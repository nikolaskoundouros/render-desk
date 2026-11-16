"""Two things every live job goes through (Nick, 2026-10-08: "i just want real time monitoring while you work in blender";
one note took an hour because the same 5-minute test ran 10 times, one setting changed each round).

attempts: a job must say which problem it works on (LIVE_ISSUE). At most MAX_TRIES jobs per problem until Nick is told about
it: a `tg text` that names the problem resets the count (tg logs every send to STATE_DIR/tg-sent.log).
stills: every image a job brings back in its pulled folders goes to Nick's Telegram as one sheet, by itself.
"""
import json, os, subprocess, tempfile, time
from pathlib import Path

MAX_TRIES = 3
TG = "/usr/local/bin/tg"
IMG = (".png", ".jpg", ".jpeg", ".webp")


def _issues_path(cfg):
    return Path(cfg["STATE_DIR"]) / "live-issues.json"


def _last_told(cfg, issue):
    """When Nick last got a text naming this problem (0 if never)."""
    log = Path(cfg["STATE_DIR"]) / "tg-sent.log"
    last = 0.0
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[1] == "text" and issue.lower() in parts[2].lower():
                try:
                    last = max(last, float(parts[0]))
                except ValueError:
                    pass
    return last


def check_attempt(cfg, jobs, issue):
    """None if this job may run (and it is counted), else the reason it may not."""
    if not issue or not issue.strip():
        return ("set LIVE_ISSUE to a short name for the problem this job works on (for example LIVE_ISSUE=acid-outside); "
                "at most %d jobs per problem before Nick is told about it" % MAX_TRIES)
    issue = issue.strip(); key = f"{jobs}::{issue}"; p = _issues_path(cfg)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        data = {}
    told = _last_told(cfg, issue)
    runs = [t for t in data.get(key, []) if t > told]
    if len(runs) >= MAX_TRIES:
        return (f"{len(runs)} jobs on '{issue}' since Nick last heard about it. Stop: send him a still and what is blocking, "
                f"with a text that names the problem: tg text \"... {issue}: ...\". Then the next job may run. Each try must "
                f"name a different cause, never a new value of the same setting.")
    runs.append(time.time()); data[key] = runs
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=1)); os.replace(tmp, p)
    return None


def snapshot(dirs):
    """Images already in the folders a job will pull, with their sizes and times, so only new ones are sent."""
    seen = {}
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(IMG):
                    q = os.path.join(root, f)
                    try:
                        s = os.stat(q); seen[q] = (s.st_size, s.st_mtime)
                    except OSError:
                        pass
    return seen


def label(jobs):
    j = jobs.lower()
    return "Acid reflux" if "acid-reflux" in j else "Robbery" if "bank-money" in j else os.path.basename(jobs.rstrip("/"))


def send_new(jobs, job_name, issue, before, dirs, log=print):
    """Send the images that are new or changed since `before` as one sheet (up to 12) to Nick's Telegram."""
    if not os.path.exists(TG):
        return
    now = snapshot(dirs)
    new = sorted(q for q, v in now.items() if before.get(q) != v)
    if not new:
        return
    cap = f"{label(jobs)} live, unchecked: {job_name} ({issue}), {len(new)} new still{'s' if len(new) != 1 else ''}"
    sheet = new[0]
    if len(new) > 1:
        try:
            from PIL import Image
            ims = [Image.open(q).convert("RGB") for q in new[:12]]
            w = 360; cells = [im.resize((w, max(1, int(im.height * w / im.width)))) for im in ims]
            cols = min(4, len(cells)); h = max(c.height for c in cells); rows = (len(cells) + cols - 1) // cols
            out = Image.new("RGB", (cols * w, rows * h), (20, 20, 20))
            for k, c in enumerate(cells):
                out.paste(c, ((k % cols) * w, (k // cols) * h))
            sheet = os.path.join(tempfile.gettempdir(), f"live_sheet_{os.getpid()}.jpg"); out.save(sheet, quality=85)
        except Exception as exc:                              # a sheet is a nicety; the first still still goes
            log(f"LIVE sheet failed ({exc}), sending the first still only")
    try:
        subprocess.run([TG, "photo", sheet, cap], capture_output=True, timeout=90)
        log(f"LIVE sent {min(len(new), 12)} still(s) to Nick's Telegram")
    except Exception as exc:
        log(f"LIVE could not send stills: {exc}")
    finally:
        if sheet != new[0]:
            try:
                os.remove(sheet)
            except OSError:
                pass
