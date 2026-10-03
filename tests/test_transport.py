import math
import socket
import struct

import pytest

from monovrtrack.tracking.types import TrackerPose, TrackingFrame
from monovrtrack.transport.udp_bridge import (PACKET_SIZE, UDPBridge, decode_packet,
                                             encode_packet)


def sample():
    return TrackingFrame(123.5, tuple(TrackerPose(r, (i + 0.25, 1.0, -2.0),
                                                (1.0, 0.0, 0.0, 0.0), 0.75)
                                    for i, r in enumerate(("waist", "left_foot", "right_foot"))))


def test_wire_offsets_and_udp_loopback():
    frame = sample()
    packet = encode_packet(frame, 42)
    assert len(packet) == PACKET_SIZE == 236
    assert packet[:4] == b"MVR1"
    assert struct.unpack_from("<d", packet, 28)[0] == 0.25
    assert struct.unpack_from("<d", packet, 52)[0] == 1.0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(2)
        bridge = UDPBridge(port=listener.getsockname()[1])
        try:
            bridge.send(frame)
            received, _ = listener.recvfrom(4096)
            sequence, decoded = decode_packet(received)
            assert sequence == 0
            assert decoded == frame
        finally:
            bridge.close()
    assert decode_packet(packet) == (42, frame)


@pytest.mark.parametrize("mutation", ["short", "nan", "duplicate", "bad_version", "bad_quat"])
def test_bad_packets_rejected(mutation):
    data = bytearray(encode_packet(sample()))
    if mutation == "short":
        data = data[:-1]
    elif mutation == "nan":
        struct.pack_into("<d", data, 28, math.nan)
    elif mutation == "duplicate":
        data[92] = 0
    elif mutation == "bad_version":
        data[4] = 2
    elif mutation == "bad_quat":
        struct.pack_into("<d", data, 52, 0.0)
    with pytest.raises(ValueError):
        decode_packet(bytes(data))


def test_sequence_wrap():
    assert decode_packet(encode_packet(sample(), 2**32))[0] == 0
