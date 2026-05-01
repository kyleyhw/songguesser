"""Unit tests for `songguesser.models`.

We verify:
  * Track / Playlist are immutable (Pydantic frozen=True),
  * Round.elapsed and Round.progress are correct under monotonic clocks,
  * Room.leaderboard ranks by score descending, name ascending as tiebreaker.
"""

from __future__ import annotations

from time import monotonic

import pytest
from pydantic import ValidationError

from songguesser.models import (
    Player,
    Playlist,
    Room,
    RoomPhase,
    Round,
    Track,
    make_room_code,
)


def _track(i: int = 0) -> Track:
    return Track(
        id=str(i),
        title=f"t{i}",
        artist=f"a{i}",
        isrc=f"ISRC{i:06d}",
        preview_url="https://cdn.example/preview.mp3",
        cover_url="https://cdn.example/cover.jpg",
        duration_ms=210_000,
    )


def test_track_is_frozen() -> None:
    t = _track()
    with pytest.raises(ValidationError):
        t.title = "mutated"  # type: ignore[misc]


def test_playlist_with_tracks_replaces_tuple_immutably() -> None:
    p = Playlist(source="spotify", source_id="abc", name="N", tracks=())
    p2 = p.with_tracks([_track(1), _track(2)])
    assert p.tracks == ()  # original untouched
    assert len(p2.tracks) == 2 and p2.tracks[0].title == "t1"


def test_round_elapsed_and_progress() -> None:
    r = Round(index=0, track=_track(), duration_seconds=10.0)
    assert r.elapsed() == 0.0  # not started
    assert r.progress() == 0.0
    # Pretend the round started one second ago.
    r.started_at_monotonic = monotonic() - 1.0
    e = r.elapsed()
    assert 0.9 <= e <= 1.5  # generous bound for CI scheduling jitter
    assert 0.0 < r.progress() < 0.2


def test_round_clamps_to_duration() -> None:
    r = Round(index=0, track=_track(), duration_seconds=5.0)
    r.started_at_monotonic = monotonic() - 999.0
    assert r.elapsed() == 5.0
    assert r.progress() == 1.0


def test_room_leaderboard_orders_by_score_desc_then_name() -> None:
    room = Room(
        code=make_room_code(),
        playlist=Playlist(source="deezer", source_id="x", name="x", tracks=()),
    )
    room.players = {
        "a": Player(id="a", name="Alice", score=10),
        "b": Player(id="b", name="bob", score=20),
        "c": Player(id="c", name="Carol", score=20),
    }
    board = room.leaderboard()
    # 20-bob (lowercased "bob" < "carol"), 20-Carol, 10-Alice.
    assert [p.id for p in board] == ["b", "c", "a"]


def test_phase_default_is_lobby() -> None:
    room = Room(
        code="ABC123",
        playlist=Playlist(source="deezer", source_id="x", name="x", tracks=()),
    )
    assert room.phase == RoomPhase.LOBBY
    assert room.current_round is None


def test_make_room_code_format() -> None:
    code = make_room_code()
    assert len(code) == 6 and code == code.upper()
    assert all(c in "0123456789ABCDEF" for c in code)
