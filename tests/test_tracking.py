from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest

from monovrtrack.tracking import (
    Calibration, DemoBackend, FootLock, Joint, JointMapper, JsonlPlaybackBackend,
    MotionSmoother, OneEuroQuaternion, OneEuroVector, PipelineConfig, Skeleton,
    TrackerPose, TrackingFrame, TrackingPipeline,
)


def standing(timestamp: float = 10.0, x_offset: float = 0.0) -> Skeleton:
    positions = {
        "pelvis": (0.0, 1.0, 0.0),
        "left_hip": (-0.12, 1.0, 0.0), "right_hip": (0.12, 1.0, 0.0),
        "left_knee": (-0.12, 0.5, 0.0), "right_knee": (0.12, 0.5, 0.0),
        "left_ankle": (-0.12, 0.06, 0.0), "right_ankle": (0.12, 0.06, 0.0),
        "left_heel": (-0.12, 0.0, 0.03), "right_heel": (0.12, 0.0, 0.03),
        "left_toe": (-0.12, 0.0, -0.14), "right_toe": (0.12, 0.0, -0.14),
        "left_shoulder": (-0.2, 1.45, 0.0), "right_shoulder": (0.2, 1.45, 0.0),
        "head": (0.0, 1.75, 0.0),
    }
    return Skeleton(timestamp, {name: Joint((p[0] + x_offset, p[1], p[2])) for name, p in positions.items()})


def rotate(q: tuple[float, ...], v: tuple[float, ...]) -> tuple[float, ...]:
    w, x, y, z = q
    vx, vy, vz = v
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx)


class MapperTests(unittest.TestCase):
    def test_three_tracker_positions_and_unit_anatomical_rotations(self) -> None:
        frame = JointMapper().map(standing())
        self.assertIsNotNone(frame)
        self.assertEqual([p.role for p in frame.trackers], ["waist", "left_foot", "right_foot"])
        self.assertEqual(frame.trackers[0].position, (0.0, 1.0, 0.0))
        for pose in frame.trackers:
            self.assertAlmostEqual(sum(v * v for v in pose.rotation), 1.0)
            self.assertAlmostEqual(rotate(pose.rotation, (0.0, 1.0, 0.0))[1], 1.0)
        foot_forward = rotate(frame.trackers[1].rotation, (0.0, 0.0, -1.0))
        self.assertAlmostEqual(foot_forward[2], -1.0)

    def test_quaternion_rotates_with_calibration_yaw(self) -> None:
        calibrated = Calibration(yaw_radians=math.pi / 2).apply(standing())
        frame = JointMapper().map(calibrated)
        self.assertAlmostEqual(rotate(frame.trackers[0].rotation, (1.0, 0.0, 0.0))[2], -1.0)
        self.assertAlmostEqual(rotate(frame.trackers[1].rotation, (0.0, 0.0, -1.0))[0], -1.0)

    def test_missing_bad_confidence_nan_and_degenerate_pose_reject(self) -> None:
        mapper = JointMapper()
        for invalid in (Joint((math.nan, 0.0, 0.0)), Joint(("1", 0.0, 0.0)), Joint((0.0, 0.0, 0.0), 1.1), Joint((0.0, 0.0, 0.0), 0.1)):
            sample = standing()
            sample.joints["left_ankle"] = invalid
            self.assertIsNone(mapper.map(sample))
        sample = standing()
        del sample.joints["pelvis"]
        self.assertIsNone(mapper.map(sample))
        sample = standing()
        sample.joints["right_hip"] = sample.joints["left_hip"]
        self.assertIsNone(mapper.map(sample))


