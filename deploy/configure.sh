#!/bin/sh
# Copy the secrets from this Mac's config onto the box, once. Values travel over the
# SSH connection on stdin, never as command arguments, so they stay out of the box's
# process list. Re-running replaces the file, so run it again after rotating the key.
set -e
BOX="${RENDER_DESK_BOX:-root@46.62.230.121}"
SRC="$HOME/.config/render-desk/render.env"
test -f "$SRC" || { echo "no $SRC on this Mac" >&2; exit 1; }

python3 - "$SRC" <<'PY' | ssh "$BOX" 'mkdir -p /etc/render-desk && cat > /etc/render-desk/render.env && chmod 600 /etc/render-desk/render.env && echo "wrote /etc/render-desk/render.env"'
import sys, shlex
src = {}
for line in open(sys.argv[1]):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        v = v.strip()
        if v[:1] in ("'", '"'):
            v = next(iter(shlex.split(v)), "")
        src[k.strip()] = v

for needed in ("RUNPOD_API_KEY", "RUNPOD_VOLUME_ID", "EDITOR_PASSWORD"):
    if not src.get(needed):
        sys.exit(f"{needed} is not set in the Mac config")

box = {
    "PROVIDER": "runpod",
    "INBOX": "/var/lib/render-desk/1-drop-here",
    "WORKING": "/var/lib/render-desk/2-working",
    "FINISHED": "/var/lib/render-desk/3-finished",
    "STATE_DIR": "/var/lib/render-desk/state",
    "RUNPOD_SSH_KEY": "/etc/render-desk/pod_key",
    "WEB_HOST": "127.0.0.1",
    "WEB_PORT": "8630",
    "BLENDER": "/nonexistent/blender",   # the GPU inspects scenes, not this box
}
for key in ("RUNPOD_API_KEY", "RUNPOD_VOLUME_ID", "RUNPOD_DATA_CENTER", "EDITOR_PASSWORD",
            "BLENDER_VERSION", "GPU_PREFERENCE", "GPU_MAX_USD_PER_HOUR",
            "DAILY_SPEND_CAP_USD", "MONTHLY_SPEND_CAP_USD", "MAX_UPLOAD_MB", "POLL_SECONDS"):
    if src.get(key):
        box[key] = src[key]

out = ["# Written by deploy/configure.sh. Secrets: keep at chmod 600."]
for key, value in box.items():
    out.append(f'{key}="{value}"' if " " in value or "," in value else f"{key}={value}")
print("\n".join(out))
PY
