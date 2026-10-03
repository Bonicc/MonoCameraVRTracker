"""Convert a camera skeleton to waist and ankle tracker poses."""

from __future__ import annotations

import math

from .types import (
    Joint, Skeleton, TrackerPose, TrackingFrame, Vec3, add, cross, dot, mul,
    finite_vector, norm, quaternion_from_basis, sub, unit, valid_joint,
)


REQUIRED_JOINTS = (
    "pelvis", "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle",
)


def _orthogonal_up(right: Vec3, candidate: Vec3) -> Vec3:
    projected = sub(candidate, mul(right, dot(candidate, right)))
    if norm(projected) < 1e-7:
        fallback = (0.0, 1.0, 0.0) if abs(right[1]) < 0.9 else (0.0, 0.0, 1.0)
        projected = sub(fallback, mul(right, dot(fallback, right)))
    return unit(projected)


class JointMapper:
    def __init__(self, min_confidence: float = 0.2) -> None:
        if not math.isfinite(min_confidence) or not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        self.min_confidence = min_confidence

    def map(self, skeleton: Skeleton) -> TrackingFrame | None:
        try:
            return self._map(skeleton)
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            # A corrupt or numerically degenerate single observation is loss,
            # not a reason to terminate the live capture process.
            return None

    def _map(self, skeleton: Skeleton) -> TrackingFrame | None:
        if not math.isfinite(skeleton.timestamp):
            return None
        joints = skeleton.joints
        if any(not valid_joint(joints.get(name), self.min_confidence) for name in REQUIRED_JOINTS):
            return None
        pelvis = joints["pelvis"]
        hip_direction = sub(joints["right_hip"].position, joints["left_hip"].position)
        if not finite_vector(hip_direction) or not math.isfinite(norm(hip_direction)) or norm(hip_direction) < 1e-7:
            return None
        right = unit(hip_direction)
        shoulders = [joints.get(f"{side}_shoulder") for side in ("left", "right")]
        if all(valid_joint(j, self.min_confidence) for j in shoulders):
            shoulder_midpoint = mul(add(shoulders[0].position, shoulders[1].position), 0.5)  # type: ignore[union-attr]
            torso_up = sub(shoulder_midpoint, pelvis.position)
            waist_confidence = min(pelvis.confidence, *(j.confidence for j in shoulders))  # type: ignore[union-attr]
        else:
            knee_midpoint = mul(add(joints["left_knee"].position, joints["right_knee"].position), 0.5)
            torso_up = sub(pelvis.position, knee_midpoint)
            waist_confidence = pelvis.confidence
        if not finite_vector(torso_up):
            return None
        up = _orthogonal_up(right, torso_up)
        backward = unit(cross(right, up), (0.0, 0.0, 1.0))
        waist_rotation = quaternion_from_basis(right, up, backward)
        waist_confidence = min(waist_confidence, joints["left_hip"].confidence, joints["right_hip"].confidence)
        poses = [TrackerPose("waist", pelvis.position, waist_rotation, waist_confidence)]
        for side in ("left", "right"):
            ankle = joints[f"{side}_ankle"]
            knee = joints[f"{side}_knee"]
            shin = sub(knee.position, ankle.position)
            if not finite_vector(shin) or not math.isfinite(norm(shin)) or norm(shin) < 1e-7:
                return None
            foot_up = unit(shin)
            heel, toe = joints.get(f"{side}_heel"), joints.get(f"{side}_toe")
            confidence = min(ankle.confidence, knee.confidence)
            foot_backward = backward
            if valid_joint(toe, self.min_confidence):
                base = heel if valid_joint(heel, self.min_confidence) else ankle
                toe_direction = sub(toe.position, base.position)  # type: ignore[union-attr]
                if norm(toe_direction) > 1e-7:
                    foot_backward = mul(unit(toe_direction), -1.0)
                    confidence = min(confidence, toe.confidence, base.confidence)  # type: ignore[union-attr]
            foot_right = cross(foot_up, foot_backward)
            if norm(foot_right) < 1e-7:
                foot_right = sub(right, mul(foot_up, dot(right, foot_up)))
            if norm(foot_right) < 1e-7:
                return None
            foot_right = unit(foot_right)
            foot_backward = unit(cross(foot_right, foot_up))
            rotation = quaternion_from_basis(foot_right, foot_up, foot_backward)
            poses.append(TrackerPose(f"{side}_foot", ankle.position, rotation, confidence))
        return TrackingFrame(skeleton.timestamp, tuple(poses))