class CalibrationTests(unittest.TestCase):
    def test_metric_transform_floor_scale_and_room_origin(self) -> None:
        sample = standing(x_offset=2.0)
        sample = Skeleton(sample.timestamp, {name: Joint((p.position[0], p.position[1] + 0.3, p.position[2] + 3.0)) for name, p in sample.joints.items()})
        calibration = Calibration.from_skeleton(sample, known_height=3.5, yaw_radians=math.pi / 2, origin=(4.0, 0.0, -2.0))
        transformed = calibration.apply(sample)
        self.assertAlmostEqual(calibration.scale, 2.0)
        self.assertAlmostEqual(transformed.joints["left_heel"].position[1], 0.0)
        self.assertAlmostEqual(transformed.joints["pelvis"].position[0], 4.0)
        self.assertAlmostEqual(transformed.joints["pelvis"].position[2], -2.0)
        self.assertAlmostEqual(transformed.joints["head"].position[1], 3.5)

    def test_known_height_never_guesses_missing_head(self) -> None:
        sample = standing()
        del sample.joints["head"]
        with self.assertRaisesRegex(ValueError, "head joint"):
            Calibration.from_skeleton(sample, known_height=1.7)
        self.assertEqual(Calibration.from_skeleton(sample, known_height=1.7, measured_height=1.7).scale, 1.0)

    def test_calibration_roundtrip_and_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            original = Calibration(1.1, -0.2, (0.1, -0.5, 2.0))
            original.save(path)
            self.assertEqual(Calibration.load(path), original)
        for scale in (0.0, -1.0, math.inf):
            with self.assertRaises(ValueError):
                Calibration(scale=scale)


class SmoothingTests(unittest.TestCase):
    def test_position_noise_damped_and_fast_motion_more_responsive(self) -> None:
        low = OneEuroVector(min_cutoff=1.0, beta=0.0)
        adaptive = OneEuroVector(min_cutoff=1.0, beta=1.0)
        low.filter((0.0, 0.0, 0.0), 0.0)
        adaptive.filter((0.0, 0.0, 0.0), 0.0)
        damped = low.filter((1.0, 0.0, 0.0), 0.02)
        responsive = adaptive.filter((1.0, 0.0, 0.0), 0.02)
        self.assertGreater(damped[0], 0.0)
        self.assertLess(damped[0], 1.0)
        self.assertGreater(responsive[0], damped[0])

    def test_position_filter_resets_on_clock_rewind_or_long_gap(self) -> None:
        smoother = OneEuroVector()
        smoother.filter((0.0, 0.0, 0.0), 1.0)
        self.assertEqual(smoother.filter((5.0, 0.0, 0.0), 0.9), (5.0, 0.0, 0.0))
        self.assertEqual(smoother.filter((9.0, 0.0, 0.0), 2.0), (9.0, 0.0, 0.0))

    def test_quaternion_antipodes_and_short_arc(self) -> None:
        smoother = OneEuroQuaternion()
        first = smoother.filter((1.0, 0.0, 0.0, 0.0), 0.0)
        second = smoother.filter((-1.0, 0.0, 0.0, 0.0), 0.02)
        self.assertEqual(first, second)
        start = (math.cos(math.radians(179) / 2), 0.0, math.sin(math.radians(179) / 2), 0.0)
        end = (math.cos(math.radians(-179) / 2), 0.0, math.sin(math.radians(-179) / 2), 0.0)
        smoother.reset()
        smoother.filter(start, 1.0)
        result = smoother.filter(end, 1.02)
        self.assertGreater(abs(result[2]), 0.99)
        self.assertAlmostEqual(sum(v * v for v in result), 1.0)


class FootLockTests(unittest.TestCase):
    def _frame(self, t: float, x: float, y: float = 0.06, confidence: float = 1.0) -> TrackingFrame:
        return TrackingFrame(t, (TrackerPose("left_foot", (x, y, 0.0), (1.0, 0.0, 0.0, 0.0), confidence),))

    def test_standing_jitter_reduced_then_motion_and_lift_release(self) -> None:
        lock = FootLock(settle_seconds=0.05)
        for t in (0.0, 0.05, 0.10, 0.15):
            lock.filter(self._frame(t, 0.0))
        result = lock.filter(self._frame(0.20, 0.002))
        self.assertLess(result.trackers[0].position[0], 0.002)
        self.assertEqual(result.trackers[0].position[1], 0.06)
        moved = lock.filter(self._frame(0.25, 0.1))
        self.assertEqual(moved.trackers[0].position[0], 0.1)
        for t in (0.30, 0.35, 0.40, 0.45):
            lock.filter(self._frame(t, 0.1))
        lifted = lock.filter(self._frame(0.50, 0.102, 0.3))
        self.assertEqual(lifted.trackers[0].position, (0.102, 0.3, 0.0))

    def test_confidence_drop_releases_contact(self) -> None:
        lock = FootLock(settle_seconds=0.0)
        for t in (0.0, 0.05, 0.10):
            lock.filter(self._frame(t, 0.0))
        dropped = lock.filter(self._frame(0.15, 0.002, confidence=0.1))
        self.assertEqual(dropped.trackers[0].position[0], 0.002)


