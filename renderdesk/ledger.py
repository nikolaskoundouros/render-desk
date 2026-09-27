"""What every clip actually cost. This is the answer the desk exists to produce."""
import csv
import datetime as dt
from pathlib import Path

COLUMNS = ["when", "job", "provider", "gpu", "frames", "seconds",
           "seconds_per_frame", "usd_per_hour", "cost_usd", "quality"]


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
    """Project a monthly bill from what has actually been measured so far."""
    data = [r for r in rows(cfg) if float(r.get("frames") or 0) > 0
            and r.get("provider") != "local"]
    if not data:
        return None
    frames = sum(float(r["frames"]) for r in data)
    seconds = sum(float(r["seconds"]) for r in data)
    cost = sum(float(r["cost_usd"]) for r in data)
    per_frame = seconds / frames
    per_frame_usd = cost / frames
    planned = clips * seconds_each * fps
    return {
        "jobs": len(data),
        "frames": int(frames),
        "seconds_per_frame": round(per_frame, 2),
        "usd_per_frame": round(per_frame_usd, 5),
        "usd_so_far": round(cost, 2),
        "planned_frames": int(planned),
        "projected_usd": round(per_frame_usd * planned, 2),
        "plan": f"{clips} clips x {seconds_each}s at {fps}fps",
    }
