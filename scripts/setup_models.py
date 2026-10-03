"""Fetch external inference source and, optionally, authorized model weights.

Run from the repository root with Python 3.11. Checkpoints stay ignored by Git.
No tokens are accepted as CLI arguments or written to the project.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


UPSTREAM_URL = "https://github.com/yangtiming/Fast-SAM-3D-Body.git"
UPSTREAM_REVISION = "d72aa36913a1673ace029d345f437561a85ec9e2"
MODEL_REPOSITORY = "facebook/sam-3d-body-dinov3"
MODEL_REVISION = "11aaa346c7204874a1cbafe3d39a979080b2c55a"
MODEL_FILES = ("model.ckpt", "model_config.yaml", "assets/mhr_model.pt")


def setup_source(destination: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise RuntimeError(f"Source destination already exists and is not a Git clone: {destination}")
        revision = subprocess.check_output(
            ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True
        ).strip()
        remote = subprocess.check_output(
            ["git", "-C", str(destination), "remote", "get-url", "origin"], text=True
        ).strip()
        modifications = subprocess.check_output(
            ["git", "-C", str(destination), "status", "--porcelain", "--untracked-files=no"],
            text=True,
        ).strip()
        if revision != UPSTREAM_REVISION or remote.rstrip("/").removesuffix(".git") != UPSTREAM_URL.removesuffix(".git"):
            raise RuntimeError(
                f"Existing source does not match the pinned upstream ({UPSTREAM_REVISION}). "
                "Choose a fresh --upstream-dir; your existing checkout was left untouched."
            )
        if modifications:
            raise RuntimeError(
                "External source has local tracked modifications. Choose a fresh --upstream-dir; "
                "your existing checkout was left untouched."
            )
        print(f"Verified external source: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--no-checkout", UPSTREAM_URL, str(destination)], check=True)
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", UPSTREAM_REVISION], check=True)
    print(f"Prepared external source: {destination}")


def download_models(destination: Path, revision: str = MODEL_REVISION) -> None:
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import GatedRepoError, HfHubHTTPError
    except ImportError as exc:
        raise RuntimeError("Install huggingface_hub first: python -m pip install huggingface_hub") from exc
    try:
        snapshot_download(
            repo_id=MODEL_REPOSITORY,
            revision=revision,
            local_dir=str(destination.resolve()),
            allow_patterns=[*MODEL_FILES, "LICENSE*", "README.md"],
        )
    except GatedRepoError as exc:
        raise RuntimeError(
            "This checkpoint is gated. Request access at "
            f"https://huggingface.co/{MODEL_REPOSITORY}, then run 'hf auth login' locally and retry."
        ) from exc
    except HfHubHTTPError as exc:
        # Do not print request headers or credential-bearing exception content.
        raise RuntimeError("Hugging Face download failed. Check login, access, model revision, and network.") from exc
    missing = [name for name in MODEL_FILES if not (destination / name).is_file()]
    if missing:
        raise RuntimeError(f"Downloaded snapshot is incomplete: {', '.join(missing)}")
    print(f"Prepared checkpoint files: {destination.resolve()}")


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path, default=root / "external" / "Fast-SAM-3D-Body")
    parser.add_argument("--checkpoint-dir", type=Path, default=root / "models" / "sam-3d-body-dinov3")
    parser.add_argument("--download", action="store_true", help="Download SAM weights using your local Hugging Face login")
    parser.add_argument("--model-revision", default=MODEL_REVISION, help="Hugging Face snapshot revision")
    args = parser.parse_args(argv)
    try:
        setup_source(args.upstream_dir)
        if args.download:
            download_models(args.checkpoint_dir, args.model_revision)
        else:
            print("Weights were not downloaded. After model access and local login, use --download.")
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Model setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
