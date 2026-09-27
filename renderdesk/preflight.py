"""Hard gates. A job that fails one of these never reaches a GPU.

Every message here is written for the editor, not for Nick: it says what to do
in Blender, not what went wrong in Python.
"""
import json
import subprocess
import tempfile
from pathlib import Path

from . import blendfile

SCRIPT = Path(__file__).parent / "scripts" / "preflight_blend.py"


class Rejected(Exception):
    def __init__(self, message, detail=""):
        super().__init__(message)
        self.message = message
        self.detail = detail


def check_version(blend, renderer_version):
    try:
        saved = blendfile.version(blend)
    except ValueError as exc:
        raise Rejected(
            "This does not look like a Blender file. Drop a .blend (or a .zip containing one).",
            str(exc),
        )
    want = blendfile.parse_version(renderer_version)
    if saved > want:
        raise Rejected(
            f"This file was saved in Blender {saved[0]}.{saved[1]} but the render machine runs "
            f"{want[0]}.{want[1]}. Ask Nick to point the render machine at Blender "
            f"{saved[0]}.{saved[1]} (one line of config), or save the file from Blender "
            f"{want[0]}.{want[1]} instead.",
            f"file={saved} renderer={want}",
        )
    return saved


def inspect(blend, blender_bin):
    """Ask Blender itself about the scene. Returns the report dict."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "preflight.json"
        proc = subprocess.run(
            [blender_bin, "-b", str(blend), "--factory-startup", "-noaudio",
             "--python", str(SCRIPT), "--", str(out)],
            capture_output=True, text=True, timeout=900,
        )
        if not out.exists():
            raise Rejected(
                "Blender could not open this file. It may be damaged, or still uploading when it "
                "was picked up. Try dropping it again.",
                (proc.stderr or proc.stdout)[-1500:],
            )
        return json.loads(out.read_text())


def gate(report):
    """Raise Rejected on anything that would waste a paid render."""
    if report["missing_files"]:
        shown = "\n".join(f"  - {p}" for p in report["missing_files"][:8])
        extra = len(report["missing_files"]) - 8
        more = f"\n  ...and {extra} more" if extra > 0 else ""
        raise Rejected(
            f"{len(report['missing_files'])} file(s) this scene needs are not inside the .blend, so "
            "the render would come out with missing textures. In Blender: File > External Data > "
            "Automatically Pack Resources, save, then drop it again.",
            shown + more,
        )
    if not report["camera"]:
        raise Rejected(
            "This scene has no camera, so there is no shot to render. Add a camera in Blender "
            "(and check it is the scene's active camera), save, then drop it again."
        )
    if report["frames"] < 1:
        raise Rejected(
            "The frame range is empty (start frame is after end frame), so there is nothing to "
            "render. Fix the start and end frames in Blender's Output panel and drop it again."
        )
    if report["objects"] < 1:
        raise Rejected("This scene is empty: there are no objects to render.")
    return report
