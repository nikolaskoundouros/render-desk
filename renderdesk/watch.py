"""The broker loop: watch the drop folder, run one job at a time, never leave a GPU up."""
import json
import shutil
import time
import traceback
from pathlib import Path

import datetime as dt

from . import config, drive, ledger, providers
from .job import Job, settled
from .preflight import Busy, Rejected

# How long a job keeps waiting for a free GPU before the editor is told to try later.
PATIENCE_HOURS = 3

ACCEPTS = {".blend", ".zip"}
IGNORE_PREFIXES = (".", "~")

EDITOR_NOTE = """HOW TO RENDER A CLIP

1. Put your .blend file in this folder (1-drop-here).
   If the scene uses textures or linked files, first do this in Blender:
   File > External Data > Automatically Pack Resources, then save.
   Or just zip the whole project folder and drop the .zip.

2. That is it. Within a minute the file moves to 2-working and a STATUS.txt
   appears there telling you what is happening and how long is left.

3. The finished video lands in 3-finished, as an mp4 next to a preview frame.

4. If something is wrong with the file (missing textures, no camera) it moves to
   4-needs-a-fix with a note explaining what to change. Nothing is charged for
   those, so drop as many as you like.

Want a quick look test instead of the full render? Put _draft in the filename,
for example shot_07_draft.blend. That renders at half size and low samples, so it
comes back in minutes and costs very little. Drop it again without _draft when
the look is right.

Do not rename or move anything in 2-working while it is rendering.
"""


def candidates(inbox):
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.name.startswith(IGNORE_PREFIXES):
            continue
        if path.suffix.lower() in ACCEPTS:
            yield path


def ensure_folders(cfg):
    inbox, working, finished = config.paths(cfg)
    problems = finished.parent / "4-needs-a-fix"
    for folder in (inbox, working, finished, problems):
        folder.mkdir(parents=True, exist_ok=True)
    note = inbox / "READ-ME-FIRST.txt"
    if not note.exists() or note.read_text() != EDITOR_NOTE:
        note.write_text(EDITOR_NOTE)
    return inbox, working, finished, problems


