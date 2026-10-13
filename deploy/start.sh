#!/usr/bin/env bash
# Запуск сервиса (ExecStart в test.service). Слушаем только localhost — наружу через Apache.
set -euo pipefail
cd "$(dirname "$0")/.."
exec venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port "${PORT:-8120}" --workers 1 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1 \
  --no-server-header --timeout-keep-alive 5 --limit-concurrency 200 \
  --log-level info
