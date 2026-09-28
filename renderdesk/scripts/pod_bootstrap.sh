#!/bin/bash
# Prepare a fresh pod for rendering. Everything expensive is cached on the network
# volume, so this is slow once and fast forever after.
set -euo pipefail
VERSION="${1:?blender version, e.g. 4.5.14}"
SERIES="${VERSION%.*}"
VOL=/workspace
BLENDER_DIR="$VOL/blender/$VERSION"

mkdir -p "$VOL/bin" "$VOL/jobs" "$VOL/frames"

# Blender runs headless but still links the X and GL client libraries. ffmpeg comes
# from the same apt call: Ubuntu's mirrors are a CDN and finish in seconds, where
# fetching a static build from a single host was taking 70 seconds of every job.
if ! dpkg -s libxi6 >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libgl1 \
    xz-utils curl ffmpeg >/dev/null
fi

if [ ! -x "$BLENDER_DIR/blender" ]; then
  echo "RD_SETUP downloading Blender $VERSION"
  mkdir -p "$BLENDER_DIR"
  URL="https://download.blender.org/release/Blender$SERIES/blender-$VERSION-linux-x64.tar.xz"
  curl -fsSL "$URL" -o /tmp/blender.tar.xz
  tar -xJf /tmp/blender.tar.xz -C "$BLENDER_DIR" --strip-components=1
  rm -f /tmp/blender.tar.xz
fi

# Prefer whatever apt just installed. The static build stays as a fallback for an
# image where apt has no ffmpeg, and lives on the volume so it is fetched once.
if command -v ffmpeg >/dev/null 2>&1; then
  ln -sf "$(command -v ffmpeg)" "$VOL/bin/ffmpeg"
elif [ ! -x "$VOL/bin/ffmpeg" ]; then
  echo "RD_SETUP apt had no ffmpeg, downloading a static build"
  curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o /tmp/ff.tar.xz
  mkdir -p /tmp/ff && tar -xJf /tmp/ff.tar.xz -C /tmp/ff --strip-components=1
  mv /tmp/ff/ffmpeg /tmp/ff/ffprobe "$VOL/bin/" && rm -rf /tmp/ff /tmp/ff.tar.xz
fi

"$BLENDER_DIR/blender" --version | head -1
# Free intelligence for later: if the Linux build can encode video itself, the
# external ffmpeg can be dropped entirely. The macOS builds cannot.
"$BLENDER_DIR/blender" -b --factory-startup -noaudio --python-expr "
import bpy
try:
    bpy.context.scene.render.image_settings.file_format = 'FFMPEG'
    print('RD_SETUP blender_can_encode: yes')
except TypeError:
    print('RD_SETUP blender_can_encode: no')
" 2>/dev/null | grep blender_can_encode || true
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo "RD_SETUP ready"
