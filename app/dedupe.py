"""Чистая логика: сырые заявки → уникальные клиенты + статистика. Без сети и базы."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .normalize import amount_to_json, clean_text, normalize_phone, parse_amount, parse_timestamp


@dataclass(frozen=True)
class Client:
    name: str
    phone: str
    email: str
    amount: Decimal | None
    created_at: datetime | None
    source_id: str          # id заявки-победителя (для отладки, наружу не отдаётся)
    position: int           # место первой заявки с этим телефоном — задаёт порядок в ответе

    def to_json(self) -> dict:
        return {"name": self.name, "phone": self.phone, "email": self.email,
                "amount": amount_to_json(self.amount)}


@dataclass(frozen=True)
class Stats:
    received: int
    unique: int
    duplicates_merged: int
    invalid_dropped: int

    def to_json(self) -> dict:
        return {"received": self.received, "unique": self.unique,
                "duplicates_merged": self.duplicates_merged, "invalid_dropped": self.invalid_dropped}


def _rank(amount: Decimal | None, created_at: datetime | None, index: int) -> tuple:
    """Чем больше ключ, тем предпочтительнее запись: max amount → более поздний created_at → позже в выгрузке.

    Нераспознанные amount/created_at проигрывают любым распознанным.
    """
    return (amount is not None, amount or Decimal(0),
            created_at is not None, created_at.timestamp() if created_at else 0.0,
            index)


def build(orders: list) -> tuple[list[Client], Stats]:
    best: dict[str, tuple[tuple, Client]] = {}
    first_seen: dict[str, int] = {}
    invalid = 0

    for index, order in enumerate(orders):
        phone = normalize_phone(order.get("phone")) if isinstance(order, dict) else None
        if phone is None:
            invalid += 1
            continue
        first_seen.setdefault(phone, index)
        amount = parse_amount(order.get("amount"))
        created_at = parse_timestamp(order.get("created_at"))
        rank = _rank(amount, created_at, index)
        current = best.get(phone)
        if current is None or rank > current[0]:
            best[phone] = (rank, Client(
                name=clean_text(order.get("name")),
                phone=phone,
                email=clean_text(order.get("email")),
                amount=amount,
                created_at=created_at,
                source_id=clean_text(order.get("id")),
                position=first_seen[phone],
            ))

    clients = sorted((c for _, c in best.values()), key=lambda c: c.position)
    valid = len(orders) - invalid
    stats = Stats(received=len(orders), unique=len(clients),
                  duplicates_merged=valid - len(clients), invalid_dropped=invalid)
    return clients, stats


def to_payload(clients: list[Client], stats: Stats) -> dict:
    return {"clients": [c.to_json() for c in clients], "stats": stats.to_json()}
