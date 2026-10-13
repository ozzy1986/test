"""Синхронизация и кеш ответа.

GET обслуживается из готовых байтов в памяти. Источник перечитывается не чаще раза в SYNC_TTL и только
одним потоком: сколько бы запросов к нам ни пришло, к источнику уходит не больше одного.
Если источник или база недоступны — отдаём последний удачный результат.
"""
import json
import logging
import threading
import time

from . import config, source, store
from .dedupe import Client, Stats, build, to_payload

log = logging.getLogger("app.sync")


class Unavailable(Exception):
    """Нет ни одного удачного результата: источник недоступен с момента старта."""


class SyncService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._body: bytes | None = None
        self._stats: Stats | None = None
        self._sha: str | None = None
        self._checked_at = 0.0       # monotonic последней успешной сверки с источником
        self._next_attempt = 0.0     # monotonic, раньше которого не ходим в источник
        self.last_error: str | None = None

    # --- публичное ---

    def startup(self) -> None:
        if store.enabled():
            try:
                store.init_schema()
                saved = store.load()
                if saved:
                    self._publish(*saved)
                    log.info("loaded saved result: %s", saved[1])
            except Exception:
                log.exception("database unavailable at startup; working from memory")
        self.refresh(force=True)

    def body(self) -> bytes:
        if time.monotonic() >= self._checked_at + config.SYNC_TTL:
            self.refresh()
        if self._body is None:
            raise Unavailable(self.last_error or "no data yet")
        return self._body

    def refresh(self, force: bool = False) -> bool:
        """Сверка с источником. → True, если результат изменился. Не бросает исключений."""
        if not self._due(force):
            return False
        # Уже синхронизирует другой поток: если есть что отдать — не ждём его.
        if not self._lock.acquire(blocking=self._body is None):
            return False
        try:
            # Пока ждали блокировку, синхронизацию мог выполнить другой поток.
            return self._sync() if self._due(force) else False
        finally:
            self._lock.release()

    def _due(self, force: bool) -> bool:
        now = time.monotonic()
        if now < self._next_attempt:
            return False
        return force or now >= self._checked_at + config.SYNC_TTL

    def force_sync(self) -> dict:
        changed = self.refresh(force=True)
        return {"ok": self.last_error is None, "changed": changed,
                "stats": self._stats.to_json() if self._stats else None}

    def health(self) -> dict:
        return {"status": "ok", "has_data": self._body is not None,
                "last_error": self.last_error,
                "seconds_since_sync": round(time.monotonic() - self._checked_at) if self._checked_at else None}

    # --- внутреннее ---

    def _sync(self) -> bool:
        now = time.monotonic()
        self._next_attempt = now + config.SYNC_COOLDOWN
        try:
            orders, sha = source.fetch()
            clients, stats = build(orders)
        except Exception as e:
            self.last_error = f"source: {e}"
            self._next_attempt = now + config.SYNC_RETRY_AFTER
            log.warning("sync failed: %s", self.last_error)
            return False

        self._checked_at = now
        self.last_error = None
        if sha == self._sha:
            return False  # источник не изменился — ни памяти, ни базы не трогаем
        if store.enabled():
            try:
                store.save(clients, stats, sha)
            except Exception as e:
                # Ответ всё равно корректен — отдаём его из памяти, сохраним в следующий раз.
                self.last_error = f"database: {e.__class__.__name__}"
                log.exception("failed to save result")
                sha = None
        self._publish(clients, stats, sha)
        log.info("synced: %s", stats)
        return True

    def _publish(self, clients: list[Client], stats: Stats, sha: str | None) -> None:
        payload = to_payload(clients, stats)
        self._body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._stats = stats
        self._sha = sha
