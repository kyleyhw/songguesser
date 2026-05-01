"""WebSocket integration test: exercises the full lobby→play→guess→reveal
loop in-process via FastAPI's TestClient WebSocket support.

Two clients connect to a synthetic room. Client A is host. A starts the
game; both receive ``round_start``. A submits the correct guess for round
1 (matching the synthetic playlist). The server's "everyone solved"
short-circuit fires and the runner advances to round 2.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from songguesser.server import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SONGGUESSER_ENABLE_SYNTHETIC", "1")
    app = create_app()
    with TestClient(app) as c:
        yield c


def _drain_until(ws: Any, predicate, *, max_messages: int = 50) -> dict[str, Any]:
    """Receive JSON messages from a TestClient WebSocket until ``predicate``
    returns True. Returns the matching message. Raises ``TimeoutError`` after
    ``max_messages`` mismatched messages."""
    for _ in range(max_messages):
        raw = ws.receive_text()
        msg: dict[str, Any] = json.loads(raw)
        if predicate(msg):
            return msg
    raise TimeoutError("predicate never matched")


def test_lobby_and_round_flow(client: TestClient) -> None:
    """Two clients in one room; host starts; one client guesses correctly."""
    code = client.post("/api/rooms/synthetic?round_seconds=10&reveal_seconds=0.1").json()["code"]

    with client.websocket_connect(f"/ws/{code}?player_id=alice&name=Alice") as ws_a, \
         client.websocket_connect(f"/ws/{code}?player_id=bob&name=Bob") as ws_b:
        # Both clients receive a state envelope on join.
        state_a = _drain_until(ws_a, lambda m: m["type"] == "state")
        state_b = _drain_until(ws_b, lambda m: m["type"] == "state")
        assert state_a["room"]["phase"] == "lobby"
        assert state_b["room"]["phase"] in ("lobby",)
        # Alice (first player) is host.
        alice_in_state = next(p for p in state_b["room"]["players"] if p["id"] == "alice")
        assert alice_in_state["is_host"] is True

        # Host starts.
        ws_a.send_text(json.dumps({"type": "start"}))
        rs_a = _drain_until(ws_a, lambda m: m["type"] == "round_start")
        rs_b = _drain_until(ws_b, lambda m: m["type"] == "round_start")
        assert rs_a["round_index"] == 0
        assert rs_b["round_index"] == 0
        assert rs_a["audio_url"].endswith("silence.mp3")

        # Alice submits the correct guess (round 0 = "Bohemian Rhapsody" / "Queen").
        ws_a.send_text(json.dumps({"type": "guess", "text": "Bohemian Rhapsody Queen"}))

        # We should observe a guess_result with kind="both" and points > 0.
        result = _drain_until(
            ws_a,
            lambda m: m["type"] == "guess_result" and m["player_id"] == "alice",
        )
        assert result["kind"] == "both"
        assert result["points"] > 0
        assert result["total"] == result["points"]


def test_unknown_room_closes_websocket(client: TestClient) -> None:
    """Connecting to a room that does not exist closes the socket immediately."""
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/ZZZZZZ?player_id=x&name=X") as ws,
    ):
        ws.receive_text()


def test_non_host_cannot_start(client: TestClient) -> None:
    code = client.post("/api/rooms/synthetic?round_seconds=1&reveal_seconds=0.1").json()["code"]
    with client.websocket_connect(f"/ws/{code}?player_id=alice&name=Alice") as ws_a, \
         client.websocket_connect(f"/ws/{code}?player_id=bob&name=Bob") as ws_b:
        # Drain initial state.
        _drain_until(ws_a, lambda m: m["type"] == "state")
        _drain_until(ws_b, lambda m: m["type"] == "state")
        # Bob (non-host) tries to start.
        ws_b.send_text(json.dumps({"type": "start"}))
        err = _drain_until(ws_b, lambda m: m["type"] == "error")
        assert "host" in err["message"].lower()


def test_ping_pong(client: TestClient) -> None:
    code = client.post("/api/rooms/synthetic?round_seconds=1&reveal_seconds=0.1").json()["code"]
    with client.websocket_connect(f"/ws/{code}?player_id=p1&name=P1") as ws:
        _drain_until(ws, lambda m: m["type"] == "state")
        ws.send_text(json.dumps({"type": "ping"}))
        pong = _drain_until(ws, lambda m: m["type"] == "pong")
        assert pong["type"] == "pong"


def test_bad_message_returns_error(client: TestClient) -> None:
    code = client.post("/api/rooms/synthetic?round_seconds=1&reveal_seconds=0.1").json()["code"]
    with client.websocket_connect(f"/ws/{code}?player_id=p1&name=P1") as ws:
        _drain_until(ws, lambda m: m["type"] == "state")
        ws.send_text("not json at all")
        err = _drain_until(ws, lambda m: m["type"] == "error")
        assert "bad message" in err["message"].lower()
