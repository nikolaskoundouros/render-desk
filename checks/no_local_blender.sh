#!/bin/sh
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
python3 "$ROOT/checks/no_local_blender.py"
