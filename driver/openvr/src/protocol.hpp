#pragma once

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace monocamera {

// Wire fields are decoded byte by byte, never by casting an unaligned packet.
inline constexpr std::size_t kHeaderBytes = 20;
inline constexpr std::size_t kTrackerBytes = 72;
inline constexpr std::size_t kTrackerCount = 3;
inline constexpr std::size_t kPacketBytes = kHeaderBytes + kTrackerCount * kTrackerBytes;
inline constexpr std::uint16_t kPort = 39570;
inline constexpr double kStaleSeconds = 0.5;
static_assert(kPacketBytes == 236);
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);

enum class Role : std::uint8_t { Waist = 0, LeftFoot = 1, RightFoot = 2 };

struct TrackerPose {
    Role role{};
    std::array<double, 3> position{};
    std::array<double, 4> quaternion{1.0, 0.0, 0.0, 0.0}; // w,x,y,z
    float confidence{};
};

struct Frame {
    std::uint32_t sequence{};
    double producer_timestamp{};
    std::array<TrackerPose, kTrackerCount> trackers{}; // indexed by Role, independent of wire order
};

inline std::uint16_t ReadU16(const std::uint8_t* bytes) {
    return static_cast<std::uint16_t>(bytes[0]) |
           (static_cast<std::uint16_t>(bytes[1]) << 8);
}

inline std::uint32_t ReadU32(const std::uint8_t* bytes) {
    std::uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) value |= static_cast<std::uint32_t>(bytes[i]) << (8 * i);
    return value;
}

inline std::uint64_t ReadU64(const std::uint8_t* bytes) {
    std::uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<std::uint64_t>(bytes[i]) << (8 * i);
    return value;
}

inline double ReadDouble(const std::uint8_t* bytes) {
    const std::uint64_t bits = ReadU64(bytes);
    double value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

inline float ReadFloat(const std::uint8_t* bytes) {
    const std::uint32_t bits = ReadU32(bytes);
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

inline bool DecodeFrame(const std::uint8_t* bytes, std::size_t size, Frame& output) {
    if (!bytes || size != kPacketBytes || std::memcmp(bytes, "MVR1", 4) != 0 ||
        ReadU16(bytes + 4) != 1 || ReadU16(bytes + 6) != kTrackerCount) return false;
    Frame candidate;
    candidate.sequence = ReadU32(bytes + 8);
    candidate.producer_timestamp = ReadDouble(bytes + 12);
    if (!std::isfinite(candidate.producer_timestamp) || candidate.producer_timestamp < 0) return false;
    std::array<bool, kTrackerCount> seen{};
    for (std::size_t i = 0; i < kTrackerCount; ++i) {
        const auto* record = bytes + kHeaderBytes + i * kTrackerBytes;
        const std::size_t role = record[0];
        if (role >= kTrackerCount || seen[role]) return false;
        seen[role] = true;
        TrackerPose& tracker = candidate.trackers[role];
        tracker.role = static_cast<Role>(role);
        for (std::size_t axis = 0; axis < 3; ++axis) {
            tracker.position[axis] = ReadDouble(record + 8 + axis * 8);
            if (!std::isfinite(tracker.position[axis])) return false;
        }
        double norm_squared = 0;
        for (std::size_t axis = 0; axis < 4; ++axis) {
            tracker.quaternion[axis] = ReadDouble(record + 32 + axis * 8);
            if (!std::isfinite(tracker.quaternion[axis])) return false;
            norm_squared += tracker.quaternion[axis] * tracker.quaternion[axis];
        }
        // Reject broken rotations; tolerate floating-point/filtering drift and normalize.
        if (!std::isfinite(norm_squared) || norm_squared < 0.81 || norm_squared > 1.21) return false;
        const double norm = std::sqrt(norm_squared);
        for (double& component : tracker.quaternion) component /= norm;
        tracker.confidence = ReadFloat(record + 64);
        if (!std::isfinite(tracker.confidence) || tracker.confidence < 0 || tracker.confidence > 1) return false;
    }
    output = candidate; // a rejected packet cannot partially overwrite a good frame
    return true;
}

inline bool IsFresh(double age_seconds) {
    return std::isfinite(age_seconds) && age_seconds >= 0 && age_seconds < kStaleSeconds;
}

inline bool IsPoseValid(const TrackerPose& pose, double age_seconds, float minimum_confidence) {
    return IsFresh(age_seconds) && pose.confidence >= minimum_confidence;
}

} // namespace monocamera
