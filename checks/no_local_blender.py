"""Prove the desk works on a machine with no Blender on it.

That is the Hetzner box: 4 GB of RAM serving client sites, which must never be
asked to open a heavy .blend. There the scene is inspected on the rented GPU, so
this pins that the job still gates the scene, still refuses a bad one, and still
delivers a video when the provider hands one back.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from renderdesk import config, watch  # noqa: E402

failures, ran = [], []


def check(name, condition, detail=""):
    ran.append(name)
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + (f"  {detail}" if not condition else ""))
    if not condition:
        failures.append(name)


GOOD_SCENE = {
    "blender_running": [5, 1, 2], "blender_saved_with": [5, 1, 2], "engine": "CYCLES",
    "camera": "Camera", "frame_start": 1, "frame_end": 3, "frame_step": 1, "fps": 24,
    "resolution": [64, 64], "resolution_percentage": 100, "missing_files": [],
    "objects": 3, "packed_images": 0, "samples": 4, "frames": 3,
}
BAD_SCENE = dict(GOOD_SCENE, missing_files=["//textures/skin.png", "//textures/cloth.png"])


class FakeGpu:
    """Stands in for the rented machine: inspects the scene, then hands back a video."""

    name = "runpod"

    def __init__(self, scene):
        self.scene = scene
        self.rendered = False

    def render(self, blend, frames_dir, opts, log, on_scene=None):
        log("RD_POD pod-fake NVIDIA GeForce RTX 4090 $0.74/hr")
        on_scene(self.scene)          # raises for a bad scene, before any frame is paid for
        self.rendered = True
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "render.mp4").write_bytes(b"pretend-video")
        (frames_dir / "preview.png").write_bytes(b"pretend-frame")
        return {"provider": "runpod", "gpu": "NVIDIA GeForce RTX 4090", "seconds": 90.0,
                "usd_per_hour": 0.74, "cost_usd": 0.0185, "frames_rendered": 3,
                "mp4": frames_dir / "render.mp4", "preview": frames_dir / "preview.png"}


tmp = Path(tempfile.mkdtemp())
real_blender = shutil.which("/opt/homebrew/bin/blender") or shutil.which("blender")
source = tmp / "source.blend"
subprocess.run([real_blender, "-b", "--factory-startup", "-noaudio", "--python",
                str(ROOT / "checks/make_test_blend.py"), "--", str(source)],
               capture_output=True, check=True)

cfg = config.load()
cfg.update({"INBOX": str(tmp / "in"), "WORKING": str(tmp / "work"),
            "FINISHED": str(tmp / "out"), "STATE_DIR": str(tmp / "state"),
            "PROVIDER": "runpod", "BLENDER": "/nonexistent/blender"})
dirs = watch.ensure_folders(cfg)
check("no Blender on this machine", shutil.which(cfg["BLENDER"]) is None)

# --- a good scene renders --------------------------------------------------
shutil.copy2(source, Path(cfg["INBOX"]) / "shot.blend")
gpu = FakeGpu(GOOD_SCENE)
watch.run_one(Path(cfg["INBOX"]) / "shot.blend", cfg, dirs, gpu)
delivered = list(Path(cfg["FINISHED"]).rglob("*.mp4"))
check("a video is delivered with no local Blender", bool(delivered), str(delivered))
check("the scene was inspected on the render machine", gpu.rendered)
readme = list(Path(cfg["FINISHED"]).rglob("READ-ME.txt"))
check("the editor is told what it ran on and what it cost",
      readme and "RTX 4090" in readme[0].read_text() and "$0.02" in readme[0].read_text(),
      readme[0].read_text() if readme else "")

# --- a bad scene is refused before any frame is rendered -------------------
shutil.copy2(source, Path(cfg["INBOX"]) / "broken.blend")
bad = FakeGpu(BAD_SCENE)
watch.run_one(Path(cfg["INBOX"]) / "broken.blend", cfg, dirs, bad)
note = list((tmp / "4-needs-a-fix").rglob("WHAT-WENT-WRONG.txt"))
check("a scene with missing textures is refused", bool(note), str(list((tmp / "4-needs-a-fix").iterdir())))
check("the refusal tells the editor how to fix it",
      note and "Automatically Pack Resources" in note[0].read_text())
check("no frames were paid for on the refused file", not bad.rendered)
check("the refused file produced no video",
      not list(Path(cfg["FINISHED"]).rglob("broken*")))

# --- the version gate still runs without Blender ---------------------------
(Path(cfg["INBOX"]) / "future.blend").write_bytes(b"BLENDER17-01v0990REND" + b"\0" * 64)
watch.run_one(Path(cfg["INBOX"]) / "future.blend", cfg, dirs, FakeGpu(GOOD_SCENE))
future = list((tmp / "4-needs-a-fix").rglob("future*/WHAT-WENT-WRONG.txt"))
check("the version gate works with no Blender present",
      future and "Blender 9.9" in future[0].read_text())

if failures:
    print(f"\nno_local_blender FAILED: {len(failures)}", file=sys.stderr)
    sys.exit(1)
print(f"no_local_blender: {len(ran)} checks passed")
