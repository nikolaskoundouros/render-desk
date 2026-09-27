#!/bin/sh
# The one command that proves render-desk works. Exit 0 = pass, anything else = fail.
# Written by Claude on 2026-09-27, for Nick to review. Agents may run it, never edit it.
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
"$ROOT/checks/end_to_end.sh"
"$ROOT/checks/runpod_contract.sh"
echo "verify.sh: PASS"
