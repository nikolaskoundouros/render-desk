#!/bin/sh
# The GPU provider cannot be proven without spending money, so this proves everything
# that does not need a GPU: the v2 request shape, the GPU fallback, the price cap, and
# that a pod is always destroyed.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
python3 "$ROOT/checks/runpod_contract.py"
