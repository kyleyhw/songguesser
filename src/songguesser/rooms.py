"""Room registry — in-memory mapping from room code → live game.

Each entry holds the engine, the connected websockets keyed by player id,
and a per-room asyncio.Lock so that concurrent inbound websocket messages
are processed serially with respect to engine state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from .engine import GameEngine
from .models import make_room_code

log = logging.getLogger(__name__)


@dataclass
class RoomEntry:
    engine: GameEngine
    sockets: dict[str, WebSocket] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Tracks the round-runner task so we can cancel it on disconnect/cleanup.
    runner: asyncio.Task[None] | None = None


class RoomRegistry:
    def __init__(self) -> None:
        self._rooms: dict[str, RoomEntry] = {}
        self._global_lock = asyncio.Lock()

    async def create(self, engine: GameEngine) -> RoomEntry:
        async with self._global_lock:
            code = engine.room.code
            if code in self._rooms:
                raise KeyError(f"room {code} already exists")
            entry = RoomEntry(engine=engine)
            self._rooms[code] = entry
            return entry

    def get(self, code: str) -> RoomEntry | None:
        return self._rooms.get(code.upper())

    async def delete(self, code: str) -> None:
        async with self._global_lock:
            entry = self._rooms.pop(code, None)
        if entry is None:
            return
        if entry.runner is not None and not entry.runner.done():
            entry.runner.cancel()
        from contextlib import suppress

        for ws in list(entry.sockets.values()):
            with suppress(Exception):
                await ws.close()

    def fresh_code(self) -> str:
        """A code not currently in use. Collisions are vanishingly unlikely
        with a 16M space, but we retry just in case."""
        for _ in range(50):
            code = make_room_code()
            if code not in self._rooms:
                return code
        raise RuntimeError("could not allocate a room code")

    def all_codes(self) -> list[str]:
        return list(self._rooms.keys())
