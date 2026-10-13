"""Хранение результата в Postgres. Синхронизация — полная замена в одной транзакции, поэтому идемпотентна."""
from datetime import datetime, timezone

import psycopg

from . import config
from .dedupe import Client, Stats

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    phone       text PRIMARY KEY,           -- уникальность клиента гарантирует сама база
    name        text NOT NULL,
    email       text NOT NULL,
    amount      numeric,
    created_at  timestamptz,
    source_id   text NOT NULL,
    position    integer NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
    id                 smallint PRIMARY KEY CHECK (id = 1),
    received           integer NOT NULL,
    unique_clients     integer NOT NULL,
    duplicates_merged  integer NOT NULL,
    invalid_dropped    integer NOT NULL,
    source_sha256      text NOT NULL,
    synced_at          timestamptz NOT NULL
);
"""
_LOCK_KEY = 812_001  # pg_advisory_xact_lock: параллельные синхронизации идут по очереди


def enabled() -> bool:
    return bool(config.DATABASE_URL)


def _connect():
    return psycopg.connect(config.DATABASE_URL, connect_timeout=5, autocommit=False)


def init_schema() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)


def save(clients: list[Client], stats: Stats, source_sha256: str) -> None:
    with _connect() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
        conn.execute("DELETE FROM clients")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO clients (phone, name, email, amount, created_at, source_id, position)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(c.phone, c.name, c.email, c.amount, c.created_at, c.source_id, c.position) for c in clients],
            )
        conn.execute(
            "INSERT INTO sync_state (id, received, unique_clients, duplicates_merged, invalid_dropped,"
            " source_sha256, synced_at) VALUES (1, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET received = EXCLUDED.received,"
            " unique_clients = EXCLUDED.unique_clients, duplicates_merged = EXCLUDED.duplicates_merged,"
            " invalid_dropped = EXCLUDED.invalid_dropped, source_sha256 = EXCLUDED.source_sha256,"
            " synced_at = EXCLUDED.synced_at",
            (stats.received, stats.unique, stats.duplicates_merged, stats.invalid_dropped,
             source_sha256, datetime.now(timezone.utc)),
        )


def load() -> tuple[list[Client], Stats, str] | None:
    """Последний сохранённый результат или None, если синхронизаций ещё не было."""
    with _connect() as conn:
        state = conn.execute(
            "SELECT received, unique_clients, duplicates_merged, invalid_dropped, source_sha256"
            " FROM sync_state WHERE id = 1").fetchone()
        if state is None:
            return None
        rows = conn.execute(
            "SELECT name, phone, email, amount, created_at, source_id, position"
            " FROM clients ORDER BY position").fetchall()
    clients = [Client(*row) for row in rows]
    return clients, Stats(*state[:4]), state[4]
