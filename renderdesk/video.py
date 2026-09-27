"""Frames to one mp4. Every editor-facing output goes through here."""
import re
import subprocess
from pathlib import Path


def frame_numbers(frames_dir):
    out = []
    for path in Path(frames_dir).glob("frame_*.png"):
        match = re.fullmatch(r"frame_(\d+)", path.stem)
        if match and path.stat().st_size > 0:
            out.append(int(match.group(1)))
    return sorted(out)


def mux(frames_dir, out_mp4, fps, ffmpeg="ffmpeg"):
    """Encode the PNG sequence as H.264 that Premiere opens without transcoding."""
    numbers = frame_numbers(frames_dir)
    if not numbers:
        raise RuntimeError("no frames were rendered, so there is nothing to encode")
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-framerate", str(fps),
        "-start_number", str(numbers[0]),
        "-i", str(Path(frames_dir) / "frame_%05d.png"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_mp4.exists():
        raise RuntimeError("ffmpeg failed:\n" + proc.stderr[-1500:])
    return {"file": out_mp4, "frames": len(numbers), "first": numbers[0], "last": numbers[-1]}
