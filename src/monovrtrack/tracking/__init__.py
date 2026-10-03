"""Public tracking API. Importing this module does not load any ML library."""

from .backend import Backend, DemoBackend, JsonlPlaybackBackend
from .calibration import Calibration
from .foot_lock import FootLock
from .joint_mapper import JointMapper, REQUIRED_JOINTS
from .pipeline import PipelineConfig, TrackingPipeline
from .smoothing import MotionSmoother, OneEuroQuaternion, OneEuroVector
from .types import Joint, Quat, Skeleton, TrackerPose, TrackingFrame, Vec3

__all__ = [
    "Backend", "Calibration", "DemoBackend", "FootLock", "Joint", "JointMapper",
    "JsonlPlaybackBackend", "MotionSmoother", "OneEuroQuaternion", "OneEuroVector",
    "PipelineConfig", "Quat", "REQUIRED_JOINTS", "Skeleton", "TrackerPose",
    "TrackingFrame", "TrackingPipeline", "Vec3",
]
