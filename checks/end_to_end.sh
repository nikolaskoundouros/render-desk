#!/bin/sh
# Proves the whole desk on this Mac: a dropped file becomes a real mp4, a file with
# missing textures is refused before any render, and a file from a newer Blender is
# refused before Blender is even started.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BLENDER=${BLENDER:-/opt/homebrew/bin/blender}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export INBOX="$TMP/1-drop-here" WORKING="$TMP/2-working" FINISHED="$TMP/3-finished"
export STATE_DIR="$TMP/state" PROVIDER=local POLL_SECONDS=1
mkdir -p "$INBOX"

fail() { echo "FAIL: $1" >&2; exit 1; }

# --- 1. a good file renders end to end -------------------------------------
"$BLENDER" -b --factory-startup -noaudio --python "$ROOT/checks/make_test_blend.py" \
  -- "$INBOX/good_draft.blend" >"$TMP/mk.log" 2>&1 || { cat "$TMP/mk.log"; fail "could not build the test scene"; }
python3 "$ROOT/bin/renderdesk" once >"$TMP/run1.log" 2>&1 || { cat "$TMP/run1.log"; fail "the run crashed"; }

MP4=$(find "$FINISHED" -name '*.mp4' | head -1)
[ -n "$MP4" ] || { cat "$TMP/run1.log"; fail "no mp4 was produced"; }
FRAMES=$(ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=nb_read_frames -of csv=p=0 "$MP4" | tr -d '\r')
[ "$FRAMES" = "3" ] || fail "mp4 has $FRAMES frames, expected 3"
[ -s "$(dirname "$MP4")/preview.png" ] || fail "no preview frame was saved"
grep -q "Done\." "$(dirname "$MP4")/READ-ME.txt" || fail "no plain-English summary for the editor"
[ -z "$(ls -A "$WORKING")" ] || fail "the working folder was left dirty after success"

# --- 2. missing textures are refused, with instructions --------------------
"$BLENDER" -b --factory-startup -noaudio --python "$ROOT/checks/make_test_blend.py" \
  -- "$INBOX/unpacked.blend" --broken >>"$TMP/mk.log" 2>&1 || fail "could not build the broken scene"
python3 "$ROOT/bin/renderdesk" once >"$TMP/run2.log" 2>&1 || { cat "$TMP/run2.log"; fail "run 2 crashed"; }
NOTE=$(find "$TMP/4-needs-a-fix" -name 'WHAT-WENT-WRONG.txt' | head -1)
[ -n "$NOTE" ] || { cat "$TMP/run2.log"; fail "a file with missing textures was not refused"; }
grep -q "Automatically Pack Resources" "$NOTE" || fail "the refusal does not tell the editor how to fix it"
[ -z "$(find "$TMP/3-finished" -name 'unpacked*')" ] || fail "the broken file still produced output"

# --- 3. no camera is refused ----------------------------------------------
"$BLENDER" -b --factory-startup -noaudio --python "$ROOT/checks/make_test_blend.py" \
  -- "$INBOX/nocam.blend" --no-camera >>"$TMP/mk.log" 2>&1 || fail "could not build the camera-less scene"
python3 "$ROOT/bin/renderdesk" once >"$TMP/run3.log" 2>&1 || { cat "$TMP/run3.log"; fail "run 3 crashed"; }
grep -rqi "no camera" "$TMP/4-needs-a-fix"/nocam*/WHAT-WENT-WRONG.txt || fail "a scene with no camera was not refused"

# --- 4. a file from a newer Blender is refused before Blender starts -------
python3 - "$INBOX/future.blend" <<'PY'
import sys
# Hand-built header claiming Blender 9.9, in the 5.x header layout.
open(sys.argv[1], "wb").write(b"BLENDER17-01v0990REND" + b"\0" * 64)
PY
python3 "$ROOT/bin/renderdesk" once >"$TMP/run4.log" 2>&1 || { cat "$TMP/run4.log"; fail "run 4 crashed"; }
grep -rq "Blender 9.9" "$TMP/4-needs-a-fix"/future*/WHAT-WENT-WRONG.txt \
  || fail "a file from a newer Blender was not refused by the version gate"

# --- 5. zip in, mp4 out ---------------------------------------------------
mkdir -p "$TMP/proj" && "$BLENDER" -b --factory-startup -noaudio \
  --python "$ROOT/checks/make_test_blend.py" -- "$TMP/proj/inside_draft.blend" >>"$TMP/mk.log" 2>&1
(cd "$TMP/proj" && zip -q "$INBOX/project.zip" inside_draft.blend)
python3 "$ROOT/bin/renderdesk" once >"$TMP/run5.log" 2>&1 || { cat "$TMP/run5.log"; fail "run 5 crashed"; }
[ -n "$(find "$FINISHED" -path '*project*' -name '*.mp4' | head -1)" ] \
  || { cat "$TMP/run5.log"; fail "a dropped .zip did not produce an mp4"; }

# --- 6. the render is not a black frame -----------------------------------
PREVIEW=$(find "$FINISHED" -name 'preview.png' | head -1)
RANGE=$(ffprobe -v error -f lavfi -i "movie=$PREVIEW,signalstats" \
  -show_entries frame_tags=lavfi.signalstats.YMIN,lavfi.signalstats.YMAX -of csv=p=0 | tr -d '\r')
python3 "$ROOT/checks/not_blank.py" "$RANGE" || fail "the rendered frame is blank: min/max luma $RANGE"

# --- 7. a second run reuses finished frames instead of paying twice --------
python3 "$ROOT/checks/resume.py" "$ROOT" "$TMP" || fail "frames are not reused on a second run"

echo "end_to_end: 7 checks passed (render, missing textures, no camera, version gate, zip, not-blank, resume)"
