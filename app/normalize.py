"""Разбор «грязных» полей заявки. Каждая функция принимает что угодно и никогда не бросает исключений."""
import math
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

_MAX_FIELD_LEN = 256          # телефон/сумма/дата длиннее — точно мусор
_MAX_TEXT_LEN = 1000          # имя/email обрезаем до этой длины
_MAX_AMOUNT = Decimal("1e15")
_NON_DIGITS = re.compile(r"[^0-9]")
_AMOUNT_SPACES = re.compile(r"[\s_'   ]")
_THOUSANDS_COMMA = re.compile(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?")
_PLAIN_NUMBER = re.compile(r"[+-]?\d+([.,]\d+)?")
_RU_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def normalize_phone(value) -> str | None:
    """Телефон → '+7XXXXXXXXXX' или None, если к 11 цифрам не приводится.

    Берём все цифры: 11 цифр с первой 7/8 — российский номер; 10 цифр — номер без кода страны.
    Всё остальное (короче, длиннее, 11 цифр с другим кодом, не строка) — невалидно.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or len(value) > _MAX_FIELD_LEN:
        return None
    # NFKC превращает «широкие» и прочие юникод-цифры (９) в ASCII.
    digits = _NON_DIGITS.sub("", unicodedata.normalize("NFKC", value))
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return None


def parse_amount(value) -> Decimal | None:
    """Сумма → Decimal или None. Понимает числа и строки вида '5000', '5 000', '1,500.50', '99,9'."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None
        result = Decimal(repr(value))
    elif isinstance(value, Decimal):
        result = value
    elif isinstance(value, str) and len(value) <= _MAX_FIELD_LEN:
        s = _AMOUNT_SPACES.sub("", unicodedata.normalize("NFKC", value))
        s = s.removesuffix("₽").removesuffix("руб.").removesuffix("руб")
        if _THOUSANDS_COMMA.fullmatch(s):
            s = s.replace(",", "")
        elif _PLAIN_NUMBER.fullmatch(s):
            s = s.replace(",", ".")
        else:
            return None
        try:
            result = Decimal(s)
        except InvalidOperation:
            return None
    else:
        return None
    if not result.is_finite() or abs(result) >= _MAX_AMOUNT:
        return None
    return result


def parse_timestamp(value) -> datetime | None:
    """Дата → aware datetime (UTC) или None. ISO 8601 (с Z/смещением/без), epoch сек/мс, ДД.ММ.ГГГГ [ЧЧ:ММ[:СС]]."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return _from_epoch(value)
        if not isinstance(value, str) or len(value) > _MAX_FIELD_LEN:
            return None
        s = value.strip()
        if not s:
            return None
        if s.isdigit():
            return _from_epoch(int(s))
        m = _RU_DATE.fullmatch(s)
        if m:
            d, mo, y, h, mi, sec = (int(x) if x else 0 for x in m.groups())
            return datetime(y, mo, d, h, mi, sec, tzinfo=timezone.utc)
        if s.endswith(("z", "Z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _from_epoch(n) -> datetime | None:
    if isinstance(n, float) and not math.isfinite(n):
        return None
    if abs(n) > 1e11:  # миллисекунды
        n = n / 1000
    return datetime.fromtimestamp(n, tz=timezone.utc)


def clean_text(value) -> str:
    """Имя/email: строка как есть, но без краевых пробелов и мусорных символов; не строка → ''.

    Выкидываем управляющие (Cc: NUL Postgres не принимает) и одиночные суррогаты (Cs: "\\ud800" валиден
    в JSON, но не кодируется в UTF-8 — уронил бы и вставку в базу, и отдачу ответа).
    """
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return ""
    value = "".join(ch for ch in value[:_MAX_TEXT_LEN * 4] if unicodedata.category(ch) not in ("Cc", "Cs"))
    return value.strip()[:_MAX_TEXT_LEN]


def amount_to_json(amount: Decimal | None):
    """Decimal → int, если целое (5000, а не 5000.0), иначе float."""
    if amount is None:
        return None
    if amount == amount.to_integral_value():
        return int(amount)
    return float(amount)
