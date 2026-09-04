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
DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx python3-venv certbot coturn >/dev/null

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

echo "== TURN relay (coturn) — fixes voice on networks that block outbound UDP entirely"
TURN_SHARED_SECRET="$(grep -E '^TURN_SHARED_SECRET=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
if [ -z "$TURN_SHARED_SECRET" ]; then
  echo "   TURN_SHARED_SECRET not set in .env — skipping, voice falls back to STUN-only"
  systemctl disable --now coturn >/dev/null 2>&1 || true
else
  # The app also needs to know its own domain to build turns: URLs — set
  # automatically here so it's never a second value to keep in sync by hand.
  if grep -qE '^TURN_DOMAIN=' "$APP_DIR/.env"; then
    sed -i "s|^TURN_DOMAIN=.*|TURN_DOMAIN=$PUBLIC_DOMAIN|" "$APP_DIR/.env"
  else
    echo "TURN_DOMAIN=$PUBLIC_DOMAIN" >> "$APP_DIR/.env"
  fi

  # coturn's default user can't read /etc/letsencrypt (root-only) — copying
  # into a dedicated, coturn-owned location sidesteps ACL wrangling. Kept
  # fresh on every renewal by the deploy-hook script below, not just here.
  install -d -m 755 /etc/turnserver-certs
  cp "/etc/letsencrypt/live/$PUBLIC_DOMAIN/fullchain.pem" "/etc/letsencrypt/live/$PUBLIC_DOMAIN/privkey.pem" /etc/turnserver-certs/
  chown turnserver:turnserver /etc/turnserver-certs/*.pem
  chmod 600 /etc/turnserver-certs/*.pem

  cat > /etc/turnserver.conf <<EOF
listening-port=3478
tls-listening-port=5349
listening-ip=0.0.0.0
external-ip=$PUBLIC_IP
realm=$PUBLIC_DOMAIN
use-auth-secret
static-auth-secret=$TURN_SHARED_SECRET
cert=/etc/turnserver-certs/fullchain.pem
pkey=/etc/turnserver-certs/privkey.pem
# Narrow range (40 ports = ~40 concurrent relayed calls, plenty for a POC)
# keeps the matching NSG rule small. Relay traffic to the real peer is VM-
# initiated outbound UDP — NSGs are stateful, so no inbound rule is needed
# for it, only for 5349 itself (the browser's inbound connection to us).
min-port=49160
max-port=49200
no-cli
no-tlsv1
no-tlsv1_1
fingerprint
EOF
  chmod 640 /etc/turnserver.conf
  chown root:turnserver /etc/turnserver.conf

  install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
  cat > /etc/letsencrypt/renewal-hooks/deploy/refresh-coturn.sh <<EOF
#!/usr/bin/env bash
set -e
cp "/etc/letsencrypt/live/$PUBLIC_DOMAIN/fullchain.pem" "/etc/letsencrypt/live/$PUBLIC_DOMAIN/privkey.pem" /etc/turnserver-certs/
chown turnserver:turnserver /etc/turnserver-certs/*.pem
chmod 600 /etc/turnserver-certs/*.pem
systemctl restart coturn
EOF
  chmod 755 /etc/letsencrypt/renewal-hooks/deploy/refresh-coturn.sh

  sed -i 's/^#\?TURNSERVER_ENABLED=.*/TURNSERVER_ENABLED=1/' /etc/default/coturn 2>/dev/null || echo "TURNSERVER_ENABLED=1" >> /etc/default/coturn
  systemctl enable --now coturn >/dev/null 2>&1
  systemctl restart coturn
  echo "   coturn active — remember to add an inbound NSG rule for TCP 5349 if not already present"
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
