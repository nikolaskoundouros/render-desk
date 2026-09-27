"""What every clip actually cost. This is the answer the desk exists to produce."""
import csv
import datetime as dt
from pathlib import Path

COLUMNS = ["when", "job", "provider", "gpu", "data_centre", "frames",
           "seconds", "render_seconds", "seconds_per_frame", "usd_per_hour",
           "cost_usd", "quality"]


def path(cfg):
    return Path(cfg["STATE_DIR"]) / "ledger.tsv"


def append(cfg, row):
    target = path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    new = not target.exists()
    with target.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, COLUMNS, delimiter="\t", extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerow(row)


def rows(cfg):
    target = path(cfg)
    if not target.exists():
        return []
    with target.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def spent_since(cfg, since):
    total = 0.0
    for row in rows(cfg):
        try:
            when = dt.datetime.fromisoformat(row["when"])
        except (ValueError, KeyError):
            continue
        if when >= since:
            total += float(row.get("cost_usd") or 0)
    return total


def summary(cfg, clips=25, seconds_each=35, fps=30):
    """Project a monthly bill from what has actually been measured.

    Renting a machine, booting it and fetching Blender costs the same whether the
    job is 3 frames or 900. Charging that to every frame makes a short test look
    thirty times slower than a real clip, so it is counted once per clip here.
    """
    data = [r for r in rows(cfg) if float(r.get("frames") or 0) > 0
            and r.get("provider") != "local"]
    if not data:
        return None

    frames = sum(float(r["frames"]) for r in data)
    total = sum(float(r["seconds"]) for r in data)
    rendering = sum(float(r.get("render_seconds") or r["seconds"]) for r in data)
    cost = sum(float(r["cost_usd"]) for r in data)
    rate = (cost / total * 3600) if total else 0

    per_frame = rendering / frames
    overhead = max(0.0, (total - rendering) / len(data))
    planned_frames = seconds_each * fps
    per_clip = overhead + planned_frames * per_frame

    return {
        "jobs": len(data),
        "frames": int(frames),
        "seconds_per_frame": round(per_frame, 2),
        "overhead_seconds": round(overhead, 1),
        "usd_per_hour": round(rate, 3),
        "usd_so_far": round(cost, 2),
        "usd_per_clip": round(per_clip * rate / 3600, 2),
        "planned_frames": int(planned_frames * clips),
        "projected_usd": round(clips * per_clip * rate / 3600, 2),
        "plan": f"{clips} clips x {seconds_each}s at {fps}fps",
        "thin": frames < 60,
    }
