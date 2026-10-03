from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from monovrtrack.tracking.sam3d_backend import SAM3DBackend, skeleton_from_sam3d_output


def model_output(*, translation=(0.2, 0.3, 2.0), box=(0, 0, 20, 20)):
    points = np.zeros((70, 3), dtype=np.float32)
    points[9] = (-0.1, -0.7, 0.0)
    points[10] = (0.1, -0.7, 0.0)
    points[13] = (-0.1, 0.2, 0.1)
    points[14] = (0.1, 0.2, 0.1)
    points[15] = (-0.1, 0.2, -0.1)
    points[18] = (0.1, 0.2, -0.1)
    return {
        "pred_keypoints_3d": points,
        "pred_cam_t": np.array(translation, dtype=np.float32),
        "bbox": np.array(box, dtype=np.float32),
    }


class FakeEstimator:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def process_one_image(self, rgb, **kwargs):
        self.calls.append((rgb, kwargs))
        return self.outputs


class SAM3DConversionTests(unittest.TestCase):
    def test_metric_translation_axis_conversion_and_pelvis_midpoint(self):
        skeleton = skeleton_from_sam3d_output(model_output(), 1.25)
        self.assertIsNotNone(skeleton)
        np.testing.assert_allclose(skeleton.joints["pelvis"].position, (0.2, 0.4, -2.0), atol=1e-6)
        np.testing.assert_allclose(skeleton.joints["left_ankle"].position, (0.1, -0.5, -2.1), atol=1e-6)
        np.testing.assert_allclose(skeleton.joints["right_toe"].position, (0.3, -0.5, -1.9), atol=1e-6)
        self.assertEqual(skeleton.timestamp, 1.25)
        self.assertEqual(skeleton.joints["pelvis"].confidence, 1.0)

    def test_nonfinite_required_joint_reports_tracking_lost(self):
        output = model_output()
        output["pred_keypoints_3d"][13, 1] = np.nan
        self.assertIsNone(skeleton_from_sam3d_output(output, 2.0))

    def test_nonfinite_translation_reports_tracking_lost(self):
        self.assertIsNone(skeleton_from_sam3d_output(model_output(translation=(0, np.inf, 2)), 2.0))

    def test_unsupported_schema_fails_clearly(self):
        output = model_output()
        output["pred_keypoints_3d"] = np.zeros((17, 3))
        with self.assertRaisesRegex(RuntimeError, "Unsupported SAM 3D Body output schema"):
            skeleton_from_sam3d_output(output, 1.0)

    def test_missing_translation_does_not_fabricate_camera_location(self):
        output = model_output()
        del output["pred_cam_t"]
        with self.assertRaisesRegex(RuntimeError, "translation"):
            skeleton_from_sam3d_output(output, 1.0)

    def test_nonfinite_timestamp_is_invalid(self):
        with self.assertRaises(ValueError):
            skeleton_from_sam3d_output(model_output(), np.nan)


class SAM3DAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "upstream" / "sam_3d_body").mkdir(parents=True)
        (self.root / "upstream" / "sam_3d_body" / "__init__.py").touch()
        (self.root / "models").mkdir()
        for name in ("model.ckpt", "model_config.yaml", "mhr_model.pt"):
            (self.root / "models" / name).touch()
        self.fake = FakeEstimator([model_output()])
        self.loader_patch = patch(
            "monovrtrack.tracking.sam3d_backend._load_estimator", return_value=self.fake
        )
        self.loader = self.loader_patch.start()
        self.frame = np.full((20, 20, 3), (10, 20, 30), dtype=np.uint8)

    def tearDown(self):
        self.loader_patch.stop()
        self.temp.cleanup()

    def backend(self, **kwargs):
        return SAM3DBackend(
            self.root / "upstream", self.root / "models" / "model.ckpt",
            self.root / "models" / "mhr_model.pt", **kwargs,
        )

    def test_bgr_frame_is_converted_to_contiguous_rgb_and_body_mode(self):
        backend = self.backend()
        self.assertIsNotNone(backend.infer(self.frame, 3.0))
        rgb, kwargs = self.fake.calls[-1]
        np.testing.assert_array_equal(rgb[0, 0], (30, 20, 10))
        self.assertTrue(rgb.flags.c_contiguous)
        self.assertEqual(kwargs["inference_type"], "body")

    def test_largest_detected_person_wins(self):
        self.fake.outputs = [
            model_output(translation=(1, 0, 2), box=(0, 0, 2, 2)),
            model_output(translation=(4, 0, 2), box=(0, 0, 20, 20)),
        ]
        skeleton = self.backend().infer(self.frame, 2.0)
        self.assertAlmostEqual(skeleton.joints["pelvis"].position[0], 4.0)

    def test_no_detections_returns_none(self):
        self.fake.outputs = []
        self.assertIsNone(self.backend().infer(self.frame, 2.0))

    def test_explicit_bbox_passes_original_pixel_coordinates(self):
        backend = self.backend(bbox=(1, 2, 10, 15))
        backend.infer(self.frame, 3.0)
        np.testing.assert_array_equal(self.fake.calls[-1][1]["bboxes"], [[1, 2, 10, 15]])

    def test_outside_frame_bbox_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            self.backend(bbox=(0, 0, 40, 40)).infer(self.frame, 3.0)

    def test_float_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "uint8"):
            self.backend().infer(self.frame.astype(np.float32), 3.0)

    def test_missing_checkpoint_fails_before_loading_gpu_model(self):
        (self.root / "models" / "model.ckpt").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "Hugging Face"):
            self.backend()
        self.loader.assert_not_called()

    def test_cpu_device_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "CUDA"):
            self.backend(device="cpu")

    def test_hand_only_inference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "full-body"):
            self.backend(inference_type="hand")

    def test_close_prevents_inference(self):
        backend = self.backend()
        backend.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            backend.infer(self.frame, 3.0)


if __name__ == "__main__":
    unittest.main()
