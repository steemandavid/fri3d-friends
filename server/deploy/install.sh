#!/usr/bin/env bash
# Install the Gotcha backend on the game laptop (plan §6.1).
#
# Everything this script touches is listed in server/DEPLOY_LOG.md together with
# the command that undoes it, and `uninstall.sh` reverses the whole thing. Run it
# from a checkout of this repo:
#
#     sudo server/deploy/install.sh
#
# Idempotent: safe to re-run to deploy a new version.
set -euo pipefail

APP_DIR=/opt/gotcha
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_DIR=/var/lib/gotcha
ETC_DIR=/etc/gotcha
UNIT=/etc/systemd/system/gotcha.service
PORT="${GOTCHA_PORT:-8080}"

if [[ $EUID -ne 0 ]]; then echo "run with sudo" >&2; exit 1; fi

echo "==> user and directories"
id -u gotcha >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin gotcha
install -d -o root -g root -m 0755 "$APP_DIR"
install -d -o gotcha -g gotcha -m 0750 "$DB_DIR"
# Re-take ownership of the *contents* too: after an uninstall/reinstall cycle the
# `gotcha` user is recreated, usually with a different uid, and an existing
# database would otherwise be left owned by a uid that no longer exists -- the
# service starts and then cannot write.
chown -R gotcha:gotcha "$DB_DIR"
install -d -o root -g gotcha -m 0750 "$ETC_DIR"

echo "==> code -> $APP_DIR/server"
rm -rf "$APP_DIR/server"
install -d -m 0755 "$APP_DIR/server"
cp -r "$SRC_DIR/gotcha_server" "$SRC_DIR/requirements.txt" "$APP_DIR/server/"
cp -r "$SRC_DIR/tools" "$APP_DIR/server/" 2>/dev/null || true
[[ -f "$SRC_DIR/README.md" ]] && cp "$SRC_DIR/README.md" "$APP_DIR/server/"
chown -R root:root "$APP_DIR/server"

echo "==> virtualenv"
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet fastapi uvicorn python-multipart

echo "==> secrets"
if [[ ! -f "$ETC_DIR/gotcha.env" ]]; then
  ADMIN_PW="${GOTCHA_ADMIN_PASSWORD:-$(head -c 9 /dev/urandom | base64 | tr -d '/+=')}"
  cat >"$ETC_DIR/gotcha.env" <<EOF
# Gotcha backend environment. Read by systemd (EnvironmentFile).
GOTCHA_PORT=$PORT
GOTCHA_ADMIN_PASSWORD=$ADMIN_PW
EOF
  chown root:gotcha "$ETC_DIR/gotcha.env"
  chmod 0640 "$ETC_DIR/gotcha.env"
  echo "    admin password: $ADMIN_PW   (stored in $ETC_DIR/gotcha.env)"
else
  echo "    keeping existing $ETC_DIR/gotcha.env"
fi

echo "==> systemd unit"
cp "$SRC_DIR/deploy/gotcha.service" "$UNIT"
systemctl daemon-reload
systemctl enable gotcha.service >/dev/null
systemctl restart gotcha.service

sleep 2
systemctl --no-pager --lines=0 status gotcha.service || true
echo
echo "==> health"
curl -fsS "http://127.0.0.1:$PORT/healthz" && echo
echo "Done. Admin console: http://<this-host>:$PORT/admin"
echo "Undo everything with: sudo server/deploy/uninstall.sh"
