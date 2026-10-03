"""Optional JSON publisher for inspection/tools. Native driver uses UDP."""

from dataclasses import asdict

from monovrtrack.tracking.types import TrackingFrame


class ZMQBridge:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:39571") -> None:
        try:
            import zmq
        except ImportError as exc:
            raise RuntimeError('Install the optional bridge with pip install ".[zmq]"') from exc
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.SNDHWM, 1)
        try:
            self.socket.bind(endpoint)
        except Exception:
            self.socket.close(linger=0)
            self.context.term()
            raise

    def send(self, frame: TrackingFrame) -> None:
        self.socket.send_json(asdict(frame))

    def close(self) -> None:
        self.socket.close(linger=0)
        self.context.term()
