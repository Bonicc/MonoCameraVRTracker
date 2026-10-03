#include "protocol.hpp"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

namespace {
int checks = 0;
void Check(bool condition, const char* name) {
    ++checks;
    if (!condition) { std::cerr << "FAILED: " << name << '\n'; std::exit(1); }
}
void WriteU64(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint64_t value) {
    for (unsigned i = 0; i < 8; ++i) bytes[offset + i] = static_cast<std::uint8_t>(value >> (i * 8));
}
void WriteDouble(std::vector<std::uint8_t>& bytes, std::size_t offset, double value) {
    std::uint64_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    WriteU64(bytes, offset, bits);
}
void WriteFloat(std::vector<std::uint8_t>& bytes, std::size_t offset, float value) {
    std::uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    for (unsigned i = 0; i < 4; ++i) bytes[offset + i] = static_cast<std::uint8_t>(bits >> (i * 8));
}
}

int main(int argc, char** argv) {
    if (argc != 2) { std::cerr << "Usage: protocol_test valid_packet.hex\n"; return 2; }
    std::ifstream fixture(argv[1]);
    Check(static_cast<bool>(fixture), "Python struct-generated fixture exists");
    std::string hex;
    fixture >> hex;
    std::vector<std::uint8_t> valid;
    Check(hex.size() == monocamera::kPacketBytes * 2, "fixture exact size");
    for (std::size_t i = 0; i < hex.size(); i += 2) {
        valid.push_back(static_cast<std::uint8_t>(std::stoul(hex.substr(i, 2), nullptr, 16)));
    }
    monocamera::Frame frame;
    auto decode = [&](const std::vector<std::uint8_t>& bytes) {
        return monocamera::DecodeFrame(bytes.data(), bytes.size(), frame);
    };
    Check(decode(valid), "valid Python packet accepted");
    Check(frame.sequence == 0x12345678 && frame.producer_timestamp == 123.5, "header little endian values");
    Check(frame.trackers[0].position[1] == 1 && frame.trackers[1].position[0] == -0.2 &&
          frame.trackers[2].position[0] == 0.2, "three role positions");
    Check(frame.trackers[0].quaternion[0] == 1 && frame.trackers[2].confidence == 0.75f, "quaternion wxyz and confidence");
    auto reordered = valid;
    for (std::size_t i = 0; i < monocamera::kTrackerBytes; ++i) {
        std::swap(reordered[20 + i], reordered[20 + 2 * monocamera::kTrackerBytes + i]);
    }
    Check(decode(reordered) && frame.trackers[2].position[0] == 0.2, "wire order independent roles");
    auto unaligned = valid;
    unaligned.insert(unaligned.begin(), 0);
    Check(monocamera::DecodeFrame(unaligned.data() + 1, valid.size(), frame), "unaligned bytes decode safely");
    Check(!monocamera::DecodeFrame(nullptr, valid.size(), frame), "null rejected");
    for (std::size_t length = 0; length < valid.size(); ++length) {
        Check(!monocamera::DecodeFrame(valid.data(), length, frame), "every truncation rejected");
    }
    auto broken = valid;
    broken.push_back(0);
    Check(!decode(broken), "oversized packet rejected");
    broken = valid; broken[0] = 'X'; Check(!decode(broken), "magic rejected");
    broken = valid; broken[4] = 2; Check(!decode(broken), "version rejected");
    broken = valid; broken[6] = 2; Check(!decode(broken), "count rejected");
    broken = valid; broken[20 + 72] = 0; Check(!decode(broken), "duplicate roles rejected");
    broken = valid; broken[20] = 3; Check(!decode(broken), "unknown role rejected");
    broken = valid; WriteDouble(broken, 12, -1); Check(!decode(broken), "negative timestamp rejected");
    broken = valid; WriteDouble(broken, 12, std::numeric_limits<double>::quiet_NaN()); Check(!decode(broken), "NaN timestamp rejected");
    for (std::size_t field : {28u, 36u, 44u, 52u, 60u, 68u, 76u}) {
        broken = valid; WriteDouble(broken, field, std::numeric_limits<double>::infinity());
        Check(!decode(broken), "infinite position or quaternion rejected");
    }
    broken = valid; WriteDouble(broken, 52, 0); Check(!decode(broken), "zero quaternion rejected");
    broken = valid; WriteDouble(broken, 52, 2); Check(!decode(broken), "invalid quaternion norm rejected");
    broken = valid; WriteDouble(broken, 52, 1.05);
    Check(decode(broken) && frame.trackers[0].quaternion[0] == 1, "small quaternion drift normalized");
    for (float value : {-0.01f, 1.01f, std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::infinity()}) {
        broken = valid; WriteFloat(broken, 84, value); Check(!decode(broken), "invalid confidence rejected");
    }
    Check(decode(valid), "restore valid frame");
    broken = valid; WriteDouble(broken, 100, std::numeric_limits<double>::quiet_NaN());
    Check(!decode(broken) && frame.sequence == 0x12345678 && frame.trackers[0].confidence == 0.95f,
          "rejection leaves previous frame unchanged");
    Check(monocamera::IsPoseValid(frame.trackers[0], 0.499, 0.5f), "fresh confident tracker valid");
    Check(!monocamera::IsPoseValid(frame.trackers[0], 0.5, 0.5f), "half-second packet stale");
    Check(!monocamera::IsPoseValid(frame.trackers[0], -1, 0.5f), "negative age invalid");
    Check(!monocamera::IsPoseValid(frame.trackers[0], std::numeric_limits<double>::quiet_NaN(), 0.5f), "NaN age invalid");
    Check(!monocamera::IsPoseValid(frame.trackers[2], 0, 0.8f), "low confidence invalid");
    std::cout << checks << " native protocol checks passed.\n";
}
