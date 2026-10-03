// SteamVR loads this library; camera/model work belongs in the Python process.
#include "udp_receiver.hpp"
#include <openvr_driver.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>

namespace {

constexpr const char* kSettingsSection = "driver_monocameravrtracker";
constexpr std::array<const char*, 3> kSerials = {
    "MONOCAMERA-WAIST", "MONOCAMERA-LEFT-FOOT", "MONOCAMERA-RIGHT-FOOT"
};

vr::DriverPose_t DisconnectedPose() {
    vr::DriverPose_t pose{};
    pose.qWorldFromDriverRotation.w = 1;
    pose.qDriverFromHeadRotation.w = 1;
    pose.qRotation.w = 1;
    pose.result = vr::TrackingResult_Uninitialized;
    return pose;
}

class Tracker final : public vr::ITrackedDeviceServerDriver {
public:
    explicit Tracker(std::size_t role) : role_(role), pose_(DisconnectedPose()) {}

    vr::EVRInitError Activate(std::uint32_t device_index) override {
        std::lock_guard<std::mutex> lock(mutex_);
        device_index_ = device_index;
        const auto container = vr::VRProperties()->TrackedDeviceToPropertyContainer(device_index);
        auto* properties = vr::VRProperties();
        properties->SetStringProperty(container, vr::Prop_TrackingSystemName_String, "monocameravrtracker");
        properties->SetStringProperty(container, vr::Prop_ManufacturerName_String, "MonoCameraVRTracker");
        properties->SetStringProperty(container, vr::Prop_ModelNumber_String, "MonoCamera Virtual Tracker");
        properties->SetStringProperty(container, vr::Prop_SerialNumber_String, kSerials[role_]);
        const std::string type = std::string("monocameravrtracker/") + kSerials[role_];
        properties->SetStringProperty(container, vr::Prop_RegisteredDeviceType_String, type.c_str());
        properties->SetStringProperty(container, vr::Prop_ControllerType_String, "monocamera_tracker");
        properties->SetInt32Property(container, vr::Prop_DeviceClass_Int32, vr::TrackedDeviceClass_GenericTracker);
        properties->SetBoolProperty(container, vr::Prop_DeviceIsWireless_Bool, false);
        properties->SetBoolProperty(container, vr::Prop_DeviceProvidesBatteryStatus_Bool, false);
        // Body roles are selected in SteamVR Manage Trackers; no handed-controller role hint.
        return vr::VRInitError_None;
    }

    void Deactivate() override {
        std::lock_guard<std::mutex> lock(mutex_);
        device_index_ = vr::k_unTrackedDeviceIndexInvalid;
        pose_ = DisconnectedPose();
    }
    void EnterStandby() override {}
    void* GetComponent(const char*) override { return nullptr; }
    void DebugRequest(const char*, char* response, std::uint32_t size) override {
        if (response && size) response[0] = '\0';
    }
    vr::DriverPose_t GetPose() override {
        std::lock_guard<std::mutex> lock(mutex_);
        return pose_;
    }

    void Publish(const monocamera::TrackerPose* tracker, double age, float minimum_confidence) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (device_index_ == vr::k_unTrackedDeviceIndexInvalid) return;
        pose_ = DisconnectedPose();
        if (tracker) {
            std::copy(tracker->position.begin(), tracker->position.end(), pose_.vecPosition);
            pose_.qRotation = {tracker->quaternion[0], tracker->quaternion[1],
                               tracker->quaternion[2], tracker->quaternion[3]};
            pose_.deviceIsConnected = monocamera::IsFresh(age);
            pose_.poseIsValid = monocamera::IsPoseValid(*tracker, age, minimum_confidence);
            pose_.result = pose_.poseIsValid ? vr::TrackingResult_Running_OK : vr::TrackingResult_Running_OutOfRange;
            // Age since receipt is safe across C++/Python monotonic clock epochs.
            // Camera inference/transport latency is not known and is not predicted.
            pose_.poseTimeOffset = pose_.deviceIsConnected ? -age : 0;
        }
        vr::VRServerDriverHost()->TrackedDevicePoseUpdated(device_index_, pose_, sizeof(pose_));
    }

private:
    std::size_t role_;
    std::mutex mutex_;
    vr::TrackedDeviceIndex_t device_index_ = vr::k_unTrackedDeviceIndexInvalid;
    vr::DriverPose_t pose_{};
};

class Provider final : public vr::IServerTrackedDeviceProvider {
public:
    vr::EVRInitError Init(vr::IVRDriverContext* context) override {
        VR_INIT_SERVER_DRIVER_CONTEXT(context);
        vr::EVRSettingsError settings_error = vr::VRSettingsError_None;
        minimum_confidence_ = vr::VRSettings()->GetFloat(kSettingsSection, "minimum_confidence", &settings_error);
        if (settings_error != vr::VRSettingsError_None || !std::isfinite(minimum_confidence_) ||
            minimum_confidence_ < 0 || minimum_confidence_ > 1) {
            minimum_confidence_ = 0.5f;
        }
        if (!receiver_.Open()) {
            vr::VRDriverLog()->Log("UDP 127.0.0.1:39570 bind failed. Close other instances and restart SteamVR.");
            VR_CLEANUP_SERVER_DRIVER_CONTEXT();
            return vr::VRInitError_Driver_Failed;
        }
        for (std::size_t role = 0; role < trackers_.size(); ++role) {
            trackers_[role] = std::make_unique<Tracker>(role);
            if (!vr::VRServerDriverHost()->TrackedDeviceAdded(kSerials[role],
                    vr::TrackedDeviceClass_GenericTracker, trackers_[role].get())) {
                // Registered instances must stay alive until provider Cleanup.
                vr::VRDriverLog()->Log("A MonoCamera tracker could not be registered with SteamVR.");
            }
        }
        vr::VRDriverLog()->Log("Three MonoCamera virtual trackers ready on UDP 127.0.0.1:39570.");
        return vr::VRInitError_None;
    }

    void Cleanup() override {
        receiver_.Close();
        for (auto& tracker : trackers_) {
            if (tracker) tracker->Deactivate();
            tracker.reset();
        }
        VR_CLEANUP_SERVER_DRIVER_CONTEXT();
    }
    const char* const* GetInterfaceVersions() override { return vr::k_InterfaceVersions; }
    void RunFrame() override {
        receiver_.Poll();
        const double age = receiver_.Age();
        for (std::size_t role = 0; role < trackers_.size(); ++role) {
            if (trackers_[role]) trackers_[role]->Publish(receiver_.HasFrame() ? &receiver_.Latest().trackers[role] : nullptr,
                                                        age, minimum_confidence_);
        }
    }
    bool ShouldBlockStandbyMode() override { return false; }
    void EnterStandby() override {}
    void LeaveStandby() override {}

private:
    monocamera::UdpReceiver receiver_;
    std::array<std::unique_ptr<Tracker>, 3> trackers_{};
    float minimum_confidence_ = 0.5f;
};

Provider provider;
} // namespace

extern "C" __declspec(dllexport) void* HmdDriverFactory(const char* interface_name, int* return_code) {
    if (interface_name && std::strcmp(interface_name, vr::IServerTrackedDeviceProvider_Version) == 0) {
        if (return_code) *return_code = vr::VRInitError_None;
        return &provider;
    }
    if (return_code) *return_code = vr::VRInitError_Init_InterfaceNotFound;
    return nullptr;
}
