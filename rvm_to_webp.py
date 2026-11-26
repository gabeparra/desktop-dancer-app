"""RVM matting -> Animated WebP (alpha + compression).

Usage:
    rvm_to_webp.py <src> <dst> <w> <h> <fps> <start_sec> <duration_sec>
                   [--backbone mobilenetv3|resnet50]
                   [--device auto|cuda|mps|cpu]
                   [--alpha-low 0.05] [--alpha-high 0.5]
                   [--quality 75]

Alpha levels curve: out = clamp((pha - low) / (high - low), 0, 1).
Defaults push pha=0.5 to fully opaque (fixes "see-through dancers")
while keeping pha<0.05 transparent (preserves hair tip softness).
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(
        description="Cut an animated transparent WebP from a video using Robust Video Matting."
    )
    p.add_argument("src", help="Source video file")
    p.add_argument("dst", help="Output animated .webp path")
    p.add_argument("w", type=int, help="Output width in pixels")
    p.add_argument("h", type=int, help="Output height in pixels")
    p.add_argument("fps", type=int, help="Output frames per second")
    p.add_argument("start", type=str, help="Start offset (ffmpeg -ss format, e.g. '0' or '00:05')")
    p.add_argument("duration", type=str, help="Clip duration in seconds (ffmpeg -t format)")
    p.add_argument("--backbone", choices=["mobilenetv3", "resnet50"], default="mobilenetv3")
    p.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto")
    p.add_argument("--alpha-low", type=float, default=0.05)
    p.add_argument("--alpha-high", type=float, default=0.5)
    p.add_argument("--quality", type=int, default=75)
    p.add_argument("--downsample-ratio", type=float, default=0.4)
    return p.parse_args(argv)


def validate_args(a: argparse.Namespace) -> None:
    if not Path(a.src).is_file():
        raise ValueError(f"Source video not found: {a.src}")
    if a.w <= 0 or a.h <= 0:
        raise ValueError(f"Width and height must be positive (got {a.w}x{a.h})")
    if a.fps <= 0:
        raise ValueError(f"FPS must be positive (got {a.fps})")
    if not (0.0 <= a.alpha_low < a.alpha_high <= 1.0):
        raise ValueError(
            f"alpha-low and alpha-high must satisfy 0 <= low < high <= 1 "
            f"(got {a.alpha_low}, {a.alpha_high})"
        )
    if not (0 <= a.quality <= 100):
        raise ValueError(f"Quality must be between 0 and 100 (got {a.quality})")
    if a.downsample_ratio <= 0 or a.downsample_ratio > 1.0:
        raise ValueError(f"downsample-ratio must be in (0, 1] (got {a.downsample_ratio})")


def select_device(requested: str, torch_mod) -> str:
    if requested != "auto":
        if requested == "cuda" and not torch_mod.cuda.is_available():
            raise RuntimeError("CUDA requested (--device cuda) but no CUDA GPU is available.")
        if requested == "mps" and not (
            hasattr(torch_mod.backends, "mps") and torch_mod.backends.mps.is_available()
        ):
            raise RuntimeError("MPS requested (--device mps) but MPS is not available.")
        return requested
    if torch_mod.cuda.is_available():
        return "cuda"
    if hasattr(torch_mod.backends, "mps") and torch_mod.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_decode_cmd(a: argparse.Namespace) -> list[str]:
    # Always scale explicitly to w x h so rawvideo byte offsets never drift
    # if the source video isn't already exact target dimensions.
    return [
        "ffmpeg", "-loglevel", "error",
        "-ss", str(a.start), "-i", str(a.src), "-t", str(a.duration),
        "-vf", f"scale={a.w}:{a.h}:flags=lanczos",
        "-r", str(a.fps),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]


def build_encode_cmd(a: argparse.Namespace) -> list[str]:
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{a.w}x{a.h}", "-r", str(a.fps), "-i", "-",
        "-c:v", "libwebp_anim", "-loop", "0",
        "-quality", str(a.quality), "-compression_level", "6",
        "-pix_fmt", "yuva420p",
        str(a.dst),
    ]


def _read_exact(stream, size: int) -> bytes:
    """Read exactly ``size`` bytes unless EOF is reached."""
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def main(argv: list[str] | None = None):
    a = parse_args(argv)
    try:
        validate_args(a)
    except ValueError as err:
        sys.exit(f"rvm_to_webp: {err}")

    if shutil.which("ffmpeg") is None:
        sys.exit("rvm_to_webp: ffmpeg not found on PATH.")

    import numpy as np
    import torch

    try:
        device = select_device(a.device, torch)
    except RuntimeError as err:
        sys.exit(f"rvm_to_webp: {err}")

    print(f"Loading RVM ({a.backbone} on {device})...", flush=True)
    model = torch.hub.load("PeterL1n/RobustVideoMatting", a.backbone, trust_repo=True)
    model = model.to(device).eval()

    dec = subprocess.Popen(
        build_decode_cmd(a),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    enc = subprocess.Popen(
        build_encode_cmd(a),
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    frame_bytes = a.w * a.h * 3
    rec = [None] * 4
    n = 0
    span = max(1e-3, a.alpha_high - a.alpha_low)
    try:
        with torch.no_grad():
            while True:
                buf = _read_exact(dec.stdout, frame_bytes)
                if len(buf) < frame_bytes:
                    break
                rgb = np.frombuffer(buf, np.uint8).reshape(a.h, a.w, 3).copy()
                src = torch.from_numpy(rgb).to(device).float().permute(2, 0, 1).unsqueeze(0) / 255.0
                fgr, pha, *rec = model(src, *rec, downsample_ratio=a.downsample_ratio)
                pha = ((pha - a.alpha_low) / span).clamp(0, 1)
                rgba = torch.cat([fgr, pha], dim=1).clamp(0, 1)
                out = (rgba[0].permute(1, 2, 0) * 255).byte().cpu().numpy().tobytes()
                enc.stdin.write(out)
                n += 1
    except BrokenPipeError:
        pass
    finally:
        if enc.stdin and not enc.stdin.closed:
            try:
                enc.stdin.close()
            except BrokenPipeError:
                pass
        if dec.stdout and not dec.stdout.closed:
            dec.stdout.close()
        dec_err = dec.stderr.read().decode(errors="replace").strip() if dec.stderr else ""
        enc_err = enc.stderr.read().decode(errors="replace").strip() if enc.stderr else ""
        dec_rc = dec.wait()
        enc_rc = enc.wait()

    if dec_rc != 0:
        sys.exit(f"rvm_to_webp: ffmpeg decode failed (exit {dec_rc}): {dec_err}")
    if enc_rc != 0:
        sys.exit(f"rvm_to_webp: ffmpeg encode failed (exit {enc_rc}): {enc_err}")
    if n == 0:
        sys.exit("rvm_to_webp: decoded 0 frames; check start offset, duration, and input file.")
    print(f"Done: {n} frames -> {a.dst}", flush=True)


if __name__ == "__main__":
    main()
