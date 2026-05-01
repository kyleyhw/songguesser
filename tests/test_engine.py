"""End-to-end tests for the GameEngine."""

from __future__ import annotations

from songguesser.engine import GameEngine
from songguesser.models import GuessKind, Player, Playlist, RoomPhase, Track


def _playlist(n: int = 3) -> Playlist:
    tracks = tuple(
        Track(
            id=str(i),
            title=f"Title {i}",
            artist=f"Artist {i}",
            isrc=f"ISRC{i}",
            preview_url=f"https://cdn/p{i}.mp3",
            cover_url=f"https://cdn/c{i}.jpg",
            duration_ms=200_000,
        )
        for i in range(n)
    )
    return Playlist(source="deezer", source_id="x", name="P", tracks=tracks)


def test_engine_lobby_to_playing() -> None:
    eng = GameEngine.new(code="ABCD12", playlist=_playlist(), round_seconds=10.0)
    eng.add_player(Player(id="a", name="Alice"))
    assert eng.room.phase == RoomPhase.LOBBY
    r = eng.start_round()
    assert eng.room.phase == RoomPhase.PLAYING
    assert r.index == 0 and r.started_at_monotonic is not None


def test_first_player_becomes_host() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist())
    eng.add_player(Player(id="a", name="Alice"))
    eng.add_player(Player(id="b", name="Bob"))
    assert eng.room.players["a"].is_host is True
    assert eng.room.players["b"].is_host is False


def test_correct_guess_awards_score_and_marks_solved() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist(), round_seconds=30.0)
    eng.add_player(Player(id="a", name="Alice"))
    eng.start_round()
    out = eng.submit_guess("a", "Artist 0 Title 0")
    assert out is not None
    assert out.match.kind == GuessKind.BOTH
    assert out.delta.points > 0
    assert eng.room.players["a"].round_kind == GuessKind.BOTH


def test_wrong_guess_yields_zero_points() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist())
    eng.add_player(Player(id="a", name="Alice"))
    eng.start_round()
    out = eng.submit_guess("a", "qqqq zzzzz")
    assert out is not None and out.delta.points == 0
    assert eng.room.players["a"].round_kind == GuessKind.NONE


def test_everyone_solved_signal_when_all_finished() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist())
    eng.add_player(Player(id="a", name="Alice"))
    eng.add_player(Player(id="b", name="Bob"))
    eng.start_round()
    out_a = eng.submit_guess("a", "Artist 0 Title 0")
    assert out_a is not None and not out_a.everyone_solved
    out_b = eng.submit_guess("b", "Title 0 Artist 0")
    assert out_b is not None and out_b.everyone_solved


def test_disconnected_player_does_not_block_everyone_solved() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist())
    eng.add_player(Player(id="a", name="Alice"))
    eng.add_player(Player(id="b", name="Bob"))
    eng.start_round()
    eng.remove_player("b")  # marks disconnected
    out = eng.submit_guess("a", "Artist 0 Title 0")
    assert out is not None and out.everyone_solved is True


def test_guess_outside_playing_phase_returns_none() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist())
    eng.add_player(Player(id="a", name="Alice"))
    # still in LOBBY
    assert eng.submit_guess("a", "Title 0") is None
    eng.start_round()
    eng.end_round_to_reveal()
    assert eng.submit_guess("a", "Title 0") is None


def test_max_rounds_clips_playlist() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist(n=10), max_rounds=3)
    assert len(eng.room.rounds) == 3


def test_playlist_exhausted_raises_and_marks_finished() -> None:
    eng = GameEngine.new(code="X", playlist=_playlist(n=1), round_seconds=1.0)
    eng.add_player(Player(id="a", name="Alice"))
    eng.start_round()
    eng.end_round_to_reveal()
    try:
        eng.start_round()
    except StopIteration:
        pass
    else:
        raise AssertionError("expected StopIteration")
    assert eng.room.phase == RoomPhase.FINISHED
