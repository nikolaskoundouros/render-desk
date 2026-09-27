"""One dropped file, start to finish.

The editor only ever sees four folders and one STATUS.txt written in plain English.
Frames stay off Drive: only the .blend, the status and the finished mp4 sync.
"""
import datetime as dt
import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

from . import ledger, preflight, video
from .preflight import Rejected

SETTLE_SECONDS = 20


def slugify(name):
    stem = Path(name).stem
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "job"


def human_time(seconds):
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"about {minutes} minute{'s' if minutes != 1 else ''}"
    hours = seconds / 3600
    return f"about {hours:.1f} hours"


def settled(path, wait=SETTLE_SECONDS):
    """True once the file has stopped growing, so Drive has finished syncing it."""
    try:
        first = path.stat().st_size
    except OSError:
        return False
    time.sleep(min(wait, 5))
    try:
        return first == path.stat().st_size and first > 0
    except OSError:
        return False


def options_from_name(name):
    """Filename tags, because the editor has no settings panel.

    scene_draft.blend -> fast low-res look test.  Anything else -> the settings
    already saved in the .blend.
    """
    lower = name.lower()
    if "_draft" in lower or "-draft" in lower:
        return {"scale": 50, "samples": 32, "label": "draft (half size, fast)"}
    return {"scale": 0, "samples": 0, "label": "full quality (the settings saved in the file)"}


