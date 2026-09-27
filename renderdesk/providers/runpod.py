"""Render on a RunPod GPU that exists only while the job runs.

The three rules this file exists to keep:
  1. a pod is always destroyed, including when the job crashes or is killed,
  2. frames live on the network volume, so an interrupted job resumes instead of
     paying to re-render what it already has,
  3. every job records what it actually cost, because finding that number out is
     the whole reason this exists.
"""
import json
import shlex
import subprocess
import time
from pathlib import Path

from .. import preflight, runpod_api

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
POD_PREFIX = "renderdesk-"


class RunPodProvider:
    name = "runpod"

    def __init__(self, cfg):
        self.cfg = cfg
        self.client = runpod_api.Client(cfg["RUNPOD_API_KEY"])
        self.key = Path(cfg["RUNPOD_SSH_KEY"]).expanduser()
        if not self.key.exists():
            raise runpod_api.RunPodError(
                f"no ssh key at {self.key}. Generate one with: ssh-keygen -t ed25519, "
                "then add the .pub to your RunPod account settings."
            )
        self.version = cfg["BLENDER_VERSION"]

    # --- ssh -----------------------------------------------------------------
    def _ssh_base(self, target):
        host, port, user = target
        return ["ssh", "-i", str(self.key), "-p", str(port),
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=15",
                f"{user}@{host}"]

    def _run(self, target, command, log=None, timeout=None):
        proc = subprocess.Popen(self._ssh_base(target) + [command],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            tail.append(line)
            del tail[:-60]
            if log:
                log(line)
        proc.wait(timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"on the render machine: {' / '.join(tail[-12:])}")
        return tail

    def _copy(self, target, local, remote, up=True):
        host, port, user = target
        args = ["scp", "-i", str(self.key), "-P", str(port),
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR", "-r"]
        pair = [str(local), f"{user}@{host}:{remote}"] if up else [f"{user}@{host}:{remote}", str(local)]
        proc = subprocess.run(args + pair, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"file transfer failed: {proc.stderr.strip()[:400]}")

    # --- pod lifecycle -------------------------------------------------------
    def sweep_orphans(self, log=print):
        """Kill anything this desk left behind. Cheap insurance against a pod
        quietly billing all night because a previous run was killed."""
        killed = []
        for pod in self.client.list_pods():
            name = pod.get("name", "")
            if name.startswith(POD_PREFIX) and pod.get("status") not in ("TERMINATED", "EXITED"):
                self.client.terminate_pod(pod["id"])
                killed.append(name)
        if killed:
            log(f"RD_SWEEP terminated leftover pods: {', '.join(killed)}")
        return killed

    def _create(self, job_name, log):
        wanted = [g.strip() for g in self.cfg["GPU_PREFERENCE"].split(",") if g.strip()]
        cap = float(self.cfg["GPU_MAX_USD_PER_HOUR"])
        errors = []
        for gpu_id in wanted:
            body = {
                "name": f"{POD_PREFIX}{job_name}"[:191],
                "image": self.cfg["RUNPOD_IMAGE"],
                "gpu": {"id": gpu_id, "count": 1},
                "cloud": "SECURE",
                "disk": 20,
                "ports": ["22/tcp"],
                "startSsh": True,
                "env": {"PUBLIC_KEY": Path(str(self.key) + ".pub").read_text().strip()},
                "mounts": {"network": [{"volumeId": self.cfg["RUNPOD_VOLUME_ID"],
                                        "path": "/workspace"}]},
            }
            # A network volume lives in one data centre and a pod can only attach it
            # from inside that same one, so asking elsewhere fails in a confusing way.
            if self.cfg.get("RUNPOD_DATA_CENTER"):
                body["dataCenterIds"] = [self.cfg["RUNPOD_DATA_CENTER"]]
            try:
                pod = self.client.create_pod(body)
            except runpod_api.RunPodError as exc:
                errors.append(f"{gpu_id}: {exc}")
                log(f"RD_POD {gpu_id} unavailable, trying the next one")
                continue
            cost = float(pod.get("cost") or 0)
            if cost > cap:
                self.client.terminate_pod(pod["id"])
                errors.append(f"{gpu_id}: ${cost}/hr is over the ${cap}/hr cap")
                continue
            log(f"RD_POD {pod['id']} {gpu_id} ${cost:.2f}/hr")
            return pod
        raise RuntimeError("no GPU could be rented right now.\n" + "\n".join(errors))

    def _wait_ready(self, pod_id, log, timeout=600):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            pod = self.client.get_pod(pod_id)
            status = pod.get("status")
            if status != last:
                log(f"RD_POD status {status}")
                last = status
            if status in ("ERROR", "TERMINATED", "EXITED"):
                raise RuntimeError(f"the rented machine stopped before it could render ({status})")
            target = runpod_api.ssh_target(pod)
            if status == "RUNNING" and target:
                for _ in range(40):
                    probe = subprocess.run(self._ssh_base(target) + ["echo ready"],
                                           capture_output=True, text=True)
                    if probe.returncode == 0:
                        return pod, target
                    time.sleep(5)
                raise RuntimeError("the machine started but never accepted a connection")
            time.sleep(10)
        raise RuntimeError(f"the machine did not start within {timeout // 60} minutes")

    # --- the job -------------------------------------------------------------
    def render(self, blend, frames_dir, opts, log, on_scene=None):
        job = frames_dir.name
        remote_job = f"/workspace/jobs/{job}"
        remote_frames = f"/workspace/frames/{job}"
        started = time.time()
        pod = None
        result = {"provider": self.name, "cost_usd": 0.0}
        try:
            self.sweep_orphans(log)
            pod = self._create(job, log)
            result["pod_id"] = pod["id"]
            result["gpu"] = (pod.get("gpu") or {}).get("id", "unknown")
            rate = float(pod.get("cost") or 0)
            pod, target = self._wait_ready(pod["id"], log)
            rate = float(pod.get("cost") or rate)
            result["usd_per_hour"] = rate

            self._run(target, f"mkdir -p {remote_job} {remote_frames}")
            self._copy(target, SCRIPTS / "pod_bootstrap.sh", "/workspace/pod_bootstrap.sh")
            self._copy(target, SCRIPTS / "render_job.py", "/workspace/render_job.py")
            root = opts.get("root")
            if root:
                # The scene came out of a .zip, so everything beside it goes too.
                root = Path(root)
                self._copy(target, root, remote_job + "/")
                relative = blend.relative_to(root)
                remote_blend = f"{remote_job}/{root.name}/{relative}"
            else:
                self._copy(target, blend, remote_job + "/")
                remote_blend = f"{remote_job}/{blend.name}"

            log("RD_SETUP preparing the machine")
            self._run(target, f"bash /workspace/pod_bootstrap.sh {shlex.quote(self.version)}", log)

            blender = f"/workspace/blender/{self.version}/blender"

            if on_scene is not None:
                # Inspect the scene here, on the machine that will render it, before a
                # single frame is paid for. A file that fails the gate aborts the job
                # and the pod is destroyed in the finally block below.
                self._copy(target, SCRIPTS / "preflight_blend.py", "/workspace/preflight.py")
                report_remote = f"{remote_job}/scene.json"
                log("RD_SETUP inspecting the scene")
                self._run(target,
                          f"{blender} -b {shlex.quote(remote_blend)} --factory-startup -noaudio "
                          f"--python /workspace/preflight.py -- {shlex.quote(report_remote)}")
                local_report = frames_dir.parent / f"{job}-scene.json"
                frames_dir.parent.mkdir(parents=True, exist_ok=True)
                self._copy(target, local_report, report_remote, up=False)
                report = json.loads(local_report.read_text())
                local_report.unlink(missing_ok=True)
                on_scene(report)
                opts = dict(opts, fps=report["fps"])
            cmd = (f"{blender} -b {shlex.quote(remote_blend)} --factory-startup -noaudio "
                   f"--python /workspace/render_job.py -- --out {shlex.quote(remote_frames)} "
                   f"--device OPTIX")
            if opts.get("samples"):
                cmd += f" --samples {int(opts['samples'])}"
            if opts.get("scale"):
                cmd += f" --scale {int(opts['scale'])}"
            self._run(target, cmd, log)

            counted = self._run(target, f"ls {remote_frames}/frame_*.png 2>/dev/null | wc -l")
            result["frames_rendered"] = int((counted[-1] if counted else "0").strip() or 0)
            if not result["frames_rendered"]:
                raise RuntimeError("the render finished without producing a single frame")

            fps = opts.get("fps") or 30
            out_mp4 = f"{remote_job}/render.mp4"
            listing = self._run(target, f"ls {remote_frames}/frame_*.png | head -1")
            first = listing[-1] if listing else ""
            start_number = "".join(c for c in Path(first).stem if c.isdigit()) or "1"
            self._run(target,
                      f"/workspace/bin/ffmpeg -y -framerate {fps} -start_number {int(start_number)} "
                      f"-i {remote_frames}/frame_%05d.png -c:v libx264 -preset slow -crf 16 "
                      f"-pix_fmt yuv420p -movflags +faststart {out_mp4} 2>&1 | tail -3")
            frames_dir.mkdir(parents=True, exist_ok=True)
            self._copy(target, frames_dir / "render.mp4", out_mp4, up=False)
            middle = self._run(target,
                               f"ls {remote_frames}/frame_*.png | sed -n "
                               f"{max(1, result['frames_rendered'] // 2)}p")[-1]
            self._copy(target, frames_dir / "preview.png", middle.strip(), up=False)
            result["mp4"] = frames_dir / "render.mp4"
            result["preview"] = frames_dir / "preview.png"
            return result
        finally:
            elapsed = time.time() - started
            result["seconds"] = round(elapsed, 1)
            result["cost_usd"] = round(result.get("usd_per_hour", 0) * elapsed / 3600, 4)
            if pod:
                for attempt in range(5):
                    try:
                        self.client.terminate_pod(pod["id"])
                        log(f"RD_POD terminated {pod['id']} after {elapsed / 60:.1f} min, "
                            f"${result['cost_usd']:.2f}")
                        break
                    except Exception as exc:  # never give up quietly on a billing machine
                        log(f"RD_POD terminate attempt {attempt + 1} failed: {exc}")
                        time.sleep(5)
                else:
                    log(f"RD_ALERT could not terminate pod {pod['id']}, stop it in the RunPod console")
