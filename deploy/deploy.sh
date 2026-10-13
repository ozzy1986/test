#!/usr/bin/env bash
# Релиз на VPS (запускать из Git Bash):
#   deploy/deploy.sh             — [build.sh локально] → загрузка → [remote-build.sh на сервере]
#                                  → переключение current → setup-server → рестарт → healthcheck
#   deploy/deploy.sh --rollback  — вернуть релиз, предшествующий текущему
#   HEALTH_PATH=/api/health deploy/deploy.sh — свой путь для healthcheck (по умолчанию /)
#
# Хуки необязательны, кладутся в deploy/:
#   build.sh        — локальная сборка (npm run build и т.п.) до загрузки
#   remote-build.sh — на сервере от testapp в папке релиза, с переменными shared/.env
#                     (venv/pip, composer install, миграции)
#   start.sh        — запуск бэкенда на 127.0.0.1:$PORT (8120); при наличии ставится systemd test.service
#
# Релизы в releases/<метка>, боевой — симлинк current; держим 5 последних.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG=deploy/.env
[ -f "$CONFIG" ] && [ -z "${DEPLOY_HOST:-}" ] && . "$CONFIG"
HOST=${DEPLOY_HOST:?нет DEPLOY_HOST: скопируйте deploy/.env.example в deploy/.env}
ROOT=/var/www/test.ozzy1986.com
URL=https://test.ozzy1986.com
HEALTH=${HEALTH_PATH:-/}

switch_to() {  # $1 — абсолютный путь релиза
  ssh "$HOST" "ln -sfn $1 $ROOT/current.tmp && mv -Tf $ROOT/current.tmp $ROOT/current \
    && bash $ROOT/current/deploy/setup-server.sh >/dev/null \
    && if [ -f $ROOT/current/deploy/start.sh ]; then systemctl restart test; fi"
}

healthcheck() {
  for _ in $(seq 1 15); do
    if curl -sf --max-time 5 -o /dev/null "$URL$HEALTH"; then echo healthy; return 0; fi
    sleep 1
  done
  echo UNHEALTHY
  ssh "$HOST" "systemctl is-enabled test >/dev/null 2>&1 && journalctl -u test -n 30 --no-pager; \
    tail -n 20 /var/log/apache2/test.ozzy1986.com_error.log"
  return 1
}

if [ "${1:-}" = "--rollback" ]; then
  CURRENT=$(ssh "$HOST" "readlink $ROOT/current")
  PREV=$(ssh "$HOST" "ls -1d $ROOT/releases/* | sort | awk -v cur='$CURRENT' '\$0 < cur' | tail -1")
  [ -n "$PREV" ] || { echo "нет релиза старше $CURRENT"; exit 1; }
  echo "--- rollback $CURRENT → $PREV ---"
  if switch_to "$PREV" && healthcheck; then echo "rolled back to $PREV"; else exit 1; fi
  exit 0
fi

if [ -f deploy/build.sh ]; then
  echo '--- local build ---'
  bash deploy/build.sh
fi

TS=$(date +%Y%m%d-%H%M%S)
REL=$ROOT/releases/$TS
echo "--- upload release $TS ---"
tar czf - \
  --exclude=./.git --exclude=node_modules --exclude=.venv --exclude=venv --exclude=./vendor \
  --exclude=.env --exclude='.env.*' --exclude=./deploy/.env --exclude='./deploy/.env.*' \
  --exclude=__pycache__ --exclude=.pytest_cache --exclude='*.log' --exclude=.idea --exclude=.vscode \
  . | ssh "$HOST" "mkdir -p $REL && tar xzf - -C $REL && chown -R testapp:testapp $REL && chmod -R o+rX $REL"

if [ -f deploy/remote-build.sh ]; then
  echo '--- remote build ---'
  ssh "$HOST" "sudo -u testapp bash -c 'set -a; . $ROOT/shared/.env; set +a; cd $REL && bash deploy/remote-build.sh'"
fi

PREV=$(ssh "$HOST" "readlink $ROOT/current 2>/dev/null || true")
echo "--- switch current → $TS (prev: ${PREV:-none}) ---"
if switch_to "$REL" && healthcheck; then
  echo "deployed $TS → $URL"
  ssh "$HOST" "ls -1d $ROOT/releases/* | sort | head -n -5 | xargs -r rm -rf"
else
  if [ -n "$PREV" ]; then
    echo "!!! healthcheck failed — rolling back to $PREV"
    switch_to "$PREV" && healthcheck
  fi
  exit 1
fi
