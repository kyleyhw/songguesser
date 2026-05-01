"""Integration tests for the HTTP layer using FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from songguesser.server import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SONGGUESSER_ENABLE_SYNTHETIC", "1")
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_index_returns_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>songguesser</title>" in r.text


def test_synthetic_room_creates_and_meta_returns(client: TestClient) -> None:
    r = client.post("/api/rooms/synthetic")
    assert r.status_code == 200
    code = r.json()["code"]
    assert len(code) == 6 and code == code.upper()

    meta = client.get(f"/api/rooms/{code}")
    assert meta.status_code == 200
    body = meta.json()
    assert body["code"] == code
    assert body["phase"] == "lobby"
    assert body["max_rounds"] == 3


def test_synthetic_room_disabled_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONGGUESSER_ENABLE_SYNTHETIC", raising=False)
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/api/rooms/synthetic")
        assert r.status_code == 404


def test_unknown_room_returns_404(client: TestClient) -> None:
    r = client.get("/api/rooms/ZZZZZZ")
    assert r.status_code == 404


def test_static_silence_mp3_is_served(client: TestClient) -> None:
    r = client.get("/static/silence.mp3")
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xfb"


def test_create_room_with_invalid_url_rejects(client: TestClient) -> None:
    r = client.post("/api/rooms", json={"playlist_url": "not a url"})
    # 400 if our parser rejects it; 422 if pydantic validation rejects first.
    assert r.status_code in (400, 422)
