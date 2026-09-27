"""Thin client for the RunPod REST API v2.

v1 (rest.runpod.io/v1) is deprecated and retires on 15 November 2026, so this
targets v2 only. Nothing here is guessed: every path and field name below comes
from the v2 reference, and anything the API rejects is surfaced verbatim rather
than swallowed, because a wrong field must not turn into a silently wrong pod.
"""
import json
import urllib.error
import urllib.request

BASE = "https://api.runpod.io/v2"

# RunPod sits behind Cloudflare, which rejects the default urllib user agent with
# a 403 "error code: 1010" that looks exactly like a bad API key. Any real name works.
USER_AGENT = "render-desk/1.0"


class RunPodError(RuntimeError):
    pass


class Client:
    def __init__(self, api_key, base=BASE):
        if not api_key:
            raise RunPodError("no RunPod API key set (put RUNPOD_API_KEY in render.env)")
        self.api_key = api_key
        self.base = base

    def request(self, method, path, body=None, timeout=60):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:1200]
            raise RunPodError(f"{method} {path} -> HTTP {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise RunPodError(f"{method} {path} -> cannot reach RunPod: {exc.reason}") from None
        return json.loads(raw) if raw.strip() else {}

    # --- pods ----------------------------------------------------------------
    def create_pod(self, body):
        return self.request("POST", "/pods", body)

    def get_pod(self, pod_id):
        return self.request("GET", f"/pods/{pod_id}")

    def list_pods(self):
        out = self.request("GET", "/pods")
        return out if isinstance(out, list) else out.get("pods", out.get("data", []))

    def terminate_pod(self, pod_id):
        return self.request("DELETE", f"/pods/{pod_id}")


def ssh_target(pod):
    """(host, port, user) for a direct SSH connection, or None if not ready yet.

    Prefers the ssh.direct block the API reports. Falls back to the 22/tcp entry
    in runtime.ports, which carries the same information.
    """
    direct = (pod.get("ssh") or {}).get("direct") or {}
    if direct.get("host") and direct.get("port"):
        return direct["host"], int(direct["port"]), direct.get("username") or "root"
    for port in ((pod.get("runtime") or {}).get("ports") or []):
        if port.get("private") == 22 and port.get("public") and port.get("ip"):
            return port["ip"], int(port["public"]), "root"
    return None
