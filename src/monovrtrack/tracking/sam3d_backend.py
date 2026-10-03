"""Adapter for the external, pinned Fast SAM 3D Body inference implementation.

No model source or checkpoint is bundled. See docs/sam3d.md for installation.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .types import Joint, Skeleton


# Verified against sam_3d_body/metadata/mhr70.py in Fast SAM 3D Body.
MHR70_JOINTS = {
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_hip": 9,
    "right_hip": 10,
    "left_knee": 11,
    "right_knee": 12,
    "left_ankle": 13,
    "right_ankle": 14,
    "left_toe": 15,
    "left_heel": 17,
    "right_toe": 18,
    "right_heel": 20,
    "neck": 69,
}
CAMERA_TO_TRACKING = np.array([1.0, -1.0, -1.0], dtype=np.float64)


def skeleton_from_sam3d_output(
    output: Mapping[str, Any], timestamp: float
) -> Skeleton | None:
    """Translate upstream MHR70 output to metric camera-relative joints.

    Upstream already converts centimeters to meters, and keypoints exclude the
    separately returned camera translation. Convert the translated points from
    x right/y down/z away into x right/y up/z toward the camera exactly once.
    Upstream exports no calibrated joint confidence: 1.0 means a finite result
    is available, not a probability that an occluded joint is correct.
    """
    if not math.isfinite(timestamp):
        raise ValueError("Skeleton timestamp must be finite")
    try:
        points = np.asarray(output["pred_keypoints_3d"], dtype=np.float64)
        translation = np.asarray(output["pred_cam_t"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("SAM 3D Body output lacks numeric keypoints/camera translation") from exc
    if points.shape != (70, 3) or translation.shape != (3,):
        raise RuntimeError(
            "Unsupported SAM 3D Body output schema: expected (70, 3) keypoints "
            f"and (3,) camera translation; got {points.shape} and {translation.shape}"
        )
    required_indices = list(MHR70_JOINTS.values())
    if not np.isfinite(points[required_indices]).all() or not np.isfinite(translation).all():
        return None
    camera_points = (points + translation[None, :]) * CAMERA_TO_TRACKING
    joints = {
        name: Joint(tuple(float(v) for v in camera_points[index]), confidence=1.0)
        for name, index in MHR70_JOINTS.items()
    }
    pelvis = (camera_points[9] + camera_points[10]) * 0.5
    joints["pelvis"] = Joint(tuple(float(v) for v in pelvis), confidence=1.0)
    return Skeleton(timestamp=float(timestamp), joints=joints)


def _bbox_area(output: Mapping[str, Any]) -> float:
    box = np.asarray(output.get("bbox", []), dtype=np.float64).reshape(-1)
    if box.shape != (4,) or not np.isfinite(box).all():
        return 0.0
    return float(max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1]))


def _load_estimator(
    upstream_dir: Path,
    checkpoint_path: Path,
    mhr_path: Path,
    device: str,
    detector_model_path: Path | None,
) -> Any:
    """Keep torch and the upstream package optional until this backend is used."""
    try:
        torch = importlib.import_module("torch")
    except ImportError as exc:
        raise RuntimeError("Install CUDA PyTorch and the dependencies in docs/sam3d.md") from exc
    if not torch.cuda.is_available():
        raise RuntimeError(
            "Fast SAM 3D Body requires CUDA; CUDA is unavailable in this Python environment. "
            "Check your NVIDIA driver and CUDA PyTorch installation."
        )
    if ":" in device:
        torch.cuda.set_device(torch.device(device))

    already_loaded = sys.modules.get("sam_3d_body")
    if already_loaded is not None:
        loaded_file = getattr(already_loaded, "__file__", None)
        if loaded_file is None or not Path(loaded_file).resolve().is_relative_to(upstream_dir):
            raise RuntimeError("A different sam_3d_body package is already loaded; restart the app")
    if str(upstream_dir) not in sys.path:
        sys.path.insert(0, str(upstream_dir))
    try:
        upstream = importlib.import_module("sam_3d_body")
        model, model_cfg = upstream.load_sam_3d_body(
            checkpoint_path=str(checkpoint_path), device=device, mhr_path=str(mhr_path)
        )
        detector = None
        if detector_model_path is not None:
            # Detector import is optional; full-image/explicit-box mode needs
            # neither Detectron2 nor Ultralytics.
            detector_module = importlib.import_module("tools.build_detector")
            detector = detector_module.HumanDetector(
                name="yolo", device=device, model=str(detector_model_path)
            )
        return upstream.SAM3DBodyEstimator(
            sam_3d_body_model=model,
            model_cfg=model_cfg,
            human_detector=detector,
            human_segmentor=None,
            fov_estimator=None,
        )
    except ImportError as exc:
        raise RuntimeError(
            f"Fast SAM 3D Body dependency import failed ({exc}); see docs/sam3d.md"
        ) from exc


class SAM3DBackend:
    """Single-person full-body model adapter; call infer from one thread only.

    Without detector_model_path, upstream assumes the full image contains one
    person. An explicit bbox is in original frame pixels (x1, y1, x2, y2).
    Optional YOLO detection returns None when no person is found. With multiple
    model results, the largest bounding box wins; this is not identity tracking.
    """

    def __init__(
        self,
        upstream_dir: str | Path,
        checkpoint_path: str | Path,
        mhr_path: str | Path,
        device: str = "cuda",
        inference_type: str = "body",
        bbox: Sequence[float] | None = None,
        detector_model_path: str | Path | None = None,
        camera_intrinsics: Sequence[Sequence[float]] | None = None,
        verbose: bool = False,
    ) -> None:
        if device != "cuda" and not device.startswith("cuda:"):
            raise ValueError("Fast SAM 3D Body only supports a CUDA device in this adapter")
        if inference_type not in {"body", "full"}:
            raise ValueError("inference_type must be 'body' or 'full' for full-body tracking")
        upstream = Path(upstream_dir).expanduser().resolve()
        checkpoint = Path(checkpoint_path).expanduser().resolve()
        mhr = Path(mhr_path).expanduser().resolve()
        if not (upstream / "sam_3d_body" / "__init__.py").is_file():
            raise FileNotFoundError(
                f"Fast SAM 3D Body source is missing at {upstream}; run scripts/setup_models.py"
            )
        for label, path in (("SAM checkpoint", checkpoint), ("MHR model", mhr)):
            if not path.is_file():
                raise FileNotFoundError(
                    f"{label} is missing: {path}. Request Hugging Face model access, "
                    "log in locally, then run scripts/setup_models.py --download."
                )
        config_locations = (
            checkpoint.parent / "model_config.yaml",
            checkpoint.parent.parent / "model_config.yaml",
        )
        if not any(path.is_file() for path in config_locations):
            raise FileNotFoundError("model_config.yaml must accompany the SAM checkpoint")
        detector_path = None
        if detector_model_path is not None:
            detector_path = Path(detector_model_path).expanduser().resolve()
            if not detector_path.is_file():
                raise FileNotFoundError(f"Optional YOLO model is missing: {detector_path}")
        self._bbox = None
        if bbox is not None:
            box = np.asarray(bbox, dtype=np.float32)
            if (
                box.shape != (4,) or not np.isfinite(box).all()
                or box[2] <= box[0] or box[3] <= box[1]
            ):
                raise ValueError("bbox must contain finite x1,y1,x2,y2 with positive width/height")
            self._bbox = box[None, :]
        self._camera_intrinsics = None
        if camera_intrinsics is not None:
            intrinsic = np.asarray(camera_intrinsics, dtype=np.float32)
            if intrinsic.shape != (3, 3) or not np.isfinite(intrinsic).all():
                raise ValueError("camera_intrinsics must be a finite 3x3 matrix")
            if intrinsic[0, 0] <= 0 or intrinsic[1, 1] <= 0:
                raise ValueError("camera_intrinsics focal lengths must be positive")
            torch = importlib.import_module("torch")
            # Upstream annotation says ndarray, but its implementation uses .to().
            self._camera_intrinsics = torch.as_tensor(intrinsic).unsqueeze(0)
        self.inference_type = inference_type
        self.verbose = verbose
        self._estimator = _load_estimator(upstream, checkpoint, mhr, device, detector_path)

    def infer(self, frame: Any, timestamp: float) -> Skeleton | None:
        if self._estimator is None:
            raise RuntimeError("SAM 3D Body backend is closed")
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("SAM 3D Body expects an HxWx3 BGR numpy frame")
        if frame.dtype != np.uint8 or frame.shape[0] == 0 or frame.shape[1] == 0:
            raise ValueError("SAM 3D Body expects a nonempty uint8 BGR frame")
        if not math.isfinite(timestamp):
            raise ValueError("Frame timestamp must be finite")
        if self._bbox is not None:
            height, width = frame.shape[:2]
            box = self._bbox[0]
            if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
                raise ValueError("bbox lies outside the camera frame")
        # Contiguous RGB prevents negative-stride arrays from reaching torch.
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        capture = contextlib.nullcontext() if self.verbose else contextlib.redirect_stdout(io.StringIO())
        with capture:
            outputs = self._estimator.process_one_image(
                rgb,
                bboxes=self._bbox,
                cam_int=self._camera_intrinsics,
                inference_type=self.inference_type,
            )
        if not outputs:
            return None
        return skeleton_from_sam3d_output(max(outputs, key=_bbox_area), timestamp)

    def close(self) -> None:
        self._estimator = None
        self._camera_intrinsics = None
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
