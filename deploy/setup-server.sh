#!/usr/bin/env bash
# Серверная конфигурация (идемпотентно): права, оба vhost'а, сертификат, systemd-юнит (если есть start.sh).
# Вызывается deploy.sh после переключения релиза; вручную от root:
#   bash /var/www/test.ozzy1986.com/current/deploy/setup-server.sh
set -euo pipefail
ROOT=/var/www/test.ozzy1986.com
CUR=$ROOT/current
DOMAIN=test.ozzy1986.com

[ -L "$CUR" ] || { echo "нет $CUR — сначала deploy/deploy.sh"; exit 1; }

# Права: Apache читает current/public, но не shared/ с секретами.
mkdir -p "$ROOT/acme" "$ROOT/backups" "$ROOT/shared"
chmod 755 "$ROOT" "$ROOT/releases"
chown testapp:testapp "$ROOT/shared" "$ROOT/backups"
chmod 700 "$ROOT/shared" "$ROOT/backups"
find "$ROOT/shared" -maxdepth 1 -name '.env*' -exec chmod 600 {} +

enable_site() {  # a2ensite отказывается работать, если в sites-enabled лежит обычный файл, а не ссылка
  local enabled="/etc/apache2/sites-enabled/$1.conf"
  if [ -e "$enabled" ] && [ ! -L "$enabled" ]; then rm -f "$enabled"; fi
  a2ensite -q "$1"
}

echo '--- apache: http vhost ---'
install -m 644 "$CUR/deploy/apache-$DOMAIN.conf" "/etc/apache2/sites-available/$DOMAIN.conf"
enable_site "$DOMAIN"

echo '--- certificate ---'
if ! certbot certificates 2>/dev/null | grep -q "Certificate Name: $DOMAIN"; then
  apache2ctl configtest && systemctl reload apache2
  certbot certonly --webroot -w "$ROOT/acme" -d "$DOMAIN" --non-interactive --agree-tos
else
  echo 'сертификат уже есть'
fi

echo '--- apache: https vhost ---'
install -m 644 "$CUR/deploy/apache-$DOMAIN-le-ssl.conf" "/etc/apache2/sites-available/$DOMAIN-le-ssl.conf"
enable_site "$DOMAIN-le-ssl"
apache2ctl configtest
systemctl reload apache2

if [ -f "$CUR/deploy/start.sh" ]; then
  echo '--- systemd ---'
  if ! cmp -s "$CUR/deploy/test.service" /etc/systemd/system/test.service; then
    install -m 644 "$CUR/deploy/test.service" /etc/systemd/system/test.service
    systemctl daemon-reload
  fi
  systemctl enable test.service >/dev/null 2>&1 || true
fi
echo 'setup done'
