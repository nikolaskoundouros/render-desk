#!/usr/bin/env python3
"""Tests for pod_guard.py with a fake RunPod account. Run: python3 tools/pod_guard_test.py
The last test runs the real probe script in bash on this machine (a stand-in pod) and checks it parses."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pod_guard as g  # noqa: E402

NOW = 1_800_000_000.0


class FakeClient:
    def __init__(self, pods):
        self.pods = {p["id"]: p for p in pods}
        self.terminated = []

    def list_pods(self):
        return [{"id": p["id"], "name": p["name"]} for p in self.pods.values()]

    def get_pod(self, pod_id):
        return self.pods[pod_id]

    def terminate_pod(self, pod_id):
        self.terminated.append(pod_id)


def pod(pid, name, ssh=True):
    p = {"id": pid, "name": name, "status": "RUNNING", "costPerHr": 0.69}
    if ssh:
        p["ssh"] = {"direct": {"host": "10.0.0.1", "port": 22, "username": "root"}}
    return p


def probe(idle_min, gpu=0, cores=0.0):
    return {"now": NOW, "marker": NOW - idle_min * 60, "gpu": gpu, "cpu1": 0, "cpu2": cores * 5e6}


def run(pods, probes, env, state=None):
    c = FakeClient(pods)
    logs = []
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "state.json"
        if state:
            sp.write_text(state)
        g.run_once(c, lambda t: probes.pop(0), sp, logs.append, env=env, now=NOW)
    return c.terminated, logs


ON, OFF = {"POD_GUARD": "1"}, {"POD_GUARD": "0"}
born_old = f"workbench-{int(NOW - 3600)}"
cases = []


def check(name, got, want):
    ok = got == want
    cases.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f": got {got}, want {want}"))


check("idle 11 min -> terminated", run([pod("a", born_old)], [probe(11)], ON)[0], ["a"])
check("SWITCH OFF: same idle pod -> nothing terminated", run([pod("a", born_old)], [probe(11)], OFF)[0], [])
check("switch off logs 'off'", run([pod("a", born_old)], [probe(11)], OFF)[1][0]["event"], "off")
check("idle 5 min -> kept", run([pod("a", born_old)], [probe(5)], ON)[0], [])
check("idle 30 min but GPU 85 % -> kept", run([pod("a", born_old)], [probe(30, gpu=85)], ON)[0], [])
check("idle 30 min but CPU 1 core -> kept", run([pod("a", born_old)], [probe(30, cores=1.0)], ON)[0], [])
check("live Blender idle: GPU 0 %, CPU 0.05 cores, 12 min -> terminated",
      run([pod("a", born_old)], [probe(12, cores=0.05)], ON)[0], ["a"])
check("older than 5 h and busy -> terminated (hard stop)",
      run([pod("a", f"workbench-{int(NOW - 5.1 * 3600)}")], [probe(0, gpu=99)], ON)[0], ["a"])
check("new pod, no marker yet, 3 min old -> kept",
      run([pod("a", f"workbench-{int(NOW - 180)}")], [{**probe(0), "marker": 0}], ON)[0], [])
check("new pod, no marker, 11 min old -> terminated",
      run([pod("a", f"workbench-{int(NOW - 660)}")], [{**probe(0), "marker": 0}], ON)[0], ["a"])
check("desk job pod renderdesk-* -> never touched",
      run([pod("r", "renderdesk-x-t1"), pod("a", born_old)], [probe(5)], ON)[0], [])
check("unreachable first time -> kept", run([pod("a", born_old)], [None], ON)[0], [])
check("unreachable for 16 min -> terminated",
      run([pod("a", born_old)], [None], ON, state='{"a": %f}' % (NOW - 960))[0], ["a"])
check("two pods: idle one goes, busy one stays",
      run([pod("a", born_old), pod("b", born_old)], [probe(20), probe(20, gpu=50)], ON)[0], ["a"])

# the real probe, in bash on this machine, against a marker 2 minutes old
with tempfile.TemporaryDirectory() as home:
    marker = Path(home) / ".wb_last_use"
    marker.touch()
    subprocess.run(["touch", "-d", "@%d" % (int(__import__("time").time()) - 120), str(marker)], check=True)
    out = subprocess.run(["bash", "-c", g.PROBE], capture_output=True, text=True, env={"HOME": home, "PATH": "/usr/bin:/bin"})
    p = g.parse_probe(out.stdout.strip().splitlines()[-1])
    print("probe said:", out.stdout.strip())
    check("real probe: marker age ~120 s", round((p["now"] - p["marker"]) / 10) * 10, 120)
    check("real probe: CPU counter readable", p["cpu1"] >= 0 and p["cpu2"] >= p["cpu1"], True)
    action, why = g.decide(p["now"], None, p, None)
    print("decision on this machine:", action, why)

print(f"{sum(cases)}/{len(cases)} passed")
sys.exit(0 if all(cases) else 1)
