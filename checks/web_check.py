"""Prove the editor's page lets the right person in and nobody else.

This page will sit on the open internet behind one password, so the checks that
matter are the ones about the door and about what a URL is allowed to reach.
"""
import http.client
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from renderdesk import config, watch, web  # noqa: E402

failures = []
ran = []


def check(name, condition, detail=""):
    ran.append(name)
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + (f"  {detail}" if not condition else ""))
    if not condition:
        failures.append(name)


tmp = Path(tempfile.mkdtemp())
cfg = config.load()
cfg.update({
    "INBOX": str(tmp / "1-drop-here"), "WORKING": str(tmp / "2-working"),
    "FINISHED": str(tmp / "3-finished"), "STATE_DIR": str(tmp / "state"),
    "EDITOR_PASSWORD": "correct-horse-battery", "MAX_UPLOAD_MB": "1",
})
dirs = watch.ensure_folders(cfg)
web.Handler.cfg, web.Handler.dirs = cfg, dirs
web.Handler.log_message = lambda *a, **k: None

httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.2)


def call(method, path, body=None, cookie=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    head = dict(headers or {})
    if cookie:
        head["Cookie"] = f"{web.COOKIE}={cookie}"
    if body is not None and "Content-Type" not in head:
        head["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, path, body=body, headers=head)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, resp.getheader("Set-Cookie"), data


# --- the door --------------------------------------------------------------
status, _, body = call("GET", "/")
check("signed out, the root shows a login form", status == 200 and b'type="password"' in body)
check("signed out, the root does not leak the app", b"Drop a Blender file" not in body)

status, _, _ = call("GET", "/api/state")
check("signed out, the job list is refused", status == 401, str(status))

status, _, _ = call("PUT", "/upload?name=x.blend", body=b"junk")
check("signed out, uploading is refused", status == 401, str(status))

status, cookie, _ = call("POST", "/login", body="password=wrong")
check("the wrong password is refused", status == 401 and not cookie, str(status))

status, cookie, _ = call("POST", "/login", body="password=correct-horse-battery")
check("the right password signs you in", status == 303 and cookie, str(status))
token = cookie.split("=", 1)[1].split(";")[0]
check("the session cookie is HttpOnly and SameSite",
      "HttpOnly" in cookie and "SameSite" in cookie, cookie)

status, _, body = call("GET", "/", cookie=token)
check("signed in, the app loads", status == 200 and b"Drop a Blender file" in body)
check("the page carries its own size limit so the browser refuses early",
      b'data-mb="1"' in body and b"__MAXMB__" not in body)

status, _, _ = call("GET", "/api/state", cookie="1799999999.deadbeef")
check("a forged cookie is refused", status == 401, str(status))
check("an expired cookie is refused", not web.valid(cfg, web.sign(cfg, time.time() - 10)))

# --- uploads ---------------------------------------------------------------
status, _, _ = call("PUT", "/upload?name=shot.blend", body=b"x" * 500, cookie=token)
landed = list(Path(cfg["INBOX"]).glob("shot.blend"))
check("an upload lands in the drop folder", status == 200 and landed, str(status))

status, _, _ = call("PUT", "/upload?name=shot.blend", body=b"x" * 400, cookie=token)
check("a second upload of the same name does not overwrite the first",
      (Path(cfg["INBOX"]) / "shot-2.blend").exists())

status, _, _ = call("PUT", "/upload?name=nasty.exe", body=b"x" * 10, cookie=token)
check("a file that is not a .blend or .zip is refused", status == 400, str(status))

try:
    # The server answers 413 from the Content-Length alone and closes, so the client
    # may see the refusal or a dropped connection. Both mean the file was refused.
    status = call("PUT", "/upload?name=huge.blend",
                  body=b"x" * (2 * 1024 * 1024), cookie=token)[0]
except (BrokenPipeError, ConnectionResetError):
    status = 413
check("an upload over the size limit is refused", status == 413, str(status))
check("a refused upload never reaches the drop folder",
      not (Path(cfg["INBOX"]) / "huge.blend").exists())

check("a part-finished upload is invisible to the watcher",
      all(not n.startswith(watch.IGNORE_PREFIXES) for n in ["shot.blend"])
      and ".part-x" .startswith(watch.IGNORE_PREFIXES))

# --- what a URL may reach --------------------------------------------------
secret = tmp / "secret.txt"
secret.write_text("private")
for attack in ["/file/../../secret.txt", "/file/x/..%2f..%2fsecret.txt",
               "/file/..%2f../secret.txt", "/file/x/%2e%2e%2f%2e%2e%2fsecret.txt"]:
    status, _, body = call("GET", attack, cookie=token)
    check(f"path traversal refused: {attack}", status == 404 and b"private" not in body, str(status))

real = Path(cfg["FINISHED"]) / "job1"
real.mkdir(parents=True, exist_ok=True)
(real / "out.mp4").write_bytes(b"video-bytes")
status, _, body = call("GET", "/file/job1/out.mp4", cookie=token)
check("a finished video downloads", status == 200 and body == b"video-bytes", str(status))

# --- brute force -----------------------------------------------------------
web.Handler.attempts = []
codes = [call("POST", "/login", body="password=nope")[0] for _ in range(10)]
check("repeated wrong passwords get locked out", 429 in codes, str(codes[-3:]))

httpd.shutdown()
if failures:
    print(f"\nweb_check FAILED: {len(failures)}", file=sys.stderr)
    sys.exit(1)
print(f"web_check: {len(ran)} checks passed")
