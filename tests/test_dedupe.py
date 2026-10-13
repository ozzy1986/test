import json
import random
from pathlib import Path

from app.dedupe import build, to_payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "orders.json").read_text("utf-8"))

# Эталон для реальной выгрузки источника (снята 2026-10-13), выведен вручную по правилам ТЗ.
EXPECTED = {
    "clients": [
        {"name": "Иван П.", "phone": "+79991234567", "email": "", "amount": 5000},             # max amount
        {"name": "Мария С.", "phone": "+79160000001", "email": "maria@example.com", "amount": 200},  # равные → позже
        {"name": "Олег Кузнецов", "phone": "+79031112233", "email": "", "amount": 7500},
        {"name": "Анна В.", "phone": "+79219998877", "email": "", "amount": 1500},             # 0 < 1500
        {"name": "Павел Орлов", "phone": "+79005551212", "email": "pavel@example.com", "amount": 300},  # 10 цифр
        {"name": "Елена Морозова", "phone": "+79261234567", "email": "elena@example.com", "amount": 9000},
        {"name": "Сергей Зайцев", "phone": "+79991110000", "email": "sergey@example.com", "amount": 450},
        {"name": "Дмитрий Лебедев", "phone": "+79164455667", "email": "dmitry@example.com", "amount": 12000},
    ],
    "stats": {"received": 17, "unique": 8, "duplicates_merged": 5, "invalid_dropped": 4},
}


def test_real_source_data():
    assert to_payload(*build(FIXTURE)) == EXPECTED


def test_idempotent_and_order_independent():
    first = to_payload(*build(FIXTURE))
    assert to_payload(*build(FIXTURE)) == first
    # Победитель в группе не зависит от порядка заявок (порядок самих клиентов — зависит, это ок).
    shuffled = FIXTURE[:]
    random.Random(1).shuffle(shuffled)
    by_phone = lambda p: {c["phone"]: c for c in p["clients"]}
    result = to_payload(*build(shuffled))
    assert by_phone(result) == by_phone(first)
    assert result["stats"] == first["stats"]


def test_stats_invariant():
    clients, s = build(FIXTURE)
    assert s.received == s.unique + s.duplicates_merged + s.invalid_dropped


def test_garbage_records_do_not_crash():
    orders = [
        None, 42, "str", [], {}, {"phone": None},
        {"id": {"x": 1}, "name": ["a"], "phone": "+7 999 000-00-01", "email": None, "amount": "abc",
         "created_at": "never"},
        {"id": 2, "name": "B", "phone": "89990000001", "email": "b@x", "amount": "100", "created_at": None},
    ]
    payload = to_payload(*build(orders))
    assert payload["stats"] == {"received": 8, "unique": 1, "duplicates_merged": 1, "invalid_dropped": 6}
    # распознанная сумма бьёт нераспознанную
    assert payload["clients"] == [{"name": "B", "phone": "+79990000001", "email": "b@x", "amount": 100}]


def test_amount_compared_as_number_not_string():
    orders = [
        {"phone": "79990000001", "amount": "900", "created_at": "2026-10-01T00:00:00Z", "name": "small"},
        {"phone": "79990000001", "amount": "5000", "created_at": "2026-09-01T00:00:00Z", "name": "big"},
    ]
    assert to_payload(*build(orders))["clients"][0]["name"] == "big"


def test_dates_compared_as_instants_not_strings():
    # 12:00+05:00 = 07:00Z — раньше, чем 10:00Z, хотя строкой «больше»
    orders = [
        {"phone": "79990000001", "amount": 1, "created_at": "2026-10-01T10:00:00Z", "name": "later"},
        {"phone": "79990000001", "amount": 1, "created_at": "2026-10-01T12:00:00+05:00", "name": "earlier"},
    ]
    assert to_payload(*build(orders))["clients"][0]["name"] == "later"


def test_full_tie_is_deterministic():
    orders = [
        {"phone": "79990000001", "amount": 1, "created_at": "2026-10-01T10:00:00Z", "name": "first"},
        {"phone": "79990000001", "amount": 1, "created_at": "2026-10-01T10:00:00Z", "name": "second"},
    ]
    assert to_payload(*build(orders))["clients"][0]["name"] == "second"


def test_empty():
    assert to_payload(*build([])) == {
        "clients": [], "stats": {"received": 0, "unique": 0, "duplicates_merged": 0, "invalid_dropped": 0}}
