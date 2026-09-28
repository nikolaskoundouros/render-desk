"""Pull new scene files out of a shared Google Drive folder.

Why this exists: the editor's line is 30 Mbps but he reaches 0.7 to Helsinki, so
the long route is the bottleneck rather than his connection. Google has edge
servers near him, so uploading to Drive should run at his real speed, and the box
pulls from Google over a fast link instead.

Everything here is read-only against Drive. Nothing is deleted or written there.
"""
import json
import subprocess
import time
from pathlib import Path

from . import watch

RCLONE = "rclone"


def configured(cfg):
    return bool(cfg.get("DRIVE_REMOTE"))


def _run(args, timeout=None):
    proc = subprocess.run([RCLONE] + args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"rclone {' '.join(args[:2])}: {proc.stderr.strip()[:400]}")
    return proc.stdout


def listing(cfg):
    """Scene files sitting in the watched folder, newest first."""
    out = _run(["lsjson", cfg["DRIVE_REMOTE"], "--files-only"], timeout=120)
    files = []
    for item in json.loads(out or "[]"):
        name = item.get("Name", "")
        if Path(name).suffix.lower() in watch.ACCEPTS:
            files.append({"name": name, "size": item.get("Size", 0),
                          "id": item.get("ID", name), "modified": item.get("ModTime", "")})
    files.sort(key=lambda f: f["modified"])
    return files


def seen_path(cfg):
    return Path(cfg["STATE_DIR"]) / "drive-seen.json"


def seen(cfg):
    try:
        return set(json.loads(seen_path(cfg).read_text()))
    except (OSError, ValueError):
        return set()


def remember(cfg, key):
    path = seen_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    marks = seen(cfg)
    marks.add(key)
    path.write_text(json.dumps(sorted(marks)))


def fetch_new(cfg, log=print):
    """Download anything new into the drop folder. Returns what it fetched.

    A file is identified by id and size together, so re-uploading a changed file
    under the same name is treated as new work, while the same file sitting there
    is never fetched twice.
    """
    inbox = Path(cfg["INBOX"])
    inbox.mkdir(parents=True, exist_ok=True)
    known = seen(cfg)
    fetched = []
    for item in listing(cfg):
        key = f"{item['id']}:{item['size']}"
        if key in known:
            continue
        # Land it under a dot name so the watcher cannot pick up a partial download.
        staging = inbox / f".drive-{item['name']}"
        started = time.time()
        log(f"RD_DRIVE fetching {item['name']} ({item['size'] / 1048576:.0f} MB)")
        _run(["copyto", f"{cfg['DRIVE_REMOTE']}/{item['name']}", str(staging),
              "--transfers", "8", "--drive-chunk-size", "64M", "--retries", "3"],
             timeout=7200)
        took = max(time.time() - started, 0.1)
        final = inbox / item["name"]
        count = 2
        while final.exists():
            final = inbox / f"{Path(item['name']).stem}-{count}{Path(item['name']).suffix}"
            count += 1
        staging.replace(final)
        remember(cfg, key)
        fetched.append(final)
        log(f"RD_DRIVE got {final.name} in {took:.0f}s "
            f"({item['size'] / 1048576 / took:.1f} MB/s from Google)")
    return fetched
