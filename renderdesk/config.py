"""Config for render-desk. Secrets live in ~/.config/render-desk/render.env, never in the repo."""
import os
import shlex
from pathlib import Path

ENV_PATH = Path.home() / ".config" / "render-desk" / "render.env"

DRIVE = Path.home() / "Library" / "CloudStorage" / "GoogleDrive-nikolaskoundouros@gmail.com" / "My Drive"
DESK = DRIVE / "Nick-AE" / "render"

DEFAULTS = {
    "PROVIDER": "local",
    "INBOX": str(DESK / "1-drop-here"),
    "WORKING": str(DESK / "2-working"),
    "FINISHED": str(DESK / "3-finished"),
    "STATE_DIR": str(Path.home() / ".local" / "share" / "render-desk"),
    "BLENDER": "/opt/homebrew/bin/blender",
    "BLENDER_VERSION": "5.1.2",
    "BLENDER_DOWNLOAD": "",
    "POLL_SECONDS": "30",
    "MAX_JOB_MINUTES": "120",
    "DAILY_SPEND_CAP_USD": "20",
    "MONTHLY_SPEND_CAP_USD": "40",
    "RUNPOD_API_KEY": "",
    "RUNPOD_VOLUME_ID": "",
    "RUNPOD_SSH_KEY": str(Path.home() / ".ssh" / "id_ed25519"),
    "RUNPOD_IMAGE": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
    "GPU_PREFERENCE": "NVIDIA GeForce RTX 4090,NVIDIA A40,NVIDIA L40S",
    "GPU_MAX_USD_PER_HOUR": "1.20",
}


def _parse(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ("'", '"'):
            value = next(iter(shlex.split(value)), "")
        out[key.strip()] = value
    return out


def load():
    cfg = dict(DEFAULTS)
    if ENV_PATH.exists():
        cfg.update(_parse(ENV_PATH.read_text()))
    for key in cfg:
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    for key in ("INBOX", "WORKING", "FINISHED", "STATE_DIR"):
        cfg[key] = str(Path(cfg[key]).expanduser())
    return cfg


def paths(cfg):
    return Path(cfg["INBOX"]), Path(cfg["WORKING"]), Path(cfg["FINISHED"])
