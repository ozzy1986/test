"""Настройки из переменных окружения (на сервере — shared/.env через systemd)."""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Адрес источника задан только здесь — запросы пользователей не влияют на то, куда ходит сервис.
SOURCE_URL = os.environ.get("SOURCE_URL", "https://test.ooobs.ru/api/orders")
SOURCE_TIMEOUT = _int("SOURCE_TIMEOUT", 10)            # сек на запрос
SOURCE_MAX_BYTES = _int("SOURCE_MAX_BYTES", 5_000_000)  # больше — считаем ответ мусором
SOURCE_MAX_RECORDS = _int("SOURCE_MAX_RECORDS", 100_000)

# GET отдаётся из памяти; источник перечитывается не чаще раза в SYNC_TTL секунд.
SYNC_TTL = _int("SYNC_TTL", 60)
# Принудительная синхронизация (/api/sync) — не чаще раза в SYNC_COOLDOWN секунд.
SYNC_COOLDOWN = _int("SYNC_COOLDOWN", 5)
# После неудачной попытки — пауза перед следующей, чтобы не долбить лежащий источник.
SYNC_RETRY_AFTER = _int("SYNC_RETRY_AFTER", 15)

# Пусто — работаем без базы (только память): удобно для тестов и локального запуска.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
