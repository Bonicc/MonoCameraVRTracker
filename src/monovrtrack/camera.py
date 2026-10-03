"""Continuously drain webcams into a single latest-frame slot."""

from __future__ import annotations

import threading
import time


class LatestFrameCapture:
    """One reader owns capture.read/release; the inference thread consumes latest.

    Timestamps mark retrieval from the camera API, not hardware exposure. A
    device/OS backend may still buffer internally. No frames are queued here.
    """

    def __init__(self, capture):
        self._capture = capture
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._latest = None
        self._sequence = 0
        self._consumed = 0
        self._ended = False
        self._error = None
        self._thread = threading.Thread(target=self._reader, name="camera-latest", daemon=True)
        self._thread.start()

    def _reader(self):
        try:
            while not self._stop.is_set():
                ok, frame = self._capture.read()
                if not ok:
                    break
                acquired = time.monotonic()
                with self._condition:
                    self._latest = (frame, acquired)
                    self._sequence += 1
                    self._condition.notify_all()
        except Exception as exc:
            self._error = exc
        finally:
            self._capture.release()
            with self._condition:
                self._ended = True
                self._condition.notify_all()

    def read(self, timeout: float = 5):
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._sequence == self._consumed and not self._ended and not self._stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Camera timed out waiting for a new frame")
                self._condition.wait(remaining)
            if self._error is not None:
                raise RuntimeError(f"Camera acquisition failed: {self._error}") from self._error
            if self._sequence != self._consumed and not self._stop.is_set():
                self._consumed = self._sequence
                frame, acquired = self._latest
                return True, frame, acquired
            return False, None, time.monotonic()

    def close(self):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        # Some camera drivers block read on unplug. The daemon owns release when
        # it returns; never release concurrently with an active native read.
        self._thread.join(timeout=1)
