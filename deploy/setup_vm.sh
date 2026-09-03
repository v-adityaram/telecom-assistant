#!/usr/bin/env bash
# Idempotent install / redeploy for the Azure VM. Run ON the VM, from the
# repo checkout, as root:
#
#   cd ~/telecom-assistant && git pull && sudo ./deploy/setup_vm.sh
#
# Safe to re-run: every step checks before it changes anything.
# Expects a .env already in the checkout (copied over separately — never
# committed). The app runs as the non-root user who invoked sudo.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-azureuser}"
PUBLIC_IP="${PUBLIC_IP:-104.211.224.38}"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
[ -f "$APP_DIR/.env" ] || { echo "!! $APP_DIR/.env is missing — copy it over first (it is never committed)"; exit 1; }

echo "== packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx python3-venv openssl >/dev/null

echo "== python venv + dependencies (as $APP_USER)"
sudo -u "$APP_USER" bash -c "
  set -e
  cd '$APP_DIR'
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip install --quiet --no-cache-dir --upgrade pip
  .venv/bin/pip install --quiet --no-cache-dir -r requirements.txt
"
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "== self-signed TLS cert (browsers need https for microphone access)"
if [ ! -f /etc/ssl/certs/telecom-assistant.crt ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -subj "/CN=$PUBLIC_IP" -addext "subjectAltName=IP:$PUBLIC_IP" \
    -keyout /etc/ssl/private/telecom-assistant.key \
    -out /etc/ssl/certs/telecom-assistant.crt 2>/dev/null
  chmod 600 /etc/ssl/private/telecom-assistant.key
fi

echo "== nginx"
install -m 644 "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/telecom-assistant
ln -sf /etc/nginx/sites-available/telecom-assistant /etc/nginx/sites-enabled/telecom-assistant
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "== systemd service"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" \
  "$APP_DIR/deploy/telecom-assistant.service" > /etc/systemd/system/telecom-assistant.service
systemctl daemon-reload
systemctl enable telecom-assistant >/dev/null 2>&1
systemctl restart telecom-assistant

echo "== verify"
for i in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 1
done
systemctl --no-pager --lines=3 status telecom-assistant || true
echo -n "app:   "; curl -fsS  http://127.0.0.1:8000/health; echo
echo -n "nginx: "; curl -fsSk https://127.0.0.1/health; echo
echo "done — open https://$PUBLIC_IP/ (accept the self-signed cert warning once)"
