"""Prove everything about the GPU provider that does not need a GPU.

A paid render cannot be part of verify.sh, so the parts that would cost real money
if they were wrong are pinned here: the exact v2 request shape, the GPU fallback,
the price cap, and above all that a pod is destroyed even when the render blows up.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from renderdesk import config, runpod_api  # noqa: E402
from renderdesk.providers.runpod import RunPodProvider  # noqa: E402

failures = []
ran = []


def check(name, condition, detail=""):
    ran.append(name)
    if condition:
        print(f"  ok   {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"  FAIL {name} {detail}")


class FakeClient:
    def __init__(self, fail_for=(), cost=0.74):
        self.fail_for = fail_for
        self.cost = cost
        self.created = []
        self.terminated = []
        self.pods = []

    def create_pod(self, body):
        self.created.append(body)
        gpu = body["gpu"]["id"]
        if gpu in self.fail_for:
            raise runpod_api.RunPodError(f"HTTP 400: no {gpu} available")
        return {"id": f"pod-{len(self.created)}", "cost": self.cost,
                "status": "PROVISIONING", "gpu": {"id": gpu}}

    def get_pod(self, pod_id):
        return {"id": pod_id, "status": "RUNNING", "cost": self.cost,
                "ssh": {"direct": {"host": "1.2.3.4", "port": 22001, "username": "root"}}}

    def list_pods(self):
        return self.pods

    def terminate_pod(self, pod_id):
        self.terminated.append(pod_id)
        return {}


cfg = config.load()
cfg["RUNPOD_API_KEY"] = "test-key-not-real"
cfg["RUNPOD_VOLUME_ID"] = "vol-test"
cfg["GPU_PREFERENCE"] = "NVIDIA GeForce RTX 4090,NVIDIA A40"

provider = RunPodProvider(cfg)

# --- the request body matches the documented v2 schema ---------------------
provider.client = FakeClient()
pod = provider._create("job-1", lambda *_: None)
body = provider.client.created[0]
check("v2 body: image at the top level", "image" in body and "imageName" not in body)
check("v2 body: gpu is nested {id,count}",
      body.get("gpu", {}).get("id") and body["gpu"].get("count") == 1, str(body.get("gpu")))
check("v2 body: network volume is nested under mounts.network",
      body.get("mounts", {}).get("network", [{}])[0].get("volumeId") == "vol-test",
      str(body.get("mounts")))
check("v2 body: cloud replaces cloudType", body.get("cloud") == "SECURE" and "cloudType" not in body)
check("v2 body: ssh is requested and port 22 exposed",
      body.get("startSsh") is True and "22/tcp" in body.get("ports", []))
check("v2 body: the public key is sent so scp can connect",
      body.get("env", {}).get("PUBLIC_KEY", "").startswith("ssh-"))
check("v2 body: both key env names are sent, since images differ",
      body.get("env", {}).get("SSH_PUBLIC_KEY") == body.get("env", {}).get("PUBLIC_KEY"))
check("pod name is tagged so orphans can be found later",
      body["name"].startswith("renderdesk-"))

# --- an unavailable GPU falls back instead of failing the job --------------
provider.client = FakeClient(fail_for=("NVIDIA GeForce RTX 4090",))
pod = provider._create("job-2", lambda *_: None)
check("falls back to the next GPU when the first is unavailable",
      pod["gpu"]["id"] == "NVIDIA A40", str(pod))

# --- every GPU unavailable is an error, not a silent hang ------------------
provider.client = FakeClient(fail_for=("NVIDIA GeForce RTX 4090", "NVIDIA A40"))
try:
    provider._create("job-3", lambda *_: None)
    check("no GPU available raises", False, "it did not raise")
except RuntimeError as exc:
    check("no GPU available raises a readable error", "no GPU could be rented" in str(exc))

# --- a pod priced above the cap is destroyed immediately -------------------
cfg["GPU_MAX_USD_PER_HOUR"] = "0.50"
capped = RunPodProvider(cfg)
capped.client = FakeClient(cost=9.99)
try:
    capped._create("job-4", lambda *_: None)
    check("price cap refuses an expensive pod", False, "it accepted it")
except RuntimeError as exc:
    check("price cap refuses an expensive pod", "over the" in str(exc))
check("a pod refused on price is terminated, not left running",
      len(capped.client.terminated) == 2, str(capped.client.terminated))

# --- the pod dies even when the render crashes -----------------------------
cfg["GPU_MAX_USD_PER_HOUR"] = "1.20"
crashing = RunPodProvider(cfg)
crashing.client = FakeClient()


def explode(*_a, **_k):
    raise RuntimeError("render machine caught fire")


crashing._wait_ready = explode
try:
    crashing.render(Path("/tmp/nope.blend"), Path("/tmp/rd-contract-frames"), {}, lambda *_: None)
except RuntimeError:
    pass
check("a crashed render still terminates the pod",
      crashing.client.terminated == ["pod-1"], str(crashing.client.terminated))

# --- orphans from a killed run are swept before the next job ---------------
sweeper = RunPodProvider(cfg)
sweeper.client = FakeClient()
sweeper.client.pods = [
    {"id": "old-1", "name": "renderdesk-yesterday", "status": "RUNNING"},
    {"id": "other", "name": "someone-elses-pod", "status": "RUNNING"},
    {"id": "gone", "name": "renderdesk-done", "status": "TERMINATED"},
]
sweeper.sweep_orphans(lambda *_: None)
check("sweep kills leftover render pods only",
      sweeper.client.terminated == ["old-1"], str(sweeper.client.terminated))

# --- ssh target parsing ----------------------------------------------------
check("ssh target reads ssh.direct",
      runpod_api.ssh_target({"ssh": {"direct": {"host": "h", "port": 1, "username": "root"}}})
      == ("h", 1, "root"))
check("ssh target falls back to runtime.ports",
      runpod_api.ssh_target({"runtime": {"ports": [
          {"private": 22, "public": 40000, "ip": "9.9.9.9", "type": "tcp"}]}})
      == ("9.9.9.9", 40000, "root"))
check("ssh target is None before the pod is ready",
      runpod_api.ssh_target({"status": "STARTING"}) is None)

# --- v1 is retired on 15 Nov 2026, so the base URL must be v2 --------------
check("targets API v2", runpod_api.BASE == "https://api.runpod.io/v2", runpod_api.BASE)

# Cloudflare answers the default urllib user agent with a 403 that reads exactly
# like a rejected API key. This cost an hour once; it does not get to happen twice.
check("sends a real user agent past Cloudflare",
      bool(runpod_api.USER_AGENT) and "urllib" not in runpod_api.USER_AGENT.lower(),
      runpod_api.USER_AGENT)

if failures:
    print("\nrunpod_contract FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
    sys.exit(1)
print(f"runpod_contract: {len(ran)} checks passed")
