"""Small, validated YAML configuration; all paths are relative to the YAML file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math

import yaml


@dataclass
class ModelConfig:
    upstream_dir: str = "external/Fast-SAM-3D-Body"
    checkpoint_path: str = "models/sam-3d-body-dinov3/model.ckpt"
    mhr_path: str = "models/sam-3d-body-dinov3/assets/mhr_model.pt"
    device: str = "cuda"
    inference_type: str = "body"
    bbox: tuple[float, float, float, float] | None = None
    detector_model_path: str | None = None
    camera_intrinsics: list[list[float]] | None = None


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 1280
    height: int = 720


@dataclass
class TransportConfig:
    host: str = "127.0.0.1"
    port: int = 39570


@dataclass
class FilterConfig:
    smoothing: bool = True
    foot_lock: bool = False
    min_confidence: float = 0.2
    max_age_seconds: float = 0.5
    loss_reset_seconds: float = 0.5


@dataclass
class AppConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    tracking: FilterConfig = field(default_factory=FilterConfig)
    target_fps: float = 30.0


def _validate_model_types(model: ModelConfig) -> None:
    for name in ("upstream_dir", "checkpoint_path", "mhr_path", "device", "inference_type"):
        if not isinstance(getattr(model, name), str) or not getattr(model, name).strip():
            raise ValueError(f"model.{name} must be a non-empty string")
    if model.detector_model_path is not None and (
        not isinstance(model.detector_model_path, str) or not model.detector_model_path.strip()
    ):
        raise ValueError("model.detector_model_path must be a non-empty string or null")


def load_config(path: str | Path | None = None) -> AppConfig:
    result = AppConfig()
    if path is not None:
        path = Path(path).resolve()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML configuration: {exc}") from exc
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be a YAML mapping")
        unknown = set(raw) - {"model", "camera", "transport", "tracking", "target_fps"}
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(map(str, unknown))}")
        for key, cls in (("model", ModelConfig), ("camera", CameraConfig),
                         ("transport", TransportConfig), ("tracking", FilterConfig)):
            values = raw.get(key, {})
            if not isinstance(values, dict):
                raise ValueError(f"{key} must be a YAML mapping")
            try:
                setattr(result, key, cls(**values))
            except TypeError as exc:
                raise ValueError(f"Invalid {key} configuration: {exc}") from exc
        result.target_fps = raw.get("target_fps", result.target_fps)
        _validate_model_types(result.model)
        for key in ("upstream_dir", "checkpoint_path", "mhr_path"):
            value = Path(getattr(result.model, key))
            setattr(result.model, key, str(value if value.is_absolute() else path.parent / value))
        if result.model.detector_model_path:
            value = Path(result.model.detector_model_path)
            result.model.detector_model_path = str(value if value.is_absolute() else path.parent / value)
    _validate_model_types(result.model)
    numeric = (result.target_fps, result.tracking.max_age_seconds,
               result.tracking.loss_reset_seconds, result.tracking.min_confidence)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in numeric):
        raise ValueError("Rate and tracking values must be finite numbers")
    if result.target_fps <= 0 or min(result.tracking.max_age_seconds,
                                   result.tracking.loss_reset_seconds) <= 0:
        raise ValueError("Rate and timeout values must be positive")
    if not 0 <= result.tracking.min_confidence <= 1:
        raise ValueError("Confidence must be between zero and one")
    if result.transport.host not in ("localhost", "127.0.0.1"):
        raise ValueError("Transport requires localhost or 127.0.0.1")
    if type(result.transport.port) is not int or not 1 <= result.transport.port <= 65535:
        raise ValueError("Transport port must be between 1 and 65535")
    if type(result.camera.index) is not int or result.camera.index < 0:
        raise ValueError("Camera index must be a non-negative integer")
    if any(type(v) is not int or v <= 0 for v in (result.camera.width, result.camera.height)):
        raise ValueError("Camera dimensions must be positive integers")
    if result.model.device != "cuda" and not result.model.device.startswith("cuda:"):
        raise ValueError("Fast SAM 3D Body requires an NVIDIA CUDA device")
    if result.model.inference_type not in ("body", "full"):
        raise ValueError("inference_type must be body or full")
    if any(type(v) is not bool for v in (result.tracking.smoothing, result.tracking.foot_lock)):
        raise ValueError("smoothing and foot_lock must be YAML booleans")
    if result.model.bbox is not None:
        box = result.model.bbox
        if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
            or not (box[0] < box[2] and box[1] < box[3])):
            raise ValueError("bbox must contain finite x1,y1,x2,y2 coordinates")
        result.model.bbox = tuple(float(v) for v in box)
    if result.model.camera_intrinsics is not None:
        matrix = result.model.camera_intrinsics
        if (not isinstance(matrix, list) or len(matrix) != 3
            or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
            or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                   for row in matrix for v in row)
            or matrix[0][0] <= 0 or matrix[1][1] <= 0):
            raise ValueError("camera_intrinsics must be a finite 3x3 matrix with positive focal lengths")
    return result
