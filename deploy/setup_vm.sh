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
# A sslip.io hostname resolves to the embedded IP with zero DNS setup —
# lets Let's Encrypt issue a real, browser-trusted certificate without
# owning a domain (public CAs never issue certs for a bare IP).
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-$(echo "$PUBLIC_IP" | tr '.' '-').sslip.io}"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
[ -f "$APP_DIR/.env" ] || { echo "!! $APP_DIR/.env is missing — copy it over first (it is never committed)"; exit 1; }

echo "== packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx python3-venv certbot >/dev/null

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

echo "== TLS certificate (Let's Encrypt, for $PUBLIC_DOMAIN)"
mkdir -p /var/www/certbot
if [ ! -f "/etc/letsencrypt/live/$PUBLIC_DOMAIN/fullchain.pem" ]; then
  # nginx can't start with the real site config yet — it points at a
  # certificate that doesn't exist until the ACME challenge below succeeds.
  # A minimal http-only bootstrap site serves just that challenge.
  cat > /etc/nginx/sites-available/telecom-assistant <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 200 'bootstrapping'; }
}
EOF
  ln -sf /etc/nginx/sites-available/telecom-assistant /etc/nginx/sites-enabled/telecom-assistant
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl restart nginx
  certbot certonly --webroot -w /var/www/certbot -d "$PUBLIC_DOMAIN" \
    --non-interactive --agree-tos --register-unsafely-without-email \
    --deploy-hook "systemctl reload nginx"
fi

echo "== nginx"
sed "s|__PUBLIC_DOMAIN__|$PUBLIC_DOMAIN|g" "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/telecom-assistant
chmod 644 /etc/nginx/sites-available/telecom-assistant
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
echo "done — open https://$PUBLIC_DOMAIN/ (trusted certificate, no browser warning)"
