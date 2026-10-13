import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main, source
from app.service import SyncService

FIXTURE = (Path(__file__).parent / "fixtures" / "orders.json").read_bytes()


@pytest.fixture
def upstream(monkeypatch):
    """Подменяет сеть: state['body'] — ответ источника, state['calls'] — сколько раз в него сходили."""
    state = {"body": FIXTURE, "fail": False, "calls": 0}

    def fake_fetch():
        state["calls"] += 1
        if state["fail"]:
            raise source.SourceError("down")
        import hashlib
        return source.parse(state["body"]), hashlib.sha256(state["body"]).hexdigest()

    monkeypatch.setattr(source, "fetch", fake_fetch)
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "SYNC_COOLDOWN", 0)
    monkeypatch.setattr(config, "SYNC_RETRY_AFTER", 0)
    monkeypatch.setattr(main, "service", SyncService())
    return state


@pytest.fixture
def client(upstream):
    with TestClient(main.app) as c:
        yield c


def test_clients_schema(client):
    for path in ("/", "/api/clients"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/json; charset=utf-8"
        assert r.headers["access-control-allow-origin"] == "*"
        assert "Иван" in r.content.decode("utf-8")  # кириллица без \u-экранирования
        data = r.json()
        assert set(data) == {"clients", "stats"}
        assert set(data["stats"]) == {"received", "unique", "duplicates_merged", "invalid_dropped"}
        assert all(set(c) == {"name", "phone", "email", "amount"} for c in data["clients"])
        assert data["stats"] == {"received": 17, "unique": 8, "duplicates_merged": 5, "invalid_dropped": 4}


def test_repeated_sync_is_idempotent(client):
    before = client.get("/api/clients").content
    for _ in range(3):
        r = client.post("/api/sync")
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["changed"] is False
        assert client.get("/api/sync").status_code == 200
    assert client.get("/api/clients").content == before


def test_get_does_not_hammer_source(client, upstream):
    calls = upstream["calls"]
    for _ in range(50):
        client.get("/api/clients")
    assert upstream["calls"] == calls  # в пределах SYNC_TTL — только из памяти


def test_source_down_serves_last_good(client, upstream):
    before = client.get("/api/clients").content
    upstream["fail"] = True
    r = client.post("/api/sync")
    assert r.json()["ok"] is False
    assert client.get("/api/clients").content == before
    assert client.get("/api/health").json()["last_error"] == "source: down"


@pytest.mark.parametrize("bad", [b"", b"not json", b"{}", b'{"a": 1}', b"null", b"[" * 100_000,
                                 b"\xff\xfe", b'"string"'],
                         ids=["empty", "text", "obj", "obj2", "null", "deep", "bytes", "str"])
def test_source_garbage_keeps_last_good(client, upstream, bad):
    before = client.get("/api/clients").content
    upstream["body"] = bad
    assert client.post("/api/sync").json()["ok"] is False
    assert client.get("/api/clients").content == before


def test_source_change_is_picked_up(client, upstream):
    upstream["body"] = json.dumps([{"name": "X", "phone": "89990000000", "email": "", "amount": 1,
                                    "created_at": "2026-10-01T00:00:00Z"}]).encode()
    r = client.post("/api/sync")
    assert r.json()["changed"] is True
    assert client.get("/api/clients").json()["clients"] == [
        {"name": "X", "phone": "+79990000000", "email": "", "amount": 1}]


def test_nan_and_huge_numbers_in_source(client, upstream):
    upstream["body"] = (b'[{"phone":"89990000000","amount":NaN},'
                        b'{"phone":"89990000000","amount":' + b"9" * 5000 + b'},'
                        b'{"phone":"89990000000","amount":Infinity,"name":"\\ud800\\u0000"}]')
    assert client.post("/api/sync").json()["ok"] is True
    data = client.get("/api/clients").json()
    assert data["stats"] == {"received": 3, "unique": 1, "duplicates_merged": 2, "invalid_dropped": 0}
    assert data["clients"][0]["amount"] is None


def test_cold_start_with_source_down(upstream):
    upstream["fail"] = True
    with TestClient(main.app) as c:
        r = c.get("/api/clients")
        assert r.status_code == 503 and r.json() == {"error": "source unavailable, no data yet"}
        upstream["fail"] = False
        assert c.get("/api/clients").status_code == 200


def test_unknown_paths_and_methods(client):
    assert client.get("/nope").status_code == 404
    assert client.get("/nope").json() == {"error": "Not Found"}
    assert client.delete("/api/clients").status_code == 405
    assert client.put("/api/sync").status_code == 405
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/clients?x=1&phone[]=2").status_code == 200
