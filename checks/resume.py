"""Render the same scene twice into one folder: the second pass must skip every
frame it already has, and finish faster. This is what makes a failed GPU job
cheap to retry."""
import subprocess
import sys
import time
from pathlib import Path

root, tmp = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, root)
from renderdesk import config, providers  # noqa: E402

cfg = config.load()
blend = tmp / "resume.blend"
subprocess.run([cfg["BLENDER"], "-b", "--factory-startup", "-noaudio",
                "--python", f"{root}/checks/make_test_blend.py", "--", str(blend)],
               capture_output=True, check=True)

provider = providers.get("local", cfg)
frames = tmp / "resume-frames"
first_lines, second_lines = [], []
start = time.time(); provider.render(blend, frames, {}, first_lines.append)
first = time.time() - start
start = time.time(); provider.render(blend, frames, {}, second_lines.append)
second = time.time() - start

rendered = [l for l in first_lines if " ok " in l]
skipped = [l for l in second_lines if l.endswith("skipped")]
print(f"   first run {first:.1f}s rendered {len(rendered)}, "
      f"second run {second:.1f}s skipped {len(skipped)}", file=sys.stderr)
sys.exit(0 if len(rendered) == 3 and len(skipped) == 3 and second < first else 1)
