"""Wire protocol between the FastAPI WebSocket server and browser clients.

All messages are JSON objects with a ``type`` discriminator. Inbound and
outbound messages are validated with Pydantic; any unknown ``type`` is
rejected.

Inbound (client → server):
    {type: "join", name: str}
    {type: "start"}
    {type: "guess", text: str}
    {type: "next"}                 — host advances to the next round
    {type: "ping"}                  — keepalive

Outbound (server → client):
    {type: "state", room: <RoomSnapshot>}
    {type: "round_start", round_index: int, audio_url: str, duration: float, cover_url: str}
    {type: "round_tick", elapsed: float, progress: float}
    {type: "round_end", round_index: int, track: <TrackPublic>, leaderboard: [...]}
    {type: "guess_result", player_id: str, name: str, kind: str, points: int, total: int}
    {type: "chat", player_id: str, name: str, text: str}
    {type: "error", message: str}
    {type: "pong"}
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# --- inbound ----------------------------------------------------------------


class JoinMsg(BaseModel):
    type: Literal["join"]
    name: str = Field(min_length=1, max_length=24)


class StartMsg(BaseModel):
    type: Literal["start"]


class GuessMsg(BaseModel):
    type: Literal["guess"]
    text: str = Field(min_length=1, max_length=200)


class NextMsg(BaseModel):
    type: Literal["next"]


class PingMsg(BaseModel):
    type: Literal["ping"]


# --- outbound ---------------------------------------------------------------


class TrackPublic(BaseModel):
    id: str
    title: str
    artist: str
    cover_url: str | None
    duration_ms: int | None


class PlayerPublic(BaseModel):
    id: str
    name: str
    score: int
    is_host: bool
    connected: bool
    round_kind: str  # "none" | "title" | "artist" | "both"


class RoomSnapshot(BaseModel):
    code: str
    phase: str
    playlist_name: str
    round_index: int
    total_rounds: int
    round_seconds: float
    reveal_seconds: float
    players: list[PlayerPublic]


class StateMsg(BaseModel):
    type: Literal["state"] = "state"
    room: RoomSnapshot


class RoundStartMsg(BaseModel):
    type: Literal["round_start"] = "round_start"
    round_index: int
    audio_url: str
    duration: float
    cover_url: str | None


class RoundTickMsg(BaseModel):
    type: Literal["round_tick"] = "round_tick"
    elapsed: float
    progress: float


class RoundEndMsg(BaseModel):
    type: Literal["round_end"] = "round_end"
    round_index: int
    track: TrackPublic
    leaderboard: list[PlayerPublic]
    is_final: bool


class GuessResultMsg(BaseModel):
    type: Literal["guess_result"] = "guess_result"
    player_id: str
    name: str
    kind: str
    points: int
    total: int


class ChatMsg(BaseModel):
    type: Literal["chat"] = "chat"
    player_id: str
    name: str
    text: str


class ErrorMsg(BaseModel):
    type: Literal["error"] = "error"
    message: str


class PongMsg(BaseModel):
    type: Literal["pong"] = "pong"


def parse_inbound(raw: dict[str, Any]) -> JoinMsg | StartMsg | GuessMsg | NextMsg | PingMsg:
    """Validate any inbound JSON envelope. Raises pydantic.ValidationError
    on bad input."""
    t = raw.get("type")
    if t == "join":
        return JoinMsg.model_validate(raw)
    if t == "start":
        return StartMsg.model_validate(raw)
    if t == "guess":
        return GuessMsg.model_validate(raw)
    if t == "next":
        return NextMsg.model_validate(raw)
    if t == "ping":
        return PingMsg.model_validate(raw)
    raise ValueError(f"unknown message type: {t!r}")
