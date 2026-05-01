"""Domain models for songguesser.

The domain mirrors `binb`'s vocabulary: a Room owns a sequence of Rounds; in each
Round one Track is played and Players submit Guesses. Track metadata is sourced
from a Spotify playlist and audio is sourced from Deezer (resolved by ISRC).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Track / playlist (immutable, returned from external APIs)
# ---------------------------------------------------------------------------


class Track(BaseModel):
    """A playable track resolved from Spotify metadata to a Deezer preview URL.

    Attributes:
        id: Stable identifier within a Playlist (we use the Deezer track id).
        title: Track title as reported by Deezer (preferred over Spotify for
            consistency with the audio source).
        artist: Primary artist name.
        isrc: International Standard Recording Code, used as the cross-catalog
            join key between Spotify and Deezer.
        preview_url: HTTPS URL of a 30 s MP3 preview hosted on Deezer's CDN.
        cover_url: HTTPS URL to the album cover (typically 500x500).
        duration_ms: Full-track duration in milliseconds (informational only;
            playback is always capped at the 30 s preview).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    artist: str
    isrc: str | None
    preview_url: str
    cover_url: str | None
    duration_ms: int | None = None


class Playlist(BaseModel):
    """A resolved playlist ready to drive a game."""

    model_config = ConfigDict(frozen=True)

    source: str  # "spotify" | "deezer"
    source_id: str
    name: str
    tracks: tuple[Track, ...]

    def with_tracks(self, tracks: Iterable[Track]) -> Playlist:
        return self.model_copy(update={"tracks": tuple(tracks)})


# ---------------------------------------------------------------------------
# Game state (mutable, lives only in the room registry)
# ---------------------------------------------------------------------------


class RoomPhase(StrEnum):
    """Lifecycle of a Room.

    LOBBY      -- waiting for players, host can start.
    PLAYING    -- preview audio is broadcasting; players may submit guesses.
    REVEAL     -- track is revealed and scores are shown for `reveal_seconds`.
    FINISHED   -- last round complete; final leaderboard.
    """

    LOBBY = "lobby"
    PLAYING = "playing"
    REVEAL = "reveal"
    FINISHED = "finished"


class GuessKind(StrEnum):
    """What a player just got right.

    Scoring (see docs/reveal_math.md) is awarded once per kind per round.
    """

    NONE = "none"
    TITLE = "title"
    ARTIST = "artist"
    BOTH = "both"


@dataclass
class Player:
    """A connected player in a Room."""

    id: str
    name: str
    score: int = 0
    is_host: bool = False
    connected: bool = True
    # Per-round bookkeeping; reset at the start of each round.
    round_kind: GuessKind = GuessKind.NONE
    round_solved_at: float | None = None  # monotonic seconds since round start


@dataclass
class Round:
    """A single round of the game.

    `started_at_monotonic` is set when the round transitions to PLAYING. All
    elapsed-time calculations use `time.monotonic()` to be immune to wall-clock
    adjustments (NTP slew, DST, etc.).
    """

    index: int
    track: Track
    duration_seconds: float = 30.0
    started_at_monotonic: float | None = None

    def elapsed(self) -> float:
        """Seconds since the round began, clamped to [0, duration_seconds]."""
        if self.started_at_monotonic is None:
            return 0.0
        return min(monotonic() - self.started_at_monotonic, self.duration_seconds)

    def progress(self) -> float:
        """Fraction of the round elapsed in [0, 1]."""
        return self.elapsed() / self.duration_seconds if self.duration_seconds > 0 else 1.0


@dataclass
class Room:
    """Multiplayer room. The whole game state lives here."""

    code: str
    playlist: Playlist
    rounds: list[Round] = field(default_factory=list)
    current_round_index: int = -1
    phase: RoomPhase = RoomPhase.LOBBY
    players: dict[str, Player] = field(default_factory=dict)
    round_seconds: float = 30.0
    reveal_seconds: float = 8.0
    max_rounds: int = 10
    created_at_monotonic: float = field(default_factory=monotonic)

    @property
    def current_round(self) -> Round | None:
        if 0 <= self.current_round_index < len(self.rounds):
            return self.rounds[self.current_round_index]
        return None

    def leaderboard(self) -> list[Player]:
        return sorted(self.players.values(), key=lambda p: (-p.score, p.name.lower()))


# ---------------------------------------------------------------------------
# Wire messages (client <-> server)
# ---------------------------------------------------------------------------


class GuessMessage(BaseModel):
    """Inbound guess from a client."""

    type: str = Field(default="guess", frozen=True)
    text: str


def make_room_code() -> str:
    """A 6-character base32 code, e.g. 'A3F9KQ'. ~36^6 ≈ 2.2e9 distinct codes."""
    return uuid4().hex[:6].upper()
