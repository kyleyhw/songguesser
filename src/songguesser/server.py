"""FastAPI app: HTTP routes for room creation + Spotify auth, WebSocket for
gameplay.

HTTP routes
-----------

  GET  /                    — landing page (lobby/create/join UI)
  GET  /static/*            — the browser client assets
  POST /api/rooms           — create a room from a Spotify playlist URL
  GET  /api/rooms/{code}    — public room metadata (for prejoin display)
  GET  /auth/login          — kick off Spotify PKCE OAuth (host only)
  GET  /auth/callback       — receive Spotify redirect, exchange code

WebSocket route
---------------

  WS   /ws/{code}?player_id=<uuid>&name=<str>

The client must specify a stable `player_id` (UUID stored in localStorage)
so that reconnects re-attach to the same Player and preserve score.

Round timing
------------
Round PLAYING phase lasts ``round_seconds`` (default 30 s). The server's
round runner task sleeps in 100 ms increments and broadcasts a
``round_tick`` every 250 ms so clients can render the cover-art reveal
and preview-progress bar smoothly. When everyone has solved (or time runs
out), the runner transitions to REVEAL for ``reveal_seconds`` (default 8 s)
and then either advances or ends the game.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .engine import GameEngine
from .models import GuessKind, Player, Playlist, Room, RoomPhase, Track
from .protocol import (
    ChatMsg,
    ErrorMsg,
    GuessResultMsg,
    PlayerPublic,
    PongMsg,
    RoomSnapshot,
    RoundEndMsg,
    RoundStartMsg,
    RoundTickMsg,
    StateMsg,
    TrackPublic,
    parse_inbound,
)
from .rooms import RoomEntry, RoomRegistry
from .spotify_public import SpotifyPublicError
from .spotify_public import fetch_playlist as fetch_public_playlist

log = logging.getLogger("songguesser.server")

STATIC_DIR = Path(__file__).parent / "static"


class CreateRoomBody(BaseModel):
    playlist_url: str
    max_rounds: int = 10
    # Spotify CDN previews are 30 s; the round cannot exceed the audio.
    round_seconds: float = Field(default=15.0, gt=0, le=30.0)
    reveal_seconds: float = 4.0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.registry = RoomRegistry()
    log.info("songguesser server started")
    try:
        yield
    finally:
        # Cancel any in-flight per-room game runner tasks so the test client's
        # context-manager teardown does not block waiting on round timers.
        registry: RoomRegistry = app.state.registry
        for code in registry.all_codes():
            entry = registry.get(code)
            if entry and entry.runner is not None and not entry.runner.done():
                entry.runner.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="songguesser", lifespan=lifespan)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---- HTTP --------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse(
                "<h1>songguesser</h1><p>Static client missing.</p>", status_code=500
            )
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    @app.post("/api/rooms")
    async def create_room(request: Request, body: CreateRoomBody) -> JSONResponse:
        registry: RoomRegistry = request.app.state.registry
        try:
            playlist = await fetch_public_playlist(body.playlist_url, enrich_covers=True)
        except SpotifyPublicError as exc:
            raise HTTPException(502, f"Spotify parse error: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not playlist.tracks:
            raise HTTPException(
                422, "playlist has no playable tracks (all previews are unavailable)"
            )
        # Shuffle to avoid playing the same opening every game.
        import random

        rng = random.Random()
        all_tracks = list(playlist.tracks)
        rng.shuffle(all_tracks)
        playlist = playlist.with_tracks(all_tracks)

        code = registry.fresh_code()
        engine = GameEngine.new(
            code=code,
            playlist=playlist,
            max_rounds=body.max_rounds,
            round_seconds=body.round_seconds,
            reveal_seconds=body.reveal_seconds,
        )
        await registry.create(engine)
        return JSONResponse(
            {
                "code": code,
                "playlist_name": playlist.name,
                "track_count": len(playlist.tracks),
                "max_rounds": body.max_rounds,
            }
        )

    @app.post("/api/rooms/synthetic")
    async def create_synthetic_room(
        request: Request,
        round_seconds: float = Query(default=8.0),
        reveal_seconds: float = Query(default=2.0),
    ) -> JSONResponse:
        """Test-only: create a room with three synthetic tracks pointing at
        a tiny inline silent MP3 served from /static/silence.mp3.

        Gated by ``SONGGUESSER_ENABLE_SYNTHETIC=1`` so it cannot accidentally
        be exposed in production deployments.
        """
        if os.environ.get("SONGGUESSER_ENABLE_SYNTHETIC") != "1":
            raise HTTPException(404, "not found")
        registry: RoomRegistry = request.app.state.registry
        synthetic_tracks = tuple(
            Track(
                id=str(i),
                title=t,
                artist=a,
                isrc=None,
                preview_url="/static/silence.mp3",
                cover_url=None,
                duration_ms=15_000,
            )
            for i, (t, a) in enumerate(
                [
                    ("Bohemian Rhapsody", "Queen"),
                    ("Hello", "Adele"),
                    ("Believer", "Imagine Dragons"),
                ]
            )
        )
        playlist = Playlist(
            source="deezer",
            source_id="synthetic",
            name="Synthetic Test Playlist",
            tracks=synthetic_tracks,
        )
        code = registry.fresh_code()
        engine = GameEngine.new(
            code=code,
            playlist=playlist,
            max_rounds=3,
            round_seconds=round_seconds,
            reveal_seconds=reveal_seconds,
        )
        await registry.create(engine)
        return JSONResponse({"code": code, "playlist_name": playlist.name, "track_count": 3})

    @app.get("/api/rooms/{code}")
    async def room_meta(request: Request, code: str) -> JSONResponse:
        registry: RoomRegistry = request.app.state.registry
        entry = registry.get(code)
        if entry is None:
            raise HTTPException(404, "room not found")
        return JSONResponse(
            {
                "code": entry.engine.room.code,
                "phase": entry.engine.room.phase.value,
                "playlist_name": entry.engine.room.playlist.name,
                "max_rounds": entry.engine.room.max_rounds,
                "players": [
                    {"name": p.name, "is_host": p.is_host}
                    for p in entry.engine.room.players.values()
                ],
            }
        )

    # ---- WebSocket ---------------------------------------------------------

    @app.websocket("/ws/{code}")
    async def ws_room(
        ws: WebSocket,
        code: str,
        player_id: str = Query(default_factory=lambda: uuid4().hex),
        name: str = Query(default="player"),
    ) -> None:
        registry: RoomRegistry = ws.app.state.registry
        entry = registry.get(code)
        if entry is None:
            await ws.close(code=4404, reason="room not found")
            return
        await ws.accept()
        sanitized = (name.strip() or "player")[:24]
        await _handle_socket(entry, ws, player_id, sanitized)

    return app


# ---------------------------------------------------------------------------
# WebSocket inner loop and round runner
# ---------------------------------------------------------------------------


async def _handle_socket(entry: RoomEntry, ws: WebSocket, player_id: str, name: str) -> None:
    engine = entry.engine
    async with entry.lock:
        if not engine.reconnect_player(player_id):
            engine.add_player(Player(id=player_id, name=name))
        entry.sockets[player_id] = ws

    await _broadcast_state(entry)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload: dict[str, Any] = json.loads(raw)
                msg = parse_inbound(payload)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                await ws.send_json(ErrorMsg(message=f"bad message: {exc}").model_dump())
                continue

            if msg.type == "ping":
                await ws.send_json(PongMsg().model_dump())
                continue
            if msg.type == "start":
                async with entry.lock:
                    me = engine.room.players.get(player_id)
                    if me is None or not me.is_host:
                        await ws.send_json(ErrorMsg(message="only the host can start").model_dump())
                        continue
                    if engine.room.phase != RoomPhase.LOBBY:
                        await ws.send_json(ErrorMsg(message="game already running").model_dump())
                        continue
                if entry.runner is None or entry.runner.done():
                    entry.runner = asyncio.create_task(_run_game(entry))
                continue
            if msg.type == "next":
                async with entry.lock:
                    me = engine.room.players.get(player_id)
                    if me is None or not me.is_host:
                        await ws.send_json(
                            ErrorMsg(message="only the host can advance").model_dump()
                        )
                        continue
                # Simplest: cancel the current runner and launch a fresh one.
                # The runner reads `phase` to decide what to do next.
                if entry.runner is not None and not entry.runner.done():
                    entry.runner.cancel()
                entry.runner = asyncio.create_task(_run_game(entry))
                continue
            if msg.type == "guess":
                async with entry.lock:
                    out = engine.submit_guess(player_id, msg.text)
                if out is None:
                    continue
                # Echo the guess to chat so other players can see attempts.
                player = engine.room.players[player_id]
                chat = ChatMsg(player_id=player_id, name=player.name, text=msg.text)
                await _broadcast(entry, chat.model_dump())
                if out.delta.points > 0 or out.match.kind != GuessKind.NONE:
                    await _broadcast(
                        entry,
                        GuessResultMsg(
                            player_id=player_id,
                            name=player.name,
                            kind=out.match.kind.value,
                            points=out.delta.points,
                            total=out.new_score,
                        ).model_dump(),
                    )
                if out.everyone_solved:
                    # Cancel the runner's sleep so it transitions immediately.
                    if entry.runner is not None and not entry.runner.done():
                        entry.runner.cancel()
                    entry.runner = asyncio.create_task(_run_game(entry, skip_to_reveal=True))
    except WebSocketDisconnect:
        pass
    finally:
        async with entry.lock:
            engine.remove_player(player_id)
            entry.sockets.pop(player_id, None)
        await _broadcast_state(entry)


async def _broadcast(entry: RoomEntry, payload: dict[str, Any]) -> None:
    dead: list[str] = []
    for pid, sock in list(entry.sockets.items()):
        try:
            await sock.send_json(payload)
        except Exception:
            dead.append(pid)
    for pid in dead:
        entry.sockets.pop(pid, None)


def _snapshot(room: Room) -> RoomSnapshot:
    return RoomSnapshot(
        code=room.code,
        phase=room.phase.value,
        playlist_name=room.playlist.name,
        round_index=room.current_round_index,
        total_rounds=len(room.rounds),
        round_seconds=room.round_seconds,
        reveal_seconds=room.reveal_seconds,
        players=[
            PlayerPublic(
                id=p.id,
                name=p.name,
                score=p.score,
                is_host=p.is_host,
                connected=p.connected,
                round_kind=p.round_kind.value,
            )
            for p in room.leaderboard()
        ],
    )


async def _broadcast_state(entry: RoomEntry) -> None:
    snap = _snapshot(entry.engine.room)
    await _broadcast(entry, StateMsg(room=snap).model_dump())


def _track_public(t: Track) -> TrackPublic:
    return TrackPublic(
        id=t.id,
        title=t.title,
        artist=t.artist,
        cover_url=t.cover_url,
        duration_ms=t.duration_ms,
    )


async def _run_game(entry: RoomEntry, *, skip_to_reveal: bool = False) -> None:
    """Drive the game forward.

    On entry, the room is either LOBBY (start the first round), PLAYING
    (continue the current round), or REVEAL (advance to the next round).
    The function loops until the playlist is exhausted; cancellation is
    used to interrupt the playing-phase sleep when everyone solves early.
    """
    engine = entry.engine
    try:
        while not engine.is_finished():
            phase = engine.room.phase
            if phase == RoomPhase.LOBBY or phase == RoomPhase.REVEAL:
                if skip_to_reveal:
                    # We were re-entered because everyone solved. Switch to REVEAL
                    # immediately rather than starting a new round.
                    skip_to_reveal = False
                    async with entry.lock:
                        engine.end_round_to_reveal()
                    await _broadcast_round_end(entry)
                    await asyncio.sleep(engine.room.reveal_seconds)
                    continue
                async with entry.lock:
                    try:
                        round = engine.start_round()
                    except StopIteration:
                        await _broadcast_state(entry)
                        return
                await _broadcast(
                    entry,
                    RoundStartMsg(
                        round_index=round.index,
                        audio_url=round.track.preview_url,
                        duration=round.duration_seconds,
                        cover_url=round.track.cover_url,
                    ).model_dump(),
                )
                await _broadcast_state(entry)
                # Tick loop.
                deadline = time.monotonic() + round.duration_seconds
                try:
                    while time.monotonic() < deadline:
                        elapsed = round.elapsed()
                        await _broadcast(
                            entry,
                            RoundTickMsg(elapsed=elapsed, progress=round.progress()).model_dump(),
                        )
                        await asyncio.sleep(0.25)
                except asyncio.CancelledError:
                    pass
                async with entry.lock:
                    engine.end_round_to_reveal()
                await _broadcast_round_end(entry)
                await asyncio.sleep(engine.room.reveal_seconds)
            elif phase == RoomPhase.PLAYING:
                # Should not happen; runner owns transitions. Defensive.
                await asyncio.sleep(0.5)
            else:
                break
    finally:
        await _broadcast_state(entry)


async def _broadcast_round_end(entry: RoomEntry) -> None:
    engine = entry.engine
    round = engine.room.current_round
    if round is None:
        return
    leaderboard = [
        PlayerPublic(
            id=p.id,
            name=p.name,
            score=p.score,
            is_host=p.is_host,
            connected=p.connected,
            round_kind=p.round_kind.value,
        )
        for p in engine.room.leaderboard()
    ]
    is_final = round.index + 1 >= len(engine.room.rounds)
    await _broadcast(
        entry,
        RoundEndMsg(
            round_index=round.index,
            track=_track_public(round.track),
            leaderboard=leaderboard,
            is_final=is_final,
        ).model_dump(),
    )


app = create_app()
