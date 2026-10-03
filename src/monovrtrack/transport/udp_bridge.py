"""Versioned, fixed-size local UDP protocol shared with the OpenVR driver."""

from __future__ import annotations

import math
import socket
import struct
from collections.abc import Callable

from monovrtrack.tracking.types import TrackerPose, TrackingFrame

HEADER = struct.Struct("<4sHHId")
TRACKER = struct.Struct("<B7x3d4df4x")
ROLES = ("waist", "left_foot", "right_foot")
PACKET_SIZE = HEADER.size + len(ROLES) * TRACKER.size


def _validate_pose(pose: TrackerPose) -> None:
    if len(pose.position) != 3 or len(pose.rotation) != 4:
        raise ValueError("Position requires xyz; quaternion requires wxyz")
    if not all(math.isfinite(v) for v in (*pose.position, *pose.rotation, pose.confidence)):
        raise ValueError("Pose values must be finite")
    if not 0 <= pose.confidence <= 1:
        raise ValueError("Confidence must be between zero and one")
    norm = math.sqrt(sum(v * v for v in pose.rotation))
    if abs(norm - 1.0) > 0.01:
        raise ValueError("Quaternion must be normalized")


def encode_packet(frame: TrackingFrame, sequence: int = 0) -> bytes:
    if not math.isfinite(frame.timestamp) or frame.timestamp < 0:
        raise ValueError("Timestamp must be finite and non-negative")
    if len(frame.trackers) != 3 or {p.role for p in frame.trackers} != set(ROLES):
        raise ValueError("Exactly one waist, left_foot and right_foot pose is required")
    by_role = {p.role: p for p in frame.trackers}
    chunks = [HEADER.pack(b"MVR1", 1, 3, sequence & 0xFFFFFFFF, frame.timestamp)]
    for index, role in enumerate(ROLES):
        pose = by_role[role]
        _validate_pose(pose)
        chunks.append(TRACKER.pack(index, *pose.position, *pose.rotation, pose.confidence))
    return b"".join(chunks)


def decode_packet(data: bytes) -> tuple[int, TrackingFrame]:
    if len(data) != PACKET_SIZE:
        raise ValueError(f"Expected {PACKET_SIZE} bytes")
    magic, version, count, sequence, timestamp = HEADER.unpack_from(data)
    if (magic, version, count) != (b"MVR1", 1, 3) or not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Invalid packet header")
    poses = []
    seen = set()
    for i in range(count):
        values = TRACKER.unpack_from(data, HEADER.size + i * TRACKER.size)
        role = values[0]
        if role >= 3 or role in seen:
            raise ValueError("Invalid or duplicate tracker role")
        seen.add(role)
        pose = TrackerPose(ROLES[role], values[1:4], values[4:8], values[8])
        _validate_pose(pose)
        poses.append(pose)
    return sequence, TrackingFrame(timestamp, tuple(poses))


class UDPBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 39570,
                 socket_factory: Callable = socket.socket) -> None:
        # Driver receives loopback packets only; resolving arbitrary hosts masks mistakes.
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError("The OpenVR bridge supports local IPv4 loopback only")
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        self.destination = ("127.0.0.1", port)
        self.socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self.sequence = 0

    def send(self, frame: TrackingFrame) -> None:
        self.socket.sendto(encode_packet(frame, self.sequence), self.destination)
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF

    def close(self) -> None:
        self.socket.close()
