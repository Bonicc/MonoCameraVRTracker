"""One Euro position smoothing and shortest-arc quaternion smoothing.

The adaptive cutoff follows Casiez et al.'s One Euro filter: high motion
increases cutoff, preserving responsiveness while reducing standing jitter.
"""

from __future__ import annotations

from dataclasses import replace
import math

from .types import Quat, TrackingFrame, Vec3, add, mul, norm, normalize_quaternion, slerp, sub


def _alpha(cutoff: float, dt: float) -> float:
    return 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff * dt))


def _validate_parameters(min_cutoff: float, beta: float, derivative_cutoff: float, max_gap: float) -> None:
    if not all(math.isfinite(x) for x in (min_cutoff, beta, derivative_cutoff, max_gap)):
        raise ValueError("Filter parameters must be finite")
    if min_cutoff <= 0.0 or beta < 0.0 or derivative_cutoff <= 0.0 or max_gap <= 0.0:
        raise ValueError("Cutoffs and max_gap must be positive; beta must be nonnegative")


class OneEuroVector:
    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.08, derivative_cutoff: float = 1.0, max_gap: float = 0.5) -> None:
        _validate_parameters(min_cutoff, beta, derivative_cutoff, max_gap)
        self.min_cutoff, self.beta = min_cutoff, beta
        self.derivative_cutoff, self.max_gap = derivative_cutoff, max_gap
        self.reset()

    def reset(self) -> None:
        self._timestamp: float | None = None
        self._raw: Vec3 | None = None
        self._filtered: Vec3 | None = None
        self._derivative: Vec3 = (0.0, 0.0, 0.0)

    def filter(self, value: Vec3, timestamp: float) -> Vec3:
        dt = 0.0 if self._timestamp is None else timestamp - self._timestamp
        if self._raw is None or dt <= 0.0 or dt > self.max_gap:
            self.reset()
            self._raw = self._filtered = value
            self._timestamp = timestamp
            return value
        derivative = mul(sub(value, self._raw), 1.0 / dt)
        derivative_alpha = _alpha(self.derivative_cutoff, dt)
        self._derivative = add(mul(derivative, derivative_alpha), mul(self._derivative, 1.0 - derivative_alpha))
        cutoff = self.min_cutoff + self.beta * norm(self._derivative)
        alpha = _alpha(cutoff, dt)
        self._filtered = add(mul(value, alpha), mul(self._filtered, 1.0 - alpha))
        self._raw, self._timestamp = value, timestamp
        return self._filtered


class OneEuroQuaternion:
    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.08, derivative_cutoff: float = 1.0, max_gap: float = 0.5) -> None:
        _validate_parameters(min_cutoff, beta, derivative_cutoff, max_gap)
        self.min_cutoff, self.beta = min_cutoff, beta
        self.derivative_cutoff, self.max_gap = derivative_cutoff, max_gap
        self.reset()

    def reset(self) -> None:
        self._timestamp: float | None = None
        self._raw: Quat | None = None
        self._filtered: Quat | None = None
        self._angular_speed = 0.0

    def filter(self, value: Quat, timestamp: float) -> Quat:
        value = normalize_quaternion(value)
        dt = 0.0 if self._timestamp is None else timestamp - self._timestamp
        if self._raw is None or dt <= 0.0 or dt > self.max_gap:
            self.reset()
            self._raw = self._filtered = value
            self._timestamp = timestamp
            return value
        cosine = sum(a * b for a, b in zip(self._raw, value))
        if cosine < 0.0:
            value = tuple(-v for v in value)
            cosine = -cosine
        angular_speed = 2.0 * math.acos(min(1.0, max(0.0, cosine))) / dt
        derivative_alpha = _alpha(self.derivative_cutoff, dt)
        self._angular_speed += derivative_alpha * (angular_speed - self._angular_speed)
        alpha = _alpha(self.min_cutoff + self.beta * self._angular_speed, dt)
        self._filtered = slerp(self._filtered, value, alpha)
        self._raw, self._timestamp = value, timestamp
        return self._filtered


class MotionSmoother:
    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.08, derivative_cutoff: float = 1.0, max_gap: float = 0.5) -> None:
        _validate_parameters(min_cutoff, beta, derivative_cutoff, max_gap)
        self._parameters = (min_cutoff, beta, derivative_cutoff, max_gap)
        self._filters: dict[str, tuple[OneEuroVector, OneEuroQuaternion]] = {}

    def reset(self) -> None:
        self._filters.clear()

    def filter(self, frame: TrackingFrame) -> TrackingFrame:
        roles = {pose.role for pose in frame.trackers}
        self._filters = {role: filters for role, filters in self._filters.items() if role in roles}
        output = []
        for pose in frame.trackers:
            if pose.role not in self._filters:
                self._filters[pose.role] = (OneEuroVector(*self._parameters), OneEuroQuaternion(*self._parameters))
            positions, rotations = self._filters[pose.role]
            output.append(replace(pose, position=positions.filter(pose.position, frame.timestamp), rotation=rotations.filter(pose.rotation, frame.timestamp)))
        return TrackingFrame(frame.timestamp, tuple(output))
