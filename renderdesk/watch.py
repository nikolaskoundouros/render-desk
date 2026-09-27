"""The broker loop: watch the drop folder, run one job at a time, never leave a GPU up."""
import shutil
import time
import traceback
from pathlib import Path

import datetime as dt

from . import config, ledger, providers
from .job import Job, settled
from .preflight import Rejected

ACCEPTS = {".blend", ".zip"}
IGNORE_PREFIXES = (".", "~", "_")

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
        print(f"[done] {job.name} -> {out_dir} ({muxed['frames']} frames)")
        return out_dir
    except Rejected as exc:
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
    while True:
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
    rows.append(("blender", shutil.which(cfg["BLENDER"]) or "MISSING", cfg["BLENDER"]))
    rows.append(("ffmpeg", shutil.which(cfg.get("FFMPEG", "ffmpeg")) or "MISSING", ""))
    rows.append(("drop folder", "ok" if inbox.exists() else "MISSING", str(inbox)))
    rows.append(("provider", cfg["PROVIDER"], ""))
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
