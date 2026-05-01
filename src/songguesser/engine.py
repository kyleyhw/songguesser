"""Game engine: room state machine and guess processing.

The engine is single-threaded per Room. It exposes two side-effecting
operations:

  * :meth:`GameEngine.start_round` — advances the room from LOBBY/REVEAL
    to PLAYING and resets per-round state.
  * :meth:`GameEngine.submit_guess` — classifies a guess, awards score,
    and may transition the room to REVEAL when all players have solved.

All round timing transitions (PLAYING → REVEAL on time-up, REVEAL → next
PLAYING after `reveal_seconds`) are driven by the websocket server's
asyncio loop in :mod:`songguesser.server`, not by the engine itself; the
engine only exposes pure transition methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic

from .matcher import MatchResult, match_guess
from .models import GuessKind, Player, Playlist, Room, RoomPhase, Round
from .scoring import ScoreDelta, award_for

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuessOutcome:
    player_id: str
    match: MatchResult
    delta: ScoreDelta
    new_score: int
    everyone_solved: bool


class GameEngine:
    def __init__(self, room: Room) -> None:
        self.room = room

    # -- room construction ------------------------------------------------------

    @classmethod
    def new(
        cls,
        *,
        code: str,
        playlist: Playlist,
        max_rounds: int = 10,
        round_seconds: float = 30.0,
        reveal_seconds: float = 8.0,
    ) -> GameEngine:
        # Round selection: use the first `max_rounds` tracks of the playlist.
        # The server-side caller may shuffle the playlist before passing it
        # in; the engine itself keeps the input order.
        chosen = playlist.tracks[:max_rounds]
        rounds = [
            Round(index=i, track=t, duration_seconds=round_seconds) for i, t in enumerate(chosen)
        ]
        room = Room(
            code=code,
            playlist=playlist.with_tracks(chosen),
            rounds=rounds,
            current_round_index=-1,
            phase=RoomPhase.LOBBY,
            round_seconds=round_seconds,
            reveal_seconds=reveal_seconds,
            max_rounds=max_rounds,
        )
        return cls(room)

    # -- player management ------------------------------------------------------

    def add_player(self, player: Player) -> None:
        if not self.room.players:
            player.is_host = True
        self.room.players[player.id] = player

    def remove_player(self, player_id: str) -> None:
        # Mark disconnected rather than evict, so they can rejoin and keep score.
        p = self.room.players.get(player_id)
        if p is not None:
            p.connected = False

    def reconnect_player(self, player_id: str) -> bool:
        p = self.room.players.get(player_id)
        if p is None:
            return False
        p.connected = True
        return True

    # -- round lifecycle --------------------------------------------------------

    def start_round(self) -> Round:
        self.room.current_round_index += 1
        if self.room.current_round_index >= len(self.room.rounds):
            self.room.phase = RoomPhase.FINISHED
            raise StopIteration("playlist exhausted")
        for p in self.room.players.values():
            p.round_kind = GuessKind.NONE
            p.round_solved_at = None
        round = self.room.rounds[self.room.current_round_index]
        round.started_at_monotonic = monotonic()
        self.room.phase = RoomPhase.PLAYING
        return round

    def end_round_to_reveal(self) -> Round | None:
        """Transition the current round to REVEAL. Idempotent; no-ops if not
        in PLAYING."""
        if self.room.phase != RoomPhase.PLAYING:
            return self.room.current_round
        self.room.phase = RoomPhase.REVEAL
        return self.room.current_round

    def is_finished(self) -> bool:
        return self.room.phase == RoomPhase.FINISHED or (
            self.room.current_round_index + 1 >= len(self.room.rounds)
            and self.room.phase == RoomPhase.REVEAL
        )

    # -- guesses ----------------------------------------------------------------

    def submit_guess(self, player_id: str, text: str) -> GuessOutcome | None:
        """Classify a guess and update scores. Returns ``None`` when the room
        is not currently accepting guesses (e.g. LOBBY/REVEAL/FINISHED)."""
        if self.room.phase != RoomPhase.PLAYING:
            return None
        round = self.room.current_round
        if round is None:
            return None
        player = self.room.players.get(player_id)
        if player is None:
            return None

        match = match_guess(text, round.track)
        if match.kind == GuessKind.NONE or player.round_kind == GuessKind.BOTH:
            zero = ScoreDelta(0, player.round_kind, player.round_kind)
            return GuessOutcome(player.id, match, zero, player.score, False)

        delta = award_for(
            elapsed=round.elapsed(),
            duration=round.duration_seconds,
            new_match=match.kind,
            current=player.round_kind,
        )
        player.round_kind = delta.to_kind
        player.score += delta.points
        if delta.to_kind == GuessKind.BOTH and player.round_solved_at is None:
            player.round_solved_at = round.elapsed()

        all_solved = all(
            p.round_kind == GuessKind.BOTH or not p.connected
            for p in self.room.players.values()
        )

        return GuessOutcome(
            player_id=player.id,
            match=match,
            delta=delta,
            new_score=player.score,
            everyone_solved=all_solved,
        )
