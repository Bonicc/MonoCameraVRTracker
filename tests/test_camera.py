from threading import Event
import time

from monovrtrack.camera import LatestFrameCapture


class BurstCapture:
    def __init__(self):
        self.value = 0
        self.released = Event()

    def read(self):
        self.value += 1
        return (True, self.value) if self.value <= 100 else (False, None)

    def release(self):
        self.released.set()


def test_latest_frame_overwrites_old_frames_without_repetition():
    capture = BurstCapture()
    source = LatestFrameCapture(capture)
    assert capture.released.wait(2)
    ok, value, timestamp = source.read()
    assert ok and value == 100
    assert 0 <= time.monotonic() - timestamp < 2
    assert source.read()[0] is False
    source.close()


def test_camera_failure_releases_resource_and_propagates():
    import pytest

    class BrokenCapture(BurstCapture):
        def read(self):
            raise OSError("device disconnected")

    capture = BrokenCapture()
    source = LatestFrameCapture(capture)
    assert capture.released.wait(2)
    with pytest.raises(RuntimeError, match="device disconnected"):
        source.read()
    source.close()
