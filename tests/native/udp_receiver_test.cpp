#include "udp_receiver.hpp"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <thread>
#include <vector>

namespace {
int checks = 0;
void Check(bool condition, const char* name) {
    ++checks;
    if (!condition) { std::cerr << "FAILED: " << name << '\n'; std::exit(1); }
}
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    std::ifstream fixture(argv[1]);
    std::string hex;
    fixture >> hex;
    Check(hex.size() == monocamera::kPacketBytes * 2, "fixture size");
    std::vector<std::uint8_t> valid;
    for (std::size_t i = 0; i < hex.size(); i += 2) {
        valid.push_back(static_cast<std::uint8_t>(std::stoul(hex.substr(i, 2), nullptr, 16)));
    }
    // Use a separate localhost test port so running SteamVR need not be interrupted.
    constexpr std::uint16_t test_port = 39571;
    monocamera::UdpReceiver receiver;
    Check(receiver.Open(test_port), "exclusive localhost socket opens");
    monocamera::UdpReceiver conflicting;
    Check(!conflicting.Open(test_port), "duplicate bind fails");
    Check(!receiver.HasFrame() && !monocamera::IsFresh(receiver.Age()), "no data disconnected");
    const SOCKET sender = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    Check(sender != INVALID_SOCKET, "sender opens");
    sockaddr_in destination{};
    destination.sin_family = AF_INET;
    destination.sin_port = htons(test_port);
    destination.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    auto send = [&](const std::vector<std::uint8_t>& packet) {
        const int sent = sendto(sender, reinterpret_cast<const char*>(packet.data()),
                                static_cast<int>(packet.size()), 0,
                                reinterpret_cast<const sockaddr*>(&destination), sizeof(destination));
        Check(sent == static_cast<int>(packet.size()), "UDP packet sent");
    };
    send(valid);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    receiver.Poll();
    Check(receiver.HasFrame() && receiver.Latest().sequence == 0x12345678 &&
          monocamera::IsFresh(receiver.Age()), "real datagram decoded and fresh");
    auto next = valid;
    next[8] = 0x79;
    send(next);
    auto invalid = valid;
    invalid[4] = 2;
    send(invalid);
    send(std::vector<std::uint8_t>(1000, 0));
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    receiver.Poll();
    Check(receiver.Latest().sequence == 0x12345679, "latest valid frame survives malformed and oversized packets");
    std::this_thread::sleep_for(std::chrono::milliseconds(550));
    send(invalid);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    receiver.Poll();
    Check(!monocamera::IsFresh(receiver.Age()), "invalid packets do not refresh timeout");
    send(valid); // sequence reset/reordering is deliberately accepted by receive order
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    receiver.Poll();
    Check(monocamera::IsFresh(receiver.Age()) && receiver.Latest().sequence == 0x12345678,
          "producer can reconnect after stale data");
    closesocket(sender);
    receiver.Close();
    Check(!receiver.HasFrame(), "close clears cached frame");
    Check(conflicting.Open(test_port), "port released after close");
    conflicting.Close();
    std::cout << checks << " UDP receiver checks passed.\n";
}
