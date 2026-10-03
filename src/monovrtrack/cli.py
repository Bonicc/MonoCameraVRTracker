"""Command line application, webcam preview, calibration and demo tools."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from contextlib import ExitStack
from pathlib import Path
import json
import math
import statistics
import sys
import time
from collections import Counter, deque

from .config import load_config
from .tracking.backend import DemoBackend, JsonlPlaybackBackend
from .tracking.calibration import Calibration
from .tracking.pipeline import PipelineConfig, TrackingPipeline
from .transport.udp_bridge import UDPBridge, decode_packet


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MonoCameraVRTracker initial prototype")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("demo", "Send a synthetic standing/walking skeleton"),
                            ("run", "Track a camera or video using Fast SAM 3D Body"),
                            ("replay", "Replay recorded canonical skeleton JSONL"),
                            ("calibrate", "Save standing floor and room alignment")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--config", type=Path)
        command.add_argument("--calibration", type=Path, help="Existing room calibration JSON")
        command.add_argument("--rate", type=float, help="Loop rate cap (0 for unlimited)")
        command.add_argument("--frames", type=int, default=120 if name == "demo" else 0,
                             help="Processed frames, 0 means until interrupted/end of input")
        command.add_argument("--no-udp", action="store_true", help="Disable SteamVR output")
        command.add_argument("--output", type=Path, help="Write resulting tracker frames as JSONL")
        command.add_argument("--record", type=Path, help="Write raw canonical skeletons as JSONL")
        command.add_argument("--preview", action="store_true", help="Open webcam/video preview; Q exits")
        command.add_argument("--zmq", metavar="ENDPOINT", help="Optional JSON PUB for tools")
        if name in ("run", "calibrate"):
            command.add_argument("--camera", type=int, help="Camera device index")
            command.add_argument("--video", type=Path, help="Use a local video instead of the webcam")
        if name == "calibrate":
            command.add_argument("--demo", action="store_true", help="Calibrate using demo input")
            command.add_argument("--save", type=Path, default=Path("calibration.json"))
            command.add_argument("--origin", type=float, nargs=3, default=(0, 0, 0),
                                 metavar=("X", "Y", "Z"), help="Standing floor origin in SteamVR meters")
            command.add_argument("--yaw-degrees", type=float, default=0,
                                 help="Rotation around room up axis")
            command.add_argument("--scale", type=float, default=1.0,
                                 help="Manual metric scale multiplier")
        if name == "replay":
            command.add_argument("path", type=Path)
            command.add_argument("--loop", action="store_true")
    listen = commands.add_parser("listen", help="Inspect UDP output while SteamVR is closed")
    listen.add_argument("--port", type=int, default=39570)
    listen.add_argument("--frames", type=int, default=1)
    listen.add_argument("--timeout", type=float, default=10)
    return parser


def _camera(config, args, stack):
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError('Install camera support with pip install -e ".[camera]"') from exc
    source = str(args.video) if args.video else (args.camera if args.camera is not None else config.camera.index)
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Cannot open video source: {source}")
    if args.video is None:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.camera.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.camera.height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        from .camera import LatestFrameCapture
        capture = LatestFrameCapture(capture)
        stack.callback(capture.close)
    else:
        stack.callback(capture.release)
    if args.preview:
        stack.callback(cv2.destroyAllWindows)
    return cv2, capture


def _summary(samples, total, valid, elapsed, rejections):
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)] if ordered else 0
    return {"frames": total, "valid_frames": valid, "dropped_frames": total - valid,
            "elapsed_seconds": round(elapsed, 4),
            "processing_fps": round(total / elapsed, 2) if elapsed else 0,
            "mean_inference_ms": round(statistics.mean(samples) * 1000, 3) if samples else 0,
            "p95_inference_ms": round(p95 * 1000, 3),
            "timing_window_frames": len(samples), "rejection_reasons": dict(rejections)}


def _run(args) -> int:
    config = load_config(args.config)
    rate = config.target_fps if args.rate is None else args.rate
    if not math.isfinite(rate) or rate < 0 or args.frames < 0:
        raise ValueError("Rate and frame count must be non-negative")
    live = args.command == "run" or (args.command == "calibrate" and not args.demo)
    calibration = Calibration.load(args.calibration) if args.calibration else None
    samples, total, valid = deque(maxlen=10000), 0, 0
    rejections = Counter()
    with ExitStack() as stack:
        capture, cv2 = None, None
        if live:
            from .tracking.sam3d_backend import SAM3DBackend
            backend = SAM3DBackend(**asdict(config.model))
            stack.callback(backend.close)
            cv2, capture = _camera(config, args, stack)
        elif args.command == "replay":
            backend = JsonlPlaybackBackend(args.path, loop=args.loop)
        else:
            backend = DemoBackend()
        if not live:
            stack.callback(backend.close)
        pipeline = TrackingPipeline(backend, PipelineConfig(**asdict(config.tracking)), calibration)
        bridges = []
        if not args.no_udp and args.command != "calibrate":
            bridges.append(UDPBridge(config.transport.host, config.transport.port))
            stack.callback(bridges[-1].close)
        if args.zmq:
            from .transport.zmq_bridge import ZMQBridge
            bridges.append(ZMQBridge(args.zmq))
            stack.callback(bridges[-1].close)
        output = stack.enter_context(args.output.open("w", encoding="utf-8")) if args.output else None
        recording = stack.enter_context(args.record.open("w", encoding="utf-8")) if args.record else None
        if live:
            print("Stand upright with both feet visible. Press Q in preview or Ctrl+C to stop.", file=sys.stderr)
        started = time.perf_counter()
        try:
            while args.frames == 0 or total < args.frames:
                frame_start = time.perf_counter()
                image = None
                acquired = time.monotonic()
                if capture is not None:
                    if args.video:
                        ok, image = capture.read()
                        acquired = time.monotonic()
                    else:
                        ok, image, acquired = capture.read()
                    if not ok:
                        if args.video:
                            break
                        raise RuntimeError("Camera stopped returning frames; restart after reconnecting it")
                inference_start = time.perf_counter()
                skeleton = backend.infer(image, acquired)
                samples.append(time.perf_counter() - inference_start)
                if skeleton is None and getattr(backend, "exhausted", False):
                    break
                total += 1
                if skeleton is not None and recording:
                    recording.write(json.dumps(asdict(skeleton), allow_nan=False) + "\n")
                tracked = pipeline.process_skeleton(skeleton, timestamp=time.monotonic())
                if tracked is not None and args.command == "calibrate":
                    if not math.isfinite(args.scale) or args.scale <= 0:
                        raise ValueError("Scale must be finite and positive")
                    calibration = Calibration.from_skeleton(skeleton, origin=tuple(args.origin),
                                                            yaw_radians=math.radians(args.yaw_degrees))
                    # Floor offset and room origin must be transformed after scaling too.
                    floor_translation = tuple((v - o) * args.scale + o
                                              for v, o in zip(calibration.translation, args.origin))
                    calibration = Calibration(args.scale, calibration.yaw_radians, floor_translation)
                    calibration.save(args.save)
                    print(json.dumps({"calibration": str(args.save.resolve()), **asdict(calibration)}))
                    return 0
                if tracked is not None and live and calibration is None:
                    calibration = Calibration.from_skeleton(skeleton)
                    pipeline.set_calibration(calibration)
                    tracked = pipeline.process_skeleton(skeleton, timestamp=time.monotonic())
                    print("Temporary floor/center calibration set. Use calibrate to save room alignment.",
                          file=sys.stderr)
                if tracked is None:
                    rejections[pipeline.last_rejection or "unknown"] += 1
                if tracked is not None:
                    valid += 1
                    for bridge in bridges:
                        bridge.send(tracked)
                    if output:
                        output.write(json.dumps(asdict(tracked), allow_nan=False) + "\n")
                if args.preview and image is not None:
                    label = "Tracking" if tracked else f"No valid pose: {pipeline.last_rejection}"
                    cv2.putText(image, label, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (0, 255, 0) if tracked else (0, 0, 255), 2)
                    if tracked:
                        for i, pose in enumerate(tracked.trackers):
                            xyz = ", ".join(f"{v:.2f}" for v in pose.position)
                            cv2.putText(image, f"{pose.role}: {xyz} m", (16, 60 + 26 * i),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                    cv2.imshow("MonoCameraVRTracker", image)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                        break
                if rate:
                    delay = 1 / rate - (time.perf_counter() - frame_start)
                    if delay > 0:
                        time.sleep(delay)
        except KeyboardInterrupt:
            pass
    summary = _summary(samples, total, valid, time.perf_counter() - started, rejections)
    print(json.dumps(summary))
    if args.command == "calibrate":
        raise RuntimeError("No valid skeleton was available for calibration")
    return 0 if valid else 1


def _listen(args) -> int:
    import socket
    if args.frames <= 0 or not 1 <= args.port <= 65535 or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("Listen count, port and timeout must be positive")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", args.port))
        receiver.settimeout(args.timeout)
        for _ in range(args.frames):
            data, _ = receiver.recvfrom(4096)
            sequence, frame = decode_packet(data)
            print(json.dumps({"sequence": sequence, **asdict(frame)}))
    return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _listen(args) if args.command == "listen" else _run(args)
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"monovrtrack: {exc}", file=sys.stderr)
        return 2