class PipelineTests(unittest.TestCase):
    def test_loss_clears_smoothing_then_reacquisition_starts_at_new_pose(self) -> None:
        pipeline = TrackingPipeline()
        pipeline.process_skeleton(standing(1.0), timestamp=1.0)
        lagged = pipeline.process_skeleton(standing(1.02, 1.0), timestamp=1.02)
        self.assertLess(lagged.trackers[0].position[0], 1.0)
        self.assertIsNone(pipeline.process_skeleton(None, timestamp=1.03))
        self.assertEqual(pipeline.last_rejection, "tracking_lost")
        acquired = pipeline.process_skeleton(standing(1.04, 2.0), timestamp=1.04)
        self.assertEqual(acquired.trackers[0].position[0], 2.0)

    def test_age_future_nonfinite_and_missing_rejected_without_exception(self) -> None:
        pipeline = TrackingPipeline()
        self.assertIsNone(pipeline.process_skeleton(standing(1.0), timestamp=2.0))
        self.assertEqual(pipeline.last_rejection, "stale_observation")
        self.assertIsNone(pipeline.process_skeleton(standing(2.0), timestamp=1.0))
        self.assertIsNone(pipeline.process_skeleton(standing(math.nan), timestamp=1.0))
        sample = standing()
        sample.joints["head"] = Joint((math.inf, 0.0, 0.0))
        self.assertIsNone(pipeline.process_skeleton(sample, timestamp=10.0))
        del sample.joints["head"]
        del sample.joints["left_knee"]
        self.assertIsNone(pipeline.process_skeleton(sample, timestamp=10.0))

    def test_timestamp_jump_and_configured_confidence_gate(self) -> None:
        pipeline = TrackingPipeline(config=PipelineConfig(min_confidence=0.8))
        pipeline.process_skeleton(standing(1.0), timestamp=1.0)
        frame = pipeline.process_skeleton(standing(2.0, 3.0), timestamp=2.0)
        self.assertEqual(frame.trackers[0].position[0], 3.0)
        sample = standing(2.02)
        sample.joints["pelvis"] = replace(sample.joints["pelvis"], confidence=0.7)
        self.assertIsNone(pipeline.process_skeleton(sample, timestamp=2.02))

    def test_demo_is_deterministic_and_reaches_pipeline(self) -> None:
        first, second = DemoBackend(), DemoBackend()
        self.assertEqual(first.infer(None, 50.0), second.infer(None, 50.0))
        with TrackingPipeline(DemoBackend()) as pipeline:
            frame = pipeline.process(None, timestamp=20.0)
            self.assertEqual(len(frame.trackers), 3)


class PlaybackTests(unittest.TestCase):
    def test_rebase_eof_loop_and_bad_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl"
            row = {"timestamp": 0.0, "joints": {name: {"position": list(j.position), "confidence": j.confidence} for name, j in standing().joints.items()}}
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            backend = JsonlPlaybackBackend(path)
            sample = backend.infer(None, 100.0)
            self.assertEqual(sample.timestamp, 100.0)
            self.assertTrue(backend.exhausted)
            self.assertIsNone(backend.infer(None, 101.0))
            looping = JsonlPlaybackBackend(path, loop=True)
            self.assertEqual(looping.infer(None, 100.0).joints, looping.infer(None, 101.0).joints)
            self.assertFalse(looping.exhausted)
            row["joints"]["pelvis"]["position"] = [math.nan, 0.0, 0.0]
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sample.jsonl:1"):
                JsonlPlaybackBackend(path)


if __name__ == "__main__":
    unittest.main()
