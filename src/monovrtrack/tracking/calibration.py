"""Explicit metric floor, yaw, scale and room-origin calibration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from .types import Joint, Skeleton, Vec3, finite_vector, valid_joint


@dataclass(frozen=True)
class Calibration:
    scale: float = 1.0
    yaw_radians: float = 0.0
    translation: Vec3 = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        if not math.isfinite(self.scale) or self.scale <= 0.0:
            raise ValueError("Calibration scale must be finite and positive")
        if not math.isfinite(self.yaw_radians) or not finite_vector(self.translation):
            raise ValueError("Calibration yaw and translation must be finite")

    def transform_position(self, position: Vec3) -> Vec3:
        if not finite_vector(position):
            raise ValueError("Position must contain three finite numbers")
        cosine, sine = math.cos(self.yaw_radians), math.sin(self.yaw_radians)
        x, y, z = position
        return (
            self.scale * (cosine * x + sine * z) + self.translation[0],
            self.scale * y + self.translation[1],
            self.scale * (-sine * x + cosine * z) + self.translation[2],
        )

    def apply(self, skeleton: Skeleton) -> Skeleton:
        return Skeleton(
            skeleton.timestamp,
            {name: Joint(self.transform_position(joint.position), joint.confidence)
             for name, joint in skeleton.joints.items()},
        )

    @classmethod
    def from_skeleton(
        cls,
        skeleton: Skeleton,
        known_height: float | None = None,
        origin: Vec3 = (0.0, 0.0, 0.0),
        yaw_radians: float = 0.0,
        measured_height: float | None = None,
    ) -> Calibration:
        """Align observed floor and pelvis projection to an explicit room origin.

        Capture a standing pose with both feet on the floor. Heel/toe joint
        heights are preferred to ankles. Height scaling requires a valid head
        joint, or an explicitly supplied measured_height. Head landmarks are
        not necessarily the crown: known_height must describe the same span.
        No missing body dimensions are guessed.
        """
        if not finite_vector(origin) or not math.isfinite(yaw_radians):
            raise ValueError("Calibration origin and yaw must be finite")
        pelvis = skeleton.joints.get("pelvis")
        if not valid_joint(pelvis):
            raise ValueError("Calibration requires a finite pelvis joint")
        foot_points = []
        for side in ("left", "right"):
            ground_points = [skeleton.joints.get(f"{side}_{part}") for part in ("heel", "toe")]
            valid_points = [point for point in ground_points if valid_joint(point)]
            if not valid_points:
                ankle = skeleton.joints.get(f"{side}_ankle")
                if valid_joint(ankle):
                    valid_points = [ankle]
            if not valid_points:
                raise ValueError(f"Calibration requires a valid {side} heel, toe, or ankle")
            foot_points.extend(valid_points)
        floor = min(point.position[1] for point in foot_points)
        scale = 1.0
        if known_height is not None:
            if not math.isfinite(known_height) or known_height <= 0.0:
                raise ValueError("known_height must be a finite positive height in metres")
            if measured_height is None:
                head = skeleton.joints.get("head")
                if not valid_joint(head):
                    raise ValueError("Height scaling requires a valid head joint or explicit measured_height; stature is not estimated")
                measured_height = head.position[1] - floor
            if not math.isfinite(measured_height) or measured_height <= 0.1:
                raise ValueError("Measured head-to-floor height must be finite and greater than 0.1 metres")
            scale = known_height / measured_height
        rotation = cls(scale=scale, yaw_radians=yaw_radians)
        hip = rotation.transform_position(pelvis.position)
        translation = (origin[0] - hip[0], origin[1] - scale * floor, origin[2] - hip[2])
        return cls(scale, yaw_radians, translation)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "coordinate_system": "metres_x_right_y_up_z_towards_viewer",
            "scale": self.scale,
            "yaw_radians": self.yaw_radians,
            "translation": list(self.translation),
        }
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str | Path) -> Calibration:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Calibration must be a JSON object")
        if payload.get("version") != 1:
            raise ValueError("Unsupported calibration version")
        if payload.get("coordinate_system") != "metres_x_right_y_up_z_towards_viewer":
            raise ValueError("Unsupported calibration coordinate system")
        try:
            return cls(float(payload["scale"]), float(payload["yaw_radians"]), tuple(float(v) for v in payload["translation"]))
        except (KeyError, TypeError) as exc:
            raise ValueError("Calibration requires numeric scale, yaw_radians and xyz translation") from exc
