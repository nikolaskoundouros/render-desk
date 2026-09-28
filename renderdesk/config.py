"""Config for render-desk. Secrets live in ~/.config/render-desk/render.env, never in the repo."""
import os
import shlex
from pathlib import Path

# On a Mac the config is the user's. On the box it is the service's, in /etc.
ENV_CANDIDATES = (
    Path.home() / ".config" / "render-desk" / "render.env",
    Path("/etc/render-desk/render.env"),
)
ENV_PATH = next((p for p in ENV_CANDIDATES if p.exists()), ENV_CANDIDATES[0])

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
    "DRIVE_REMOTE": "",
    "DRIVE_POLL_SECONDS": "60",
    "WEB_PORT": "8630",
    "WEB_HOST": "127.0.0.1",
    "EDITOR_PASSWORD": "",
    "MAX_UPLOAD_MB": "4096",
    "MAX_JOB_MINUTES": "120",
    "DAILY_SPEND_CAP_USD": "20",
    "MONTHLY_SPEND_CAP_USD": "40",
    "RUNPOD_API_KEY": "",
    "RUNPOD_VOLUME_ID": "",
    "RUNPOD_DATA_CENTER": "",
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
    for path in ENV_CANDIDATES:
        if path.exists():
            try:
                cfg.update(_parse(path.read_text()))
            except PermissionError:
                pass
            break
    for key in cfg:
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    for key in ("INBOX", "WORKING", "FINISHED", "STATE_DIR"):
        cfg[key] = str(Path(cfg[key]).expanduser())
    return cfg


def paths(cfg):
    return Path(cfg["INBOX"]), Path(cfg["WORKING"]), Path(cfg["FINISHED"])