class Job:
    def __init__(self, source, cfg, dirs):
        self.cfg = cfg
        self.inbox, self.working, self.finished, self.problems = dirs
        self.name = source.name
        self.slug = slugify(source.name)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        self.dir = self.working / f"{self.slug}_{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.blend = self.dir / source.name
        shutil.move(str(source), str(self.blend))
        self.frames = None
        self.opts = options_from_name(source.name)
        self.started = time.time()
        self.log_path = self.dir / "technical-log.txt"
        self.report = None

    # --- talking to the editor -------------------------------------------------
    def status(self, headline, detail=""):
        body = f"{self.name}\n\n{headline}\n"
        if detail:
            body += f"\n{detail}\n"
        body += (
            f"\nQuality: {self.opts['label']}"
            f"\nStarted: {dt.datetime.fromtimestamp(self.started):%H:%M on %d %b}"
            "\n\nNothing for you to do. The finished video appears here when it is ready."
            " If the file cannot be rendered you get a note saying what to change.\n"
        )
        (self.dir / "STATUS.txt").write_text(body)

    def log(self, line):
        with self.log_path.open("a") as fh:
            fh.write(f"{dt.datetime.now():%H:%M:%S} {line}\n")

    # --- the run ---------------------------------------------------------------
    def unpack_if_zip(self):
        if self.blend.suffix.lower() != ".zip":
            return
        with zipfile.ZipFile(self.blend) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".blend")
                     and not n.startswith("__MACOSX")]
            if not names:
                raise Rejected("That .zip has no .blend file inside it.")
            names.sort(key=lambda n: (n.count("/"), len(n)))
            zf.extractall(self.dir / "unpacked")
        self.blend = self.dir / "unpacked" / names[0]

    def frames_dir(self):
        """Keyed by what is actually being rendered, not by when it was dropped.

        Same file dropped again after a failure reuses its frames and carries on.
        An edited file hashes differently, so it never inherits stale frames.
        """
        digest = hashlib.sha1()
        with self.blend.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        key = f"{self.slug}-{digest.hexdigest()[:10]}-s{self.opts['scale']}-n{self.opts['samples']}"
        return Path(self.cfg["STATE_DIR"]) / "frames" / key

    def check(self):
        self.status("Checking the file.")
        self.unpack_if_zip()
        preflight.check_version(self.blend, self.cfg["BLENDER_VERSION"])
        report = preflight.gate(preflight.inspect(self.blend, self.cfg["BLENDER"]))
        self.report = report
        self.frames = self.frames_dir()
        self.frames.mkdir(parents=True, exist_ok=True)
        self.opts["fps"] = report["fps"]
        unpacked = self.dir / "unpacked"
        self.opts["root"] = str(unpacked) if unpacked.exists() else None
        (self.dir / "scene-report.json").write_text(json.dumps(report, indent=2))
        width, height = report["resolution"]
        if self.opts["scale"]:
            width, height = width * self.opts["scale"] // 100, height * self.opts["scale"] // 100
        self.status(
            "Queued for rendering.",
            f"{report['frames']} frames at {width} x {height}, {report['fps']} fps "
            f"({report['frames'] / max(report['fps'], 1):.1f} seconds of video).",
        )
        return report

    def render(self, provider):
        total = self.report["frames"]
        state = {"done": 0, "times": []}

        def on_line(line):
            self.log(line)
            match = re.match(r"RD_FRAME (\d+)/(\d+) \d+ (?:ok ([\d.]+)s|skipped)", line)
            if match:
                state["done"] = int(match.group(1))
                if match.group(3):
                    state["times"].append(float(match.group(3)))
                    del state["times"][:-20]
                left = ""
                if state["times"]:
                    per = sum(state["times"]) / len(state["times"])
                    left = f" {human_time(per * (total - state['done']))} left."
                self.status("Rendering now.", f"Frame {state['done']} of {total}.{left}")
            elif line.startswith("RD_DEVICE"):
                self.status("Rendering now.", f"Machine: {line[len('RD_DEVICE '):]}")

        self.status("Rendering now.", f"Frame 0 of {total}.")
        result = provider.render(self.blend, self.frames, self.opts, on_line)
        self.log(f"RD_RESULT {json.dumps(result)}")
        return result

    def deliver(self, result):
        self.status("Making the video file.")
        out_dir = self.finished / self.dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{self.slug}.mp4"

        if result.get("mp4"):
            # The GPU provider already encoded on the rented machine: bringing back
            # one mp4 instead of a PNG sequence is the difference between 50 MB and
            # several GB over the wire.
            shutil.copy2(result["mp4"], target)
            if result.get("preview") and Path(result["preview"]).exists():
                shutil.copy2(result["preview"], out_dir / "preview.png")
            rendered = int(result.get("frames_rendered") or 0)
        else:
            muxed = video.mux(self.frames, target, self.report["fps"],
                              self.cfg.get("FFMPEG", "ffmpeg"))
            rendered = muxed["frames"]
            numbers = video.frame_numbers(self.frames)
            preview = self.frames / f"frame_{numbers[len(numbers) // 2]:05d}.png"
            if preview.exists():
                shutil.copy2(preview, out_dir / "preview.png")

        total = self.report["frames"]
        seconds = result.get("seconds", 0)
        per_frame = seconds / rendered if rendered else 0
        ledger.append(self.cfg, {
            "when": dt.datetime.now().isoformat(timespec="seconds"),
            "job": self.name,
            "provider": result.get("provider", "?"),
            "gpu": result.get("gpu", ""),
            "frames": rendered,
            "seconds": round(seconds, 1),
            "seconds_per_frame": round(per_frame, 2),
            "usd_per_hour": result.get("usd_per_hour", 0),
            "cost_usd": round(result.get("cost_usd", 0), 4),
            "quality": self.opts["label"],
        })

        (out_dir / "READ-ME.txt").write_text(
            f"{self.name}\n\n"
            f"Done. {rendered} of {total} frames, "
            f"{rendered / max(self.report['fps'], 1):.1f} seconds of video.\n"
            f"Quality: {self.opts['label']}\n"
            f"Rendered on: {result.get('gpu') or result.get('device', 'unknown')}\n"
            f"Render time: {human_time(seconds)} ({per_frame:.1f} seconds per frame)\n"
            f"Cost: ${result.get('cost_usd', 0):.2f}\n\n"
            "The preview image is one frame from the middle, so you can check the look"
            " without opening the video.\n"
        )
        if self.log_path.exists():
            shutil.copy2(self.log_path, out_dir / "technical-log.txt")

        if rendered < total:
            (out_dir / "INCOMPLETE.txt").write_text(
                f"Only {rendered} of {total} frames rendered, so this video is short. Drop the "
                "same file again and it will carry on from the frames that are already done.\n"
            )
        else:
            shutil.rmtree(self.dir, ignore_errors=True)
            shutil.rmtree(self.frames, ignore_errors=True)
        return out_dir, {"frames": rendered}

    def reject(self, exc):
        out = self.problems / self.dir.name
        out.mkdir(parents=True, exist_ok=True)
        body = f"{self.name}\n\nThis file was not rendered.\n\n{exc.message}\n"
        if getattr(exc, "detail", ""):
            body += f"\n--- details for Nick ---\n{exc.detail}\n"
        (out / "WHAT-WENT-WRONG.txt").write_text(body)
        for item in self.dir.iterdir():
            if item.name != "STATUS.txt":
                shutil.move(str(item), str(out / item.name))
        shutil.rmtree(self.dir, ignore_errors=True)
        return out
