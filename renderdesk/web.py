"""A page the editor can use from anywhere: upload a .blend, watch it render, take the mp4.

Standard library only, on purpose. This has to keep running on Nick's Mac for months
without a dependency going stale underneath it.
"""
import hashlib
import hmac
import html
import json
import mimetypes
import os
import secrets
import shutil
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, ledger, providers, watch

COOKIE = "renderdesk"
SESSION_HOURS = 24 * 14
ATTEMPT_WINDOW = 300
MAX_ATTEMPTS = 8


def secret(cfg):
    """A stable signing key for session cookies, kept out of the repo and out of Drive."""
    path = Path(cfg["STATE_DIR"]) / "session.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def sign(cfg, expires):
    mac = hmac.new(secret(cfg).encode(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def valid(cfg, token):
    try:
        expires, mac = (token or "").split(".", 1)
        if float(expires) < time.time():
            return False
        expected = hmac.new(secret(cfg).encode(), expires.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, expected)
    except (ValueError, AttributeError):
        return False


def safe_name(name):
    """A filename the editor typed is not a path. Strip it back to one."""
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    keep = "".join(c for c in name if c.isalnum() or c in "._- ()")
    return keep[:120] or "dropped.blend"


def read_text(path, default=""):
    try:
        return path.read_text()
    except OSError:
        return default


def collect(dirs):
    """Everything the editor should see, newest first."""
    inbox, working, finished, problems = dirs
    items = []
    for folder in sorted(working.iterdir()) if working.exists() else []:
        if folder.is_dir():
            items.append({"state": "working", "name": folder.name,
                          "text": read_text(folder / "STATUS.txt", "Starting.")})
    for folder in sorted(finished.iterdir()) if finished.exists() else []:
        if not folder.is_dir():
            continue
        videos = sorted(folder.glob("*.mp4"))
        items.append({
            "state": "done", "name": folder.name,
            "text": read_text(folder / "READ-ME.txt"),
            "video": videos[0].name if videos else None,
            "preview": "preview.png" if (folder / "preview.png").exists() else None,
        })
    for folder in sorted(problems.iterdir()) if problems.exists() else []:
        if folder.is_dir():
            items.append({"state": "problem", "name": folder.name,
                          "text": read_text(folder / "WHAT-WENT-WRONG.txt")})
    waiting = []
    if inbox.exists():
        for path in sorted(inbox.iterdir()):
            if not path.is_file() or path.suffix.lower() not in watch.ACCEPTS:
                continue
            # A job sent back to the queue leaves its explanation beside it, so the
            # editor sees "waiting for a machine" rather than a bare filename.
            note = inbox / f".status-{path.stem}.txt"
            waiting.append({"name": path.name, "text": read_text(note)})
    items.sort(key=lambda i: i["name"], reverse=True)
    return {"items": items, "waiting": waiting}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Render Desk</title>
<style>
  :root { color-scheme: light dark; --bg:#f6f6f7; --card:#fff; --line:#e2e2e6;
          --text:#16161a; --dim:#6b6b76; --accent:#4f46e5; --ok:#0f7b41; --bad:#b4342a; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#141417; --card:#1c1c21; --line:#2c2c34; --text:#ececed;
            --dim:#9a9aa6; --accent:#8b83ff; --ok:#4ade80; --bad:#f87171; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:16px/1.55 -apple-system,
         BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 32px 16px 80px; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
  .sub { color: var(--dim); font-size: 14px; margin: 0 0 28px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
          padding: 18px; margin-bottom: 14px; }
  #drop { border: 2px dashed var(--line); border-radius: 12px; padding: 34px 18px;
          text-align: center; cursor: pointer; transition: border-color .15s, background .15s; }
  #drop.hot { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); }
  #drop b { display:block; font-size:17px; margin-bottom:6px; }
  #drop span { color: var(--dim); font-size: 14px; }
  .bar { height: 6px; background: var(--line); border-radius: 99px; overflow: hidden; margin-top: 14px; }
  .bar i { display:block; height:100%; width:0; background: var(--accent); transition: width .2s; }
  .row { display:flex; align-items:baseline; justify-content:space-between; gap:12px; }
  .tag { font-size:12px; font-weight:600; padding:3px 9px; border-radius:99px;
         border:1px solid var(--line); white-space:nowrap; }
  .working .tag { color: var(--accent); } .done .tag { color: var(--ok); } .problem .tag { color: var(--bad); }
  pre { white-space: pre-wrap; margin: 10px 0 0; font: 14px/1.5 ui-monospace, SFMono-Regular,
        Menlo, monospace; color: var(--dim); }
  a.btn { display:inline-block; margin-top:12px; margin-right:8px; padding:9px 15px; border-radius:9px;
          background: var(--accent); color:#fff; text-decoration:none; font-size:14px; font-weight:600; }
  a.plain { background: transparent; color: var(--accent); border:1px solid var(--line); }
  img.prev { margin-top:12px; max-width: 200px; border-radius:8px; border:1px solid var(--line); display:block; }
  form.out { margin-top:32px; } button.link { background:none; border:none; color:var(--dim);
        font-size:13px; text-decoration:underline; cursor:pointer; padding:0; }
  .empty { color: var(--dim); font-size: 14px; }
</style></head><body><div class="wrap">
<h1>Render Desk</h1>
<p class="sub">Drop a Blender file. It comes back as a video.</p>

<div class="card">
  <div id="drop"><b>Choose a file or drop it here</b>
    <span>.blend, or a .zip of the whole project folder</span></div>
  <input id="file" type="file" accept=".blend,.zip" hidden>
  <div class="bar" id="barwrap" hidden><i id="bar"></i></div>
  <span id="limit" data-mb="__MAXMB__" hidden></span>
  <p class="sub" id="note" style="margin:12px 0 0"></p>
</div>

<div class="card" style="background:transparent;border-style:dashed">
  <p class="sub" style="margin:0">Before you upload, in Blender do
  <b>File &gt; External Data &gt; Automatically Pack Resources</b>, then save. That puts the textures
  inside the file. Put <b>_draft</b> in the filename for a fast, cheap look test.</p>
</div>

<div id="jobs"></div>
<form class="out" method="post" action="/logout"><button class="link">Sign out</button></form>
</div>
<script>
const drop = document.getElementById('drop'), file = document.getElementById('file');
const bar = document.getElementById('bar'), barwrap = document.getElementById('barwrap');
const note = document.getElementById('note'), jobs = document.getElementById('jobs');

drop.onclick = () => file.click();
file.onchange = () => file.files[0] && upload(file.files[0]);
['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add('hot'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove('hot'); }));
drop.addEventListener('drop', ev => ev.dataTransfer.files[0] && upload(ev.dataTransfer.files[0]));

const MAXMB = parseInt(document.getElementById('limit').dataset.mb, 10);
function upload(f) {
  if (!/\\.(blend|zip)$/i.test(f.name)) { note.textContent = 'That needs to be a .blend or a .zip.'; return; }
  if (f.size > MAXMB * 1024 * 1024) {
    note.textContent = 'That file is ' + Math.round(f.size / 1048576) + ' MB, over the ' + MAXMB
      + ' MB limit. Ask Nick to raise it, or send the .blend without the heavy textures.';
    return;
  }
  const xhr = new XMLHttpRequest();
  xhr.open('PUT', '/upload?name=' + encodeURIComponent(f.name));
  barwrap.hidden = false;
  note.textContent = 'Uploading ' + f.name + '...';
  xhr.upload.onprogress = e => { if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + '%'; };
  xhr.onload = () => {
    barwrap.hidden = true; bar.style.width = '0';
    note.textContent = xhr.status === 200
      ? f.name + ' received. It appears below within a minute.'
      : 'Upload failed: ' + xhr.responseText;
    refresh();
  };
  xhr.onerror = () => { barwrap.hidden = true; note.textContent = 'Upload failed. Try again.'; };
  xhr.send(f);
}

const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LABEL = { working: 'Rendering', done: 'Ready', problem: 'Needs a fix' };

async function refresh() {
  let data;
  try { data = await (await fetch('/api/state')).json(); } catch (e) { return; }
  if (!data.items.length && !data.waiting.length) {
    jobs.innerHTML = '<p class="empty">Nothing here yet.</p>'; return;
  }
  jobs.innerHTML = data.waiting.map(w =>
    `<div class="card working"><div class="row"><b>${esc(w.name)}</b>
     <span class="tag">${w.text ? 'Waiting' : 'Just uploaded'}</span></div>
     ${w.text ? `<pre>${esc(w.text)}</pre>` : ''}</div>`).join('')
  + data.items.map(i => {
    let extra = '';
    if (i.preview) extra += `<img class="prev" src="/file/${encodeURIComponent(i.name)}/${i.preview}" alt="">`;
    if (i.video) extra += `<a class="btn" href="/file/${encodeURIComponent(i.name)}/${i.video}" download>Download the video</a>`;
    return `<div class="card ${i.state}"><div class="row"><b>${esc(i.name)}</b>
      <span class="tag">${LABEL[i.state]}</span></div>
      <pre>${esc(i.text)}</pre>${extra}</div>`;
  }).join('');
}
refresh(); setInterval(refresh, 8000);
</script></body></html>
"""

LOGIN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Render Desk</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; min-height:100vh; display:grid; place-items:center; background:#f6f6f7;
         font: 16px -apple-system, BlinkMacSystemFont, system-ui, sans-serif; color:#16161a; }
  @media (prefers-color-scheme: dark) { body { background:#141417; color:#ececed; } }
  form { background:#fff; border-radius:12px; padding:30px; width:320px;
         border:1px solid #e2e2e6; }
  @media (prefers-color-scheme: dark) { form { background:#1c1c21; border-color:#2c2c34; } }
  h1 { font-size:19px; margin:0 0 18px; }
  input { width:100%; padding:11px; font-size:16px; border-radius:9px; border:1px solid #c9c9d1;
          background:transparent; color:inherit; }
  button { width:100%; margin-top:12px; padding:11px; font-size:15px; font-weight:600;
           border:none; border-radius:9px; background:#4f46e5; color:#fff; cursor:pointer; }
  p { color:#b4342a; font-size:14px; margin:12px 0 0; }
</style></head><body>
<form method="post" action="/login">
  <h1>Render Desk</h1>
  <input type="password" name="password" placeholder="Password" autofocus
         autocomplete="current-password" required>
  <button>Sign in</button>
  __ERROR__
</form></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "renderdesk"
    sys_version = ""
    cfg = {}
    dirs = ()
    attempts = []
    lock = threading.Lock()

    def log_message(self, fmt, *args):  # one tidy line, not Apache noise
        print(f"  web {self.address_string()} {fmt % args}")

    # --- helpers -------------------------------------------------------------
    def send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, where, headers=()):
        self.send(HTTPStatus.SEE_OTHER, b"", headers=(("Location", where),) + tuple(headers))

    def authed(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return valid(self.cfg, value)
        return False

    def throttled(self):
        """Eight wrong passwords in five minutes and the door stops answering."""
        now = time.time()
        with self.lock:
            Handler.attempts = [t for t in Handler.attempts if now - t < ATTEMPT_WINDOW]
            return len(Handler.attempts) >= MAX_ATTEMPTS

    # --- routes --------------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if not self.authed():
            if path == "/":
                return self.send(HTTPStatus.OK, LOGIN.replace("__ERROR__", ""))
            return self.send(HTTPStatus.UNAUTHORIZED, "Sign in first.", "text/plain; charset=utf-8")
        if path == "/":
            return self.send(HTTPStatus.OK,
                             PAGE.replace("__MAXMB__", str(int(self.cfg["MAX_UPLOAD_MB"]))))
        if path == "/api/state":
            return self.send(HTTPStatus.OK, json.dumps(collect(self.dirs)),
                             "application/json; charset=utf-8")
        if path.startswith("/file/"):
            return self.serve_file(path)
        return self.send(HTTPStatus.NOT_FOUND, "Not found.", "text/plain; charset=utf-8")

    def serve_file(self, path):
        parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
        if len(parts) != 3:
            return self.send(HTTPStatus.NOT_FOUND, "Not found.", "text/plain; charset=utf-8")
        _, job, name = parts
        root = self.dirs[2].resolve()
        target = (root / job / name).resolve()
        # A filename from a URL is never trusted to stay inside the folder.
        if not str(target).startswith(str(root) + os.sep) or not target.is_file():
            return self.send(HTTPStatus.NOT_FOUND, "Not found.", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with target.open("rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 1 << 20)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            return self.login()
        if path == "/logout":
            return self.redirect("/", (("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0"),))
        return self.send(HTTPStatus.NOT_FOUND, "Not found.", "text/plain; charset=utf-8")

    def login(self):
        if self.throttled():
            return self.send(HTTPStatus.TOO_MANY_REQUESTS,
                             LOGIN.replace("__ERROR__", "<p>Too many tries. Wait five minutes.</p>"))
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        given = (form.get("password") or [""])[0]
        want = self.cfg["EDITOR_PASSWORD"]
        if not want:
            return self.send(HTTPStatus.SERVICE_UNAVAILABLE,
                             LOGIN.replace("__ERROR__", "<p>No password is set yet.</p>"))
        if not hmac.compare_digest(given, want):
            with self.lock:
                Handler.attempts.append(time.time())
            time.sleep(1)
            return self.send(HTTPStatus.UNAUTHORIZED,
                             LOGIN.replace("__ERROR__", "<p>Wrong password.</p>"))
        token = sign(self.cfg, int(time.time() + SESSION_HOURS * 3600))
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return self.redirect("/", (("Set-Cookie",
                                    f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax"
                                    f"; Max-Age={SESSION_HOURS * 3600}{secure}"),))

    def do_PUT(self):
        if not self.authed():
            return self.send(HTTPStatus.UNAUTHORIZED, "Sign in first.", "text/plain; charset=utf-8")
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/upload":
            return self.send(HTTPStatus.NOT_FOUND, "Not found.", "text/plain; charset=utf-8")
        name = safe_name(urllib.parse.parse_qs(parsed.query).get("name", [""])[0])
        if Path(name).suffix.lower() not in watch.ACCEPTS:
            return self.send(HTTPStatus.BAD_REQUEST, "Only .blend or .zip files.",
                             "text/plain; charset=utf-8")
        length = int(self.headers.get("Content-Length") or 0)
        limit = int(self.cfg["MAX_UPLOAD_MB"]) * 1024 * 1024
        if length <= 0:
            return self.send(HTTPStatus.BAD_REQUEST, "Empty file.", "text/plain; charset=utf-8")
        if length > limit:
            # Answer before reading the body: there is no reason to accept gigabytes
            # only to throw them away. The browser checks the size first anyway.
            return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                             f"That file is bigger than the {self.cfg['MAX_UPLOAD_MB']} MB limit.",
                             "text/plain; charset=utf-8",
                             headers=(("Connection", "close"),))

        inbox = self.dirs[0]
        # Land it under a dot-name first: the watcher ignores those, so a half-uploaded
        # file can never be picked up and rendered.
        staging = inbox / f".part-{secrets.token_hex(4)}"
        written = 0
        try:
            with staging.open("wb") as fh:
                while written < length:
                    chunk = self.rfile.read(min(1 << 20, length - written))
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
            if written != length:
                raise OSError(f"upload stopped early ({written} of {length} bytes)")
            final = inbox / name
            stem, suffix = Path(name).stem, Path(name).suffix
            count = 2
            while final.exists():
                final = inbox / f"{stem}-{count}{suffix}"
                count += 1
            staging.replace(final)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            return self.send(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc),
                             "text/plain; charset=utf-8")
        return self.send(HTTPStatus.OK, "ok", "text/plain; charset=utf-8")


def serve(cfg, with_watcher=True):
    dirs = watch.ensure_folders(cfg)
    if not cfg["EDITOR_PASSWORD"]:
        raise SystemExit("no EDITOR_PASSWORD set. Run: bin/renderdesk password")
    Handler.cfg, Handler.dirs = cfg, dirs

    if with_watcher:
        thread = threading.Thread(target=watch.loop, args=(cfg,), daemon=True)
        thread.start()

    host, port = cfg["WEB_HOST"], int(cfg["WEB_PORT"])
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"render desk on http://{host}:{port}  (provider={cfg['PROVIDER']})")
    httpd.serve_forever()
