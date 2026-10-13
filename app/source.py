"""Загрузка сырых заявок из источника с защитой от медленных, огромных и битых ответов."""
import hashlib
import json
import urllib.error
import urllib.request

from . import config


class SourceError(Exception):
    """Источник недоступен или прислал не то — результат прошлой синхронизации не трогаем."""


def _safe_int(s: str):
    # Число из тысяч цифр обычный json.loads разбирает с ValueError и роняет весь ответ.
    return int(s) if len(s) <= 30 else None


def _reject_constant(_name: str):
    # NaN / Infinity / -Infinity — не JSON; превращаем в None, а не в float('nan').
    return None


def parse(body: bytes) -> list:
    try:
        data = json.loads(body.decode("utf-8-sig"), parse_int=_safe_int, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise SourceError(f"invalid JSON: {e.__class__.__name__}") from None
    # Ожидаем массив; терпим обёртку вида {"orders": [...]} / {"data": [...]}.
    if isinstance(data, dict):
        for key in ("orders", "data", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise SourceError(f"expected JSON array, got {type(data).__name__}")
    if len(data) > config.SOURCE_MAX_RECORDS:
        raise SourceError(f"too many records: {len(data)}")
    return data


def fetch() -> tuple[list, str]:
    """→ (заявки, sha256 тела ответа)."""
    req = urllib.request.Request(config.SOURCE_URL, headers={
        "Accept": "application/json",
        "User-Agent": "test.ozzy1986.com-sync/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=config.SOURCE_TIMEOUT) as resp:
            if resp.status != 200:
                raise SourceError(f"HTTP {resp.status}")
            body = resp.read(config.SOURCE_MAX_BYTES + 1)
    except SourceError:
        raise
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code}") from None
    except Exception as e:  # сеть, TLS, таймаут, обрыв
        raise SourceError(f"{e.__class__.__name__}: {e}") from None
    if len(body) > config.SOURCE_MAX_BYTES:
        raise SourceError("response too large")
    return parse(body), hashlib.sha256(body).hexdigest()
