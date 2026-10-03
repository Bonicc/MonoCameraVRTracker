"""Defensive skeleton processing, calibration, smoothing and contact lock."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

from .backend import Backend
from .calibration import Calibration
from .foot_lock import FootLock
from .joint_mapper import JointMapper
from .smoothing import MotionSmoother
from .types import Skeleton, TrackingFrame, valid_joint


@dataclass(frozen=True)
class PipelineConfig:
    max_age_seconds: float = 0.25
    loss_reset_seconds: float = 0.5
    smoothing: bool = True
    foot_lock: bool = False
    min_confidence: float = 0.2
    min_cutoff: float = 1.5
    beta: float = 0.08
    derivative_cutoff: float = 1.0
    future_tolerance_seconds: float = 0.05

    def __post_init__(self) -> None:
        values = (self.max_age_seconds, self.loss_reset_seconds, self.min_confidence, self.min_cutoff, self.beta, self.derivative_cutoff, self.future_tolerance_seconds)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Pipeline configuration must be finite")
        if self.max_age_seconds <= 0.0 or self.loss_reset_seconds <= 0.0 or self.min_cutoff <= 0.0 or self.derivative_cutoff <= 0.0 or self.beta < 0.0 or self.future_tolerance_seconds < 0.0 or not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("Invalid pipeline configuration")


class TrackingPipeline:
    def __init__(self, backend: Backend | None = None, config: PipelineConfig | None = None, calibration: Calibration | None = None) -> None:
        self.backend = backend
        self.config = config or PipelineConfig()
        self.calibration = calibration or Calibration()
        self.mapper = JointMapper(self.config.min_confidence)
        self.smoother = MotionSmoother(self.config.min_cutoff, self.config.beta, self.config.derivative_cutoff, self.config.loss_reset_seconds)
        self.foot_lock = FootLock(max_gap=self.config.loss_reset_seconds)
        self._last_timestamp: float | None = None
        self.last_rejection: str | None = None

    def reset(self) -> None:
        self.smoother.reset()
        self.foot_lock.reset()
        self._last_timestamp = None

    def set_calibration(self, calibration: Calibration) -> None:
        self.calibration = calibration
        self.reset()

    def _reject(self, reason: str) -> None:
        self.reset()
        self.last_rejection = reason
        return None

    def process(self, frame: Any, timestamp: float | None = None) -> TrackingFrame | None:
        if self.backend is None:
            raise RuntimeError("process() requires a backend; use process_skeleton() for externally inferred poses")
        capture_timestamp = time.monotonic() if timestamp is None else timestamp
        skeleton = self.backend.infer(frame, capture_timestamp)
        # Explicit clocks are useful for deterministic recordings and unit tests.
        now = time.monotonic() if timestamp is None else timestamp
        return self.process_skeleton(skeleton, now)

    def process_skeleton(self, skeleton: Skeleton | None, timestamp: float | None = None) -> TrackingFrame | None:
        now = time.monotonic() if timestamp is None else timestamp
        if skeleton is None:
            return self._reject("tracking_lost")
        if not isinstance(skeleton, Skeleton) or not isinstance(skeleton.joints, dict):
            return self._reject("invalid_skeleton")
        if not isinstance(skeleton.timestamp, (float, int)) or not isinstance(now, (float, int)) or not math.isfinite(skeleton.timestamp) or not math.isfinite(now):
            return self._reject("invalid_timestamp")
        age = now - skeleton.timestamp
        if age > self.config.max_age_seconds:
            return self._reject("stale_observation")
        if age < -self.config.future_tolerance_seconds:
            return self._reject("future_observation")
        if any(not valid_joint(joint) for joint in skeleton.joints.values()):
            return self._reject("invalid_joint")
        if self._last_timestamp is not None:
            gap = skeleton.timestamp - self._last_timestamp
            if gap <= 0.0 or gap > self.config.loss_reset_seconds:
                self.reset()
        calibrated = self.calibration.apply(skeleton)
        result = self.mapper.map(calibrated)
        if result is None:
            return self._reject("missing_or_low_confidence_joints")
        if self.config.smoothing:
            result = self.smoother.filter(result)
        if self.config.foot_lock:
            result = self.foot_lock.filter(result)
        self._last_timestamp = skeleton.timestamp
        self.last_rejection = None
        return result

    def close(self) -> None:
        self.reset()
        if self.backend is not None:
            self.backend.close()

    def __enter__(self) -> TrackingPipeline:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
