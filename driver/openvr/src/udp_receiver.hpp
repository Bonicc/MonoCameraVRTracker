#pragma once

#include "protocol.hpp"
#include <array>
#include <chrono>
#include <string>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>

namespace monocamera {

class UdpReceiver {
public:
    using Clock = std::chrono::steady_clock;
    UdpReceiver() = default;
    UdpReceiver(const UdpReceiver&) = delete;
    UdpReceiver& operator=(const UdpReceiver&) = delete;
    ~UdpReceiver() { Close(); }

    bool Open(std::uint16_t port = kPort) {
        Close();
        WSADATA data{};
        if (WSAStartup(MAKEWORD(2, 2), &data) != 0) return false;
        initialized_ = true;
        socket_ = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (socket_ == INVALID_SOCKET) { Close(); return false; }
        // A second driver instance must not silently share the port.
        BOOL exclusive = TRUE;
        if (setsockopt(socket_, SOL_SOCKET, SO_EXCLUSIVEADDRUSE,
                       reinterpret_cast<const char*>(&exclusive), sizeof(exclusive)) != 0) {
            Close(); return false;
        }
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(port);
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (bind(socket_, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0) {
            Close(); return false;
        }
        u_long nonblocking = 1;
        if (ioctlsocket(socket_, FIONBIO, &nonblocking) != 0) { Close(); return false; }
        return true;
    }

    void Close() {
        if (socket_ != INVALID_SOCKET) { closesocket(socket_); socket_ = INVALID_SOCKET; }
        if (initialized_) { WSACleanup(); initialized_ = false; }
        has_frame_ = false;
    }

    // Only provider RunFrame owns the socket and frame. No background thread/lifetime race.
    void Poll() {
        if (socket_ == INVALID_SOCKET) return;
        std::array<std::uint8_t, kPacketBytes + 1> bytes{};
        // Bound work to avoid blocking vrserver under a flood of invalid local packets.
        for (unsigned packets = 0; packets < 256; ++packets) {
            sockaddr_in source{};
            int source_size = sizeof(source);
            const int size = recvfrom(socket_, reinterpret_cast<char*>(bytes.data()),
                                      static_cast<int>(bytes.size()), 0,
                                      reinterpret_cast<sockaddr*>(&source), &source_size);
            if (size == SOCKET_ERROR) {
                const int error = WSAGetLastError();
                if (error == WSAEMSGSIZE) continue; // oversized datagram consumed, never accepted
                break; // includes WSAEWOULDBLOCK; this function never waits
            }
            Frame candidate;
            if (source.sin_addr.s_addr == htonl(INADDR_LOOPBACK) &&
                DecodeFrame(bytes.data(), static_cast<std::size_t>(size), candidate)) {
                frame_ = candidate;
                received_at_ = Clock::now();
                has_frame_ = true;
            }
        }
    }

    bool HasFrame() const { return has_frame_; }
    const Frame& Latest() const { return frame_; }
    double Age() const {
        if (!has_frame_) return std::numeric_limits<double>::infinity();
        return std::chrono::duration<double>(Clock::now() - received_at_).count();
    }

private:
    SOCKET socket_ = INVALID_SOCKET;
    bool initialized_ = false;
    bool has_frame_ = false;
    Frame frame_{};
    Clock::time_point received_at_{};
};

} // namespace monocamera
