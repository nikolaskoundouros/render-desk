#!/bin/sh
# Put the current code on the box and restart it. Safe to run as often as you like:
# it never touches the config file that holds the secrets, and it verifies the
# service answers before it calls itself done.
set -e
BOX="${RENDER_DESK_BOX:-root@46.62.230.121}"
ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "==> preparing the box"
ssh "$BOX" 'set -e
  id renderdesk >/dev/null 2>&1 || useradd --system --home /var/lib/render-desk --shell /usr/sbin/nologin renderdesk
  mkdir -p /opt/render-desk /var/lib/render-desk /etc/render-desk
  chown -R renderdesk:renderdesk /var/lib/render-desk
  # A key that exists only on this box, so nothing of Nicks is copied here and it
  # can be revoked on its own.
  if [ ! -f /etc/render-desk/pod_key ]; then
    ssh-keygen -t ed25519 -N "" -C "render-desk@box" -f /etc/render-desk/pod_key >/dev/null
    chown renderdesk:renderdesk /etc/render-desk/pod_key /etc/render-desk/pod_key.pub
    chmod 600 /etc/render-desk/pod_key
  fi'

echo "==> copying the code"
rsync -az --delete \
  --exclude .git --exclude __pycache__ --exclude "*.pyc" \
  "$ROOT/bin" "$ROOT/renderdesk" "$ROOT/checks" "$ROOT/verify.sh" \
  "$BOX:/opt/render-desk/"

echo "==> installing the service"
scp -q "$ROOT/deploy/render-desk.service" "$BOX:/etc/systemd/system/render-desk.service"
ssh "$BOX" 'set -e
  test -f /etc/render-desk/render.env || { echo "no /etc/render-desk/render.env yet, run deploy/configure.sh first" >&2; exit 1; }
  chown -R renderdesk:renderdesk /opt/render-desk
  chown renderdesk:renderdesk /etc/render-desk/render.env
  chmod 600 /etc/render-desk/render.env
  systemctl daemon-reload
  systemctl enable --now render-desk.service >/dev/null
  systemctl restart render-desk.service'

echo "==> checking it answers"
sleep 3
ssh "$BOX" 'systemctl is-active render-desk.service && curl -fsS -o /dev/null -w "page: HTTP %{http_code}\n" http://127.0.0.1:8630/'
echo "shipped."
