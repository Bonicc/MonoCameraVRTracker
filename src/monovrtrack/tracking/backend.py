"""Backend contract plus model-free demo and recorded skeleton playback."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .types import Joint, Skeleton, valid_joint


@runtime_checkable
class Backend(Protocol):
    def infer(self, frame: Any, timestamp: float) -> Skeleton | None: ...

    def close(self) -> None: ...


class DemoBackend:
    """Deterministic, explicitly synthetic walking skeleton for smoke tests."""

    def __init__(self) -> None:
        self._started_at: float | None = None

    def infer(self, frame: Any, timestamp: float) -> Skeleton | None:
        if not math.isfinite(timestamp):
            return None
        if self._started_at is None:
            self._started_at = timestamp
        t = timestamp - self._started_at
        sway = 0.025 * math.sin(t * 2.0)
        pelvis_y = 0.94 + 0.015 * math.cos(t * 4.0)
        positions = {
            "pelvis": (sway, pelvis_y, 0.0),
            "left_hip": (sway - 0.13, pelvis_y, 0.0),
            "right_hip": (sway + 0.13, pelvis_y, 0.0),
            "left_shoulder": (sway - 0.2, 1.45, 0.0),
            "right_shoulder": (sway + 0.2, 1.45, 0.0),
            "head": (sway, 1.73, 0.0),
        }
        for side, sign, phase in (("left", -1.0, 0.0), ("right", 1.0, math.pi)):
            wave = math.sin(t * 2.0 + phase)
            foot_y = 0.10 * max(0.0, wave)
            foot_z = 0.20 * math.cos(t * 2.0 + phase)
            x = sign * 0.13
            positions[f"{side}_ankle"] = (x, foot_y + 0.065, foot_z)
            positions[f"{side}_knee"] = (x, (pelvis_y + foot_y) * 0.50, foot_z * 0.65 + 0.06)
            positions[f"{side}_heel"] = (x, foot_y, foot_z + 0.045)
            positions[f"{side}_toe"] = (x, foot_y, foot_z - 0.16)
        return Skeleton(timestamp, {name: Joint(p) for name, p in positions.items()})

    def close(self) -> None:
        pass


class JsonlPlaybackBackend:
    """Read one skeleton per call and rebase its timestamp to the caller clock.

    Each JSONL row is {"timestamp": seconds, "joints": {"name":
    {"position": [x,y,z], "confidence": 1.0}}}. Plain position arrays are
    also accepted. This backend advances per inference; it does not sleep.
    """

    def __init__(self, path: str | Path, loop: bool = False) -> None:
        self.path = Path(path)
        self.loop = loop
        self._samples: list[Skeleton] = []
        self._index = 0
        with self.path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    timestamp = float(row.get("timestamp", len(self._samples)))
                    if not math.isfinite(timestamp) or not isinstance(row["joints"], dict):
                        raise ValueError("Invalid timestamp or joint dictionary")
                    joints = {}
                    for name, value in row["joints"].items():
                        raw_position = value["position"] if isinstance(value, dict) else value
                        confidence = float(value.get("confidence", 1.0)) if isinstance(value, dict) else 1.0
                        joint = Joint(tuple(float(v) for v in raw_position), confidence)
                        if not valid_joint(joint):
                            raise ValueError(f"Invalid joint {name!r}")
                        joints[str(name)] = joint
                    self._samples.append(Skeleton(timestamp, joints))
                except (KeyError, TypeError, ValueError, OverflowError) as error:
                    raise ValueError(f"Invalid JSONL skeleton at {self.path}:{line_number}: {error}") from error
        if not self._samples:
            raise ValueError(f"No skeleton samples in {self.path}")

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def exhausted(self) -> bool:
        return not self.loop and self._index >= len(self._samples)

    def infer(self, frame: Any, timestamp: float) -> Skeleton | None:
        if not math.isfinite(timestamp):
            return None
        if self._index >= len(self._samples):
            if not self.loop:
                return None
            self._index = 0
        sample = self._samples[self._index]
        self._index += 1
        return Skeleton(timestamp, dict(sample.joints))

    def rewind(self) -> None:
        self._index = 0

    def close(self) -> None:
        pass
