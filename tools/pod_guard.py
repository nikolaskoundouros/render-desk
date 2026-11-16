#!/usr/bin/env python3
"""pod_guard: terminate any workbench pod that has been idle for 10 minutes.

Nick, 15 Nov 2026: "after 10 idle minutes please shut the pod down". The Mac watchdog in renderdesk/workbench.py
could not do it: a live Blender inside `workbench run` kept the pod marked in use, and the Mac slept. This runs on
the always-on 3D System box (root@37.27.148.115) from a systemd timer, once a minute, and needs neither the Mac nor
the chat that started the pod.

Each minute, for every pod on the RunPod account named workbench-*:
  - ssh in and read: the age of ~/.wb_last_use (written by every workbench run/push/pull and by every live Blender
    connector command), the GPU use, and the container's CPU use over 5 seconds;
  - busy now (GPU >= 10 % or CPU >= half a core): keep;
  - otherwise idle for IDLE_MINUTES (10): terminate;
  - older than MAX_HOURS (5, Nick 7 Oct "i want the gpu for 5 hours max"): terminate even if busy;
  - unreachable by ssh for UNREACHABLE_MINUTES (15): terminate, since nobody can be using it either.

Off switch: POD_GUARD=0 in /etc/pod-guard.env (or the environment). Off means it reads nothing and stops nothing.
  pod_guard.py            one pass (what the timer runs)
  pod_guard.py --dry-run  one pass, decisions logged, nothing terminated
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from renderdesk import config, runpod_api  # noqa: E402

PREFIX = "workbench-"
IDLE_MINUTES = 10
MAX_HOURS = 5
UNREACHABLE_MINUTES = 15
GPU_BUSY_PCT = 10
CPU_BUSY_CORES = 0.5
SWITCH_FILE = Path("/etc/pod-guard.env")
MARKER = "$HOME/.wb_last_use"

# Printed by the pod: its own clock, the marker time, the busiest GPU's use, container CPU microseconds before and
# after 5 s. CPU comes from the container's cgroup, not /proc/stat, which shows the whole host in a container.
PROBE = r"""
cpu() { if [ -r /sys/fs/cgroup/cpu.stat ]; then awk '/^usage_usec/{print $2}' /sys/fs/cgroup/cpu.stat;
        elif [ -r /sys/fs/cgroup/cpuacct/cpuacct.usage ]; then echo $(( $(cat /sys/fs/cgroup/cpuacct/cpuacct.usage) / 1000 ));
        else echo -1; fi; }
c1=$(cpu); sleep 5; c2=$(cpu)
g=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1)
echo "now=$(date +%s) marker=$(stat -c %Y MARKER 2>/dev/null || echo 0) gpu=${g:--1} cpu1=$c1 cpu2=$c2"
""".replace("MARKER", MARKER)


def switch_on(env=None):
    """POD_GUARD from the environment wins, then /etc/pod-guard.env; default on."""
    env = os.environ if env is None else env
    if "POD_GUARD" in env:
        return env["POD_GUARD"].strip() not in ("0", "off", "false", "")
    if SWITCH_FILE.exists():
        for line in SWITCH_FILE.read_text().splitlines():
            if line.strip().startswith("POD_GUARD="):
                return line.split("=", 1)[1].strip() not in ("0", "off", "false", "")
    return True


def parse_probe(text):
    vals = dict(kv.split("=", 1) for kv in text.split() if "=" in kv)
    return {k: float(v) for k, v in vals.items()}


def decide(now, born, probe, unreachable_since):
    """Pure decision for one pod. now/born/unreachable_since are box times (s); probe is parse_probe() or None.
    Returns (action, reason), action in {"keep", "terminate"}."""
    if born and now - born >= MAX_HOURS * 3600:
        return "terminate", f"hard stop {MAX_HOURS} h"
    if probe is None:
        if unreachable_since and now - unreachable_since >= UNREACHABLE_MINUTES * 60 and \
                (not born or now - born >= UNREACHABLE_MINUTES * 60):
            return "terminate", f"unreachable {UNREACHABLE_MINUTES} min"
        return "keep", "unreachable, waiting"
    cores = (probe["cpu2"] - probe["cpu1"]) / 5e6 if probe["cpu1"] >= 0 else 0.0
    if probe["gpu"] >= GPU_BUSY_PCT or cores >= CPU_BUSY_CORES:
        return "keep", f"busy (gpu {probe['gpu']:.0f} %, cpu {cores:.2f} cores)"
    # Idle time is measured on the pod's own clock; the pod's birth (name tag) counts as a use so a new pod gets
    # its 10 minutes before the first command.
    last = probe["marker"]
    if born:
        last = max(last, born - (now - probe["now"]))
    idle = (probe["now"] - last) / 60
    if idle >= IDLE_MINUTES:
        return "terminate", f"idle {idle:.0f} min (gpu {probe['gpu']:.0f} %, cpu {cores:.2f} cores)"
    return "keep", f"idle {idle:.0f} min"


def born_of(name):
    try:
        return int(name[len(PREFIX):].split("-")[0])
    except ValueError:
        return None


def ssh_probe(key, target):
    host, port, user = target
    cmd = ["ssh", "-i", str(key), "-p", str(port), "-o", "StrictHostKeyChecking=accept-new",
           "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=15",
           "-o", "BatchMode=yes", f"{user}@{host}", PROBE]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        return None
    try:
        return parse_probe(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def run_once(client, probe_fn, state_path, log, dry_run=False, env=None, now=None):
    """One pass over the account. Returns the list of (pod_id, action, reason)."""
    if not switch_on(env):
        log({"event": "off", "why": "POD_GUARD=0"})
        return []
    now = time.time() if now is None else now
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    seen, results = {}, []
    for pod in client.list_pods():
        name = pod.get("name") or ""
        if not name.startswith(PREFIX):
            continue
        pod = client.get_pod(pod["id"]) if "id" in pod else pod
        if pod.get("status") not in (None, "RUNNING"):
            continue
        target = runpod_api.ssh_target(pod)
        probe = probe_fn(target) if target else None
        since = None
        if probe is None:
            since = state.get(pod["id"], now)
            seen[pod["id"]] = since
        action, reason = decide(now, born_of(name), probe, since)
        if action == "terminate" and not dry_run:
            try:
                client.terminate_pod(pod["id"])
            except runpod_api.RunPodError as exc:
                if "404" not in str(exc):
                    action, reason = "keep", f"terminate failed: {exc}"
        log({"event": action, "pod": pod["id"], "name": name, "why": reason, "rate": pod.get("costPerHr") or pod.get("cost"),
             "dry_run": dry_run})
        results.append((pod["id"], action, reason))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(seen))
    return results


def main():
    dry = "--dry-run" in sys.argv
    cfg = config.load()
    state_dir = Path(cfg["STATE_DIR"])
    logfile = state_dir / "pod-guard.log"

    def log(rec):
        rec = {"when": dt.datetime.now().isoformat(timespec="seconds"), **rec}
        line = json.dumps(rec)
        print(line, flush=True)
        with open(logfile, "a") as fh:
            fh.write(line + "\n")

    client = runpod_api.Client(cfg["RUNPOD_API_KEY"])
    key = cfg["RUNPOD_SSH_KEY"]
    run_once(client, lambda t: ssh_probe(key, t), state_dir / "pod-guard-unreachable.json", log, dry_run=dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
