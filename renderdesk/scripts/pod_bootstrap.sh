#!/bin/bash
# Prepare a fresh pod for rendering. Everything expensive is cached on the network
# volume, so this is slow once and fast forever after.
set -euo pipefail
VERSION="${1:?blender version, e.g. 4.5.14}"
SERIES="${VERSION%.*}"
VOL=/workspace
BLENDER_DIR="$VOL/blender/$VERSION"

mkdir -p "$VOL/bin" "$VOL/jobs" "$VOL/frames"

# Blender runs headless but still links the X and GL client libraries.
if ! dpkg -s libxi6 >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libgl1 xz-utils curl >/dev/null
fi

if [ ! -x "$BLENDER_DIR/blender" ]; then
  echo "RD_SETUP downloading Blender $VERSION"
  mkdir -p "$BLENDER_DIR"
  URL="https://download.blender.org/release/Blender$SERIES/blender-$VERSION-linux-x64.tar.xz"
  curl -fsSL "$URL" -o /tmp/blender.tar.xz
  tar -xJf /tmp/blender.tar.xz -C "$BLENDER_DIR" --strip-components=1
  rm -f /tmp/blender.tar.xz
fi

if [ ! -x "$VOL/bin/ffmpeg" ]; then
  echo "RD_SETUP downloading ffmpeg"
  curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o /tmp/ff.tar.xz
  mkdir -p /tmp/ff && tar -xJf /tmp/ff.tar.xz -C /tmp/ff --strip-components=1
  mv /tmp/ff/ffmpeg /tmp/ff/ffprobe "$VOL/bin/" && rm -rf /tmp/ff /tmp/ff.tar.xz
fi

"$BLENDER_DIR/blender" --version | head -1
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo "RD_SETUP ready"
