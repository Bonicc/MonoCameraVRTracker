"""Small, dependency-free tracking data types and coordinate math.

Positions are metres: +X right, +Y up, +Z toward the camera/viewer.
Quaternions are right handed and ordered (w, x, y, z).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import TypeAlias

Vec3: TypeAlias = tuple[float, float, float]
Quat: TypeAlias = tuple[float, float, float, float]


@dataclass(frozen=True)
class Joint:
    position: Vec3
    confidence: float = 1.0


@dataclass(frozen=True)
class Skeleton:
    timestamp: float
    joints: dict[str, Joint]


@dataclass(frozen=True)
class TrackerPose:
    role: str
    position: Vec3
    rotation: Quat
    confidence: float = 1.0


@dataclass(frozen=True)
class TrackingFrame:
    timestamp: float
    trackers: tuple[TrackerPose, ...]


def finite_vector(value: object, length: int = 3) -> bool:
    try:
        return len(value) == length and all(isinstance(v, Real) and math.isfinite(float(v)) for v in value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return False


def valid_joint(joint: object, min_confidence: float = 0.0) -> bool:
    return (
        isinstance(joint, Joint)
        and finite_vector(joint.position)
        and isinstance(joint.confidence, (float, int))
        and math.isfinite(joint.confidence)
        and min_confidence <= joint.confidence <= 1.0
    )


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def dot(a: Vec3, b: Vec3) -> float:
    return sum(x * y for x, y in zip(a, b))


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec3) -> float:
    return math.hypot(*a)


def unit(a: Vec3, fallback: Vec3 = (0.0, 1.0, 0.0)) -> Vec3:
    length = norm(a)
    return mul(a, 1.0 / length) if length > 1e-8 else fallback


def normalize_quaternion(q: Quat) -> Quat:
    if not finite_vector(q, 4):
        raise ValueError("Quaternion must contain four finite numbers")
    length = math.hypot(*q)
    if length <= 1e-8 or not math.isfinite(length):
        raise ValueError("Quaternion cannot have zero length")
    return tuple(v / length for v in q)  # type: ignore[return-value]


def quaternion_from_basis(x: Vec3, y: Vec3, z: Vec3) -> Quat:
    """Convert an orthonormal column basis to a unit quaternion."""
    m00, m01, m02 = x[0], y[0], z[0]
    m10, m11, m12 = x[1], y[1], z[1]
    m20, m21, m22 = x[2], y[2], z[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        q = (0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(max(0.0, 1.0 + m00 - m11 - m22)) * 2.0
        q = ((m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s)
    elif m11 > m22:
        s = math.sqrt(max(0.0, 1.0 + m11 - m00 - m22)) * 2.0
        q = ((m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s)
    else:
        s = math.sqrt(max(0.0, 1.0 + m22 - m00 - m11)) * 2.0
        q = ((m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s)
    return normalize_quaternion(q)


def slerp(a: Quat, b: Quat, amount: float) -> Quat:
    """Interpolate on the shortest arc, including antipodal representations."""
    a, b = normalize_quaternion(a), normalize_quaternion(b)
    cosine = sum(x * y for x, y in zip(a, b))
    if cosine < 0.0:
        b = tuple(-v for v in b)  # type: ignore[assignment]
        cosine = -cosine
    cosine = min(1.0, max(-1.0, cosine))
    amount = min(1.0, max(0.0, amount))
    if cosine > 0.9995:
        return normalize_quaternion(tuple(x + amount * (y - x) for x, y in zip(a, b)))  # type: ignore[arg-type]
    theta = math.acos(cosine)
    denominator = math.sin(theta)
    aa = math.sin((1.0 - amount) * theta) / denominator
    bb = math.sin(amount * theta) / denominator
    return normalize_quaternion(tuple(aa * x + bb * y for x, y in zip(a, b)))  # type: ignore[arg-type]
