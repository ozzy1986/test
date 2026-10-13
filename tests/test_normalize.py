from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.normalize import amount_to_json, clean_text, normalize_phone, parse_amount, parse_timestamp


@pytest.mark.parametrize("raw", [
    "+7 999 123-45-67", "8 (999) 123 45 67", "79991234567", "+79991234567", "8-999-123-45-67",
    "+7-999-123-45-67", " 8 999 1234567 ", "9991234567", "(999) 123-45-67", 79991234567, 89991234567,
    "+７ ９９９ １２３ ４５ ６７",            # полноширинные цифры
    "тел.: +7 999 123-45-67",
])
def test_phone_valid(raw):
    assert normalize_phone(raw) == "+79991234567"


@pytest.mark.parametrize("raw", [
    "", "   ", "123", "+7 999", "не указан", None, True, False, 12.5, [], {}, "+1 202 555 0100 1",
    "12025550100",                          # 11 цифр, но не российский код
    "+7 999 123-45-67 доб. 12",             # лишние цифры
    "+7 999 123-45-67, +7 916 000-00-01",   # два номера
    "+44 20 7946 0958 12", "7" * 12, "9" * 1000,
    "٩٩٩١٢٣٤٥٦٧",                           # арабские цифры: не ASCII — не угадываем
])
def test_phone_invalid(raw):
    assert normalize_phone(raw) is None


@pytest.mark.parametrize("raw, expected", [
    (5000, Decimal(5000)), (0, Decimal(0)), (99.9, Decimal("99.9")), ("5000", Decimal(5000)),
    ("5 000", Decimal(5000)), ("5 000", Decimal(5000)), ("1,500", Decimal(1500)),
    ("1,500.50", Decimal("1500.50")), ("99,9", Decimal("99.9")), (" 300 ₽", Decimal(300)),
    ("-100", Decimal(-100)),
])
def test_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", [
    None, True, "", "abc", "1e3", float("nan"), float("inf"), "NaN", "Infinity", [], {}, 10 ** 40, "5..0",
])
def test_amount_invalid(raw):
    assert parse_amount(raw) is None


def test_amount_to_json():
    assert amount_to_json(Decimal("5000.00")) == 5000 and isinstance(amount_to_json(Decimal("5000.00")), int)
    assert amount_to_json(Decimal("99.9")) == 99.9
    assert amount_to_json(None) is None


UTC = timezone.utc


@pytest.mark.parametrize("raw, expected", [
    ("2026-10-01T10:00:00Z", datetime(2026, 10, 1, 10, tzinfo=UTC)),
    ("2026-10-01T13:00:00+03:00", datetime(2026, 10, 1, 10, tzinfo=UTC)),
    ("2026-10-01 10:00:00", datetime(2026, 10, 1, 10, tzinfo=UTC)),
    ("2026-10-01", datetime(2026, 10, 1, tzinfo=UTC)),
    ("01.10.2026 10:00", datetime(2026, 10, 1, 10, tzinfo=UTC)),
    (1790848800, datetime(2026, 10, 1, 10, tzinfo=UTC)),
    (1790848800000, datetime(2026, 10, 1, 10, tzinfo=UTC)),
    ("1790848800", datetime(2026, 10, 1, 10, tzinfo=UTC)),
])
def test_timestamp(raw, expected):
    assert parse_timestamp(raw) == expected


@pytest.mark.parametrize("raw", [None, True, "", "вчера", "2026-13-45", "32.01.2026", 10 ** 30, float("nan"), []])
def test_timestamp_invalid(raw):
    assert parse_timestamp(raw) is None


def test_clean_text():
    assert clean_text("  Иван\x00 Петров\n ") == "Иван Петров"
    assert clean_text("bad\ud800surrogate") == "badsurrogate"
    assert clean_text(None) == "" and clean_text({"a": 1}) == "" and clean_text(42) == "42"
    assert len(clean_text("x" * 100_000)) == 1000
