"""Render on this Mac. Free, slow, and the machine is busy while it runs.

Real purpose: it is the same code path as the GPU provider, so the whole desk can
be proven end to end without spending a cent.
"""
import platform
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "render_job.py"


class LocalProvider:
    name = "local"

    def __init__(self, cfg):
        self.cfg = cfg

    def device(self):
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            return "METAL"
        return "NONE"

    def render(self, blend, frames_dir, opts, log):
        frames_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.cfg["BLENDER"], "-b", str(blend), "--factory-startup", "-noaudio",
            "--python", str(SCRIPT), "--",
            "--out", str(frames_dir), "--device", self.device(),
        ]
        if opts.get("samples"):
            cmd += ["--samples", str(opts["samples"])]
        if opts.get("scale"):
            cmd += ["--scale", str(opts["scale"])]

        started = time.time()
        result = {"provider": self.name, "device": self.device(), "cost_usd": 0.0}
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            tail.append(line)
            del tail[:-40]
            if line.startswith("RD_"):
                log(line)
            if line.startswith("RD_DEVICE"):
                result["gpu"] = line[len("RD_DEVICE "):]
        proc.wait()
        result["seconds"] = round(time.time() - started, 1)
        if proc.returncode != 0:
            raise RuntimeError("Blender exited with an error:\n" + "\n".join(tail[-25:]))
        return result