def budget_left(cfg):
    """(daily, monthly) dollars still available. Local rendering is free, so this
    only ever restrains the provider that spends money."""
    now = dt.datetime.now()
    day = ledger.spent_since(cfg, now.replace(hour=0, minute=0, second=0, microsecond=0))
    month = ledger.spent_since(cfg, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    return (float(cfg["DAILY_SPEND_CAP_USD"]) - day,
            float(cfg["MONTHLY_SPEND_CAP_USD"]) - month)


def waiting_since(cfg, name, reset=False):
    """When this file first failed to find a GPU, so patience can run out."""
    path = Path(cfg["STATE_DIR"]) / "waiting.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        book = json.loads(path.read_text())
    except (OSError, ValueError):
        book = {}
    if reset:
        book.pop(name, None)
    elif name not in book:
        book[name] = time.time()
    path.write_text(json.dumps(book))
    return book.get(name, time.time())


def run_one(source, cfg, dirs, provider):
    job = Job(source, cfg, dirs)
    try:
        if provider.name != "local":
            day_left, month_left = budget_left(cfg)
            if day_left <= 0 or month_left <= 0:
                which = "today's" if day_left <= 0 else "this month's"
                raise Rejected(
                    f"This was not rendered because {which} render budget is used up. Nothing has "
                    "been charged. Ask Nick to raise the limit, then drop the file again.",
                    f"daily left ${day_left:.2f}, monthly left ${month_left:.2f}",
                )
        job.check()
        result = job.render(provider)
        out_dir, muxed = job.deliver(result)
        waiting_since(cfg, job.name, reset=True)
        print(f"[done] {job.name} -> {out_dir} ({muxed['frames']} frames)")
        return out_dir
    except Busy as exc:
        # No machine was free. That is RunPod's weather, not a problem with the file,
        # so the job goes back in the queue and keeps its place.
        first = waiting_since(cfg, job.name)
        hours = (time.time() - first) / 3600
        job.log(f"BUSY {exc}")
        if hours < PATIENCE_HOURS:
            job.requeue(
                "Waiting for a free render machine.",
                f"All the graphics cards are busy right now. This keeps trying by itself"
                f" and starts the moment one frees up. Waiting {int(hours * 60)} minutes"
                f" so far. Nothing is wrong with your file and nothing has been charged.")
            print(f"[waiting] {job.name}: no GPU free, {int(hours * 60)} min so far")
            return None
        waiting_since(cfg, job.name, reset=True)
        out = job.reject(Rejected(
            f"No render machine came free in {PATIENCE_HOURS} hours, so this was put"
            " aside. Nothing is wrong with your file and nothing has been charged."
            " Upload it again later and it will render.", str(exc)))
        print(f"[gave up] {job.name}: no GPU for {PATIENCE_HOURS}h")
        return out
    except Rejected as exc:
        waiting_since(cfg, job.name, reset=True)
        out = job.reject(exc)
        print(f"[needs a fix] {job.name}: {exc.message}")
        return out
    except Exception as exc:  # a crash is still an answer the editor can read
        detail = traceback.format_exc()
        job.log(detail)
        out = job.reject(Rejected(
            "The render machine hit a problem with this file, so nothing was produced. Nick has "
            "the technical log. Dropping the file again is safe: any frames already finished are "
            "reused.",
            f"{exc}\n\n{detail[-2000:]}",
        ))
        print(f"[failed] {job.name}: {exc}")
        return out


def loop(cfg, once=False):
    dirs = ensure_folders(cfg)
    inbox = dirs[0]
    provider = providers.get(cfg["PROVIDER"], cfg)
    print(f"render-desk watching {inbox}  provider={provider.name}")
    if drive.configured(cfg):
        print(f"also pulling from Google Drive: {cfg['DRIVE_REMOTE']}")
    last_drive = 0.0
    while True:
        # Files can arrive two ways: uploaded on the page, or dropped in the shared
        # Drive folder. Drive is there because the editor's route to this box is slow
        # while his route to Google is not.
        if drive.configured(cfg) and time.time() - last_drive >= int(cfg["DRIVE_POLL_SECONDS"]):
            last_drive = time.time()
            try:
                drive.fetch_new(cfg)
            except Exception as exc:
                print(f"[drive] could not check the folder: {exc}")
        for source in candidates(inbox):
            if not settled(source):
                print(f"[wait] {source.name} is still uploading")
                continue
            run_one(source, cfg, dirs, provider)
        if once:
            return
        time.sleep(int(cfg["POLL_SECONDS"]))


def doctor(cfg):
    inbox, working, finished, problems = ensure_folders(cfg)
    rows = []
    local = cfg["PROVIDER"] == "local"
    blender = shutil.which(cfg["BLENDER"])
    rows.append(("blender", (blender or "MISSING") if local
                 else (blender or "not needed here, the GPU inspects the scene"),
                 cfg["BLENDER"]))
    if cfg["PROVIDER"] == "local":
        rows.append(("ffmpeg", shutil.which(cfg.get("FFMPEG", "ffmpeg")) or "MISSING", ""))
    rows.append(("drop folder", "ok" if inbox.exists() else "MISSING", str(inbox)))
    rows.append(("provider", cfg["PROVIDER"], ""))
    if cfg.get("DRIVE_REMOTE"):
        try:
            found = len(drive.listing(cfg))
            rows.append(("google drive", f"ok, {found} scene file(s) waiting", cfg["DRIVE_REMOTE"]))
        except Exception as exc:
            rows.append(("google drive", "MISSING", str(exc)[:80]))
    else:
        rows.append(("google drive", "not set up", "optional"))
    day_left, month_left = budget_left(cfg)
    rows.append(("budget left", f"${day_left:.2f} today, ${month_left:.2f} this month", ""))
    if cfg["PROVIDER"] == "runpod":
        rows.append(("runpod key", "set" if cfg["RUNPOD_API_KEY"] else "MISSING", ""))
        rows.append(("network volume", cfg["RUNPOD_VOLUME_ID"] or "MISSING", ""))
        key = Path(cfg["RUNPOD_SSH_KEY"]).expanduser()
        rows.append(("ssh key", "ok" if key.exists() else "MISSING", str(key)))
    width = max(len(r[0]) for r in rows)
    ok = True
    for name, value, extra in rows:
        if value == "MISSING":
            ok = False
        print(f"  {name.ljust(width)}  {value}  {extra}")
    return 0 if ok else 1
