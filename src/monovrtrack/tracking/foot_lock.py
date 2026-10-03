"""Optional gentle horizontal contact stabilization.

This is a heuristic for an already calibrated floor, not an IK/contact model.
Ankle heights are preserved; fast motion, lifting and tracking loss release.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .types import TrackingFrame, Vec3, norm, sub


@dataclass
class _FootState:
    timestamp: float
    previous: Vec3
    stable_since: float | None = None
    anchor: Vec3 | None = None


class FootLock:
    def __init__(
        self,
        contact_height: float = 0.12,
        enter_speed: float = 0.08,
        release_speed: float = 0.35,
        release_distance: float = 0.08,
        settle_seconds: float = 0.08,
        strength: float = 0.8,
        min_confidence: float = 0.4,
        max_gap: float = 0.5,
        floor_height: float = 0.0,
    ) -> None:
        values = (contact_height, enter_speed, release_speed, release_distance, settle_seconds, strength, min_confidence, max_gap, floor_height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Foot lock parameters must be finite")
        if any(v < 0.0 for v in (contact_height, enter_speed, release_speed, release_distance, settle_seconds)) or not 0.0 <= strength <= 1.0 or not 0.0 <= min_confidence <= 1.0 or max_gap <= 0.0:
            raise ValueError("Invalid foot lock parameters")
        self.contact_height, self.enter_speed = contact_height, enter_speed
        self.release_speed, self.release_distance = release_speed, release_distance
        self.settle_seconds, self.strength = settle_seconds, strength
        self.min_confidence, self.max_gap, self.floor_height = min_confidence, max_gap, floor_height
        self._states: dict[str, _FootState] = {}

    def reset(self) -> None:
        self._states.clear()

    def filter(self, frame: TrackingFrame) -> TrackingFrame:
        output = []
        present = set()
        for pose in frame.trackers:
            if pose.role not in ("left_foot", "right_foot"):
                output.append(pose)
                continue
            present.add(pose.role)
            state = self._states.get(pose.role)
            dt = 0.0 if state is None else frame.timestamp - state.timestamp
            if state is None or dt <= 0.0 or dt > self.max_gap:
                self._states[pose.role] = _FootState(frame.timestamp, pose.position)
                output.append(pose)
                continue
            speed = norm(sub(pose.position, state.previous)) / dt
            height = pose.position[1] - self.floor_height
            airborne = height > self.contact_height + 0.04
            low_confidence = pose.confidence < self.min_confidence
            if state.anchor is not None:
                drift = norm(sub(pose.position, state.anchor))
                if airborne or low_confidence or speed > self.release_speed or drift > self.release_distance:
                    state.anchor = None
                    state.stable_since = None
            elif height <= self.contact_height and speed <= self.enter_speed and not low_confidence:
                if state.stable_since is None:
                    state.stable_since = frame.timestamp
                elif frame.timestamp - state.stable_since >= self.settle_seconds:
                    state.anchor = pose.position
            else:
                state.stable_since = None
            state.previous, state.timestamp = pose.position, frame.timestamp
            if state.anchor is not None:
                x = pose.position[0] + self.strength * (state.anchor[0] - pose.position[0])
                z = pose.position[2] + self.strength * (state.anchor[2] - pose.position[2])
                pose = replace(pose, position=(x, pose.position[1], z))
            output.append(pose)
        self._states = {role: state for role, state in self._states.items() if role in present}
        return TrackingFrame(frame.timestamp, tuple(output))
