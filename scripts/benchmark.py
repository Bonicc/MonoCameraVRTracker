"""Measure the selected backend. Demo results are not GPU inference performance."""

import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("demo", "camera", "video"), default="demo")
    parser.add_argument("--config", default="config/rtx4080.yaml")
    parser.add_argument("--video")
    parser.add_argument("--frames", type=int, default=300)
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if args.source == "video" and not args.video:
        parser.error("--source video requires --video")
    command = [sys.executable, "-m", "monovrtrack", "demo" if args.source == "demo" else "run",
               "--frames", str(args.frames), "--rate", "0", "--no-udp", "--config", args.config]
    if args.video:
        command.extend(("--video", args.video))
    print(f"Benchmark source: {args.source} (including mapping/filtering; no rate cap)", file=sys.stderr)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
