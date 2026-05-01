"""Round scoring and guess-kind aggregation.

Score curve
-----------
We adopt a *linear* speed bonus, the same family ``binb`` uses but
parameterised. Let

    t        = elapsed seconds since the round started, t ∈ [0, T]
    T        = round duration (default 30 s)
    p_full   = full-credit award for guessing both artist and title
    p_part   = partial-credit award for guessing only one of {artist, title}

Then the awarded score is

    s(t, k) = w(k) · ⌊p_full · (1 - t/T)⌋ + bonus(k)

with ``w(BOTH) = 1.0``, ``w(TITLE | ARTIST) = p_part / p_full``, and
``bonus`` zero unless we choose to add a small flat reward for completing
both. We use ``p_full = 1000``, ``p_part = 500`` (so partial credit is
exactly half of full at the same time), and ``bonus(k) = 0``. With these
constants:

    s_full(t)  = ⌊1000 · (1 - t/T)⌋
    s_part(t)  = ⌊ 500 · (1 - t/T)⌋

so a player who guesses *both* parts at ``t = 0`` earns 1000; at ``t = T``
they earn 0; the curve is monotone non-increasing in ``t``. Partial-credit
awards are also recorded so a player who later identifies the second part
*upgrades* their award by the difference. Concretely: if a player guesses
the title at ``t1`` and the artist at ``t2 > t1`` we award

    s_part(t1) at t1, then (s_full(t2) - s_part(t1)) at t2 (clamped ≥ 0)

so the player's total for that round equals ``s_full(t2)``, never less than
the partial they had locked in. This avoids the trap where a fast partial
guess would actively *hurt* the player who completes the round later.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import GuessKind, Round

FULL_AWARD = 1000
PART_AWARD = 500


@dataclass(frozen=True)
class ScoreDelta:
    """The score change to apply to a single player after a guess.

    `from_kind` -> `to_kind` describes the player's *aggregate* round
    state before and after this guess (so the engine can know whether to
    transition the player to "solved").
    """

    points: int
    from_kind: GuessKind
    to_kind: GuessKind


def speed_score(elapsed: float, *, duration: float, base: int) -> int:
    """The base linear curve. Returns ``floor(base · (1 - t/T))`` clamped ≥ 0."""
    if duration <= 0:
        return 0
    fraction_remaining = 1.0 - (elapsed / duration)
    if fraction_remaining <= 0:
        return 0
    return int(base * fraction_remaining)  # int() truncates toward zero


def award_for(
    *,
    elapsed: float,
    duration: float,
    new_match: GuessKind,
    current: GuessKind,
) -> ScoreDelta:
    """Compute the score delta for adding `new_match` on top of `current`.

    `new_match` is what this single guess matched (TITLE, ARTIST, or BOTH).
    """
    if new_match == GuessKind.NONE:
        return ScoreDelta(0, current, current)

    # Determine the aggregate kind after this match.
    after = _merge(current, new_match)
    if after == current:
        # Player already had this credit; nothing to award.
        return ScoreDelta(0, current, current)

    # If they're now BOTH, award full minus whatever they've already earned.
    if after == GuessKind.BOTH:
        full = speed_score(elapsed, duration=duration, base=FULL_AWARD)
        already = (
            speed_score(elapsed, duration=duration, base=PART_AWARD)
            if current != GuessKind.NONE
            else 0
        )
        return ScoreDelta(max(full - already, 0), current, after)

    # Partial-credit award (TITLE or ARTIST only).
    return ScoreDelta(
        speed_score(elapsed, duration=duration, base=PART_AWARD),
        current,
        after,
    )


def _merge(a: GuessKind, b: GuessKind) -> GuessKind:
    """The lattice join over {NONE, TITLE, ARTIST, BOTH}.

    BOTH ⊓ x = BOTH; (TITLE ⊔ ARTIST) = BOTH; otherwise the non-NONE side.
    """
    if a == GuessKind.BOTH or b == GuessKind.BOTH:
        return GuessKind.BOTH
    if {a, b} == {GuessKind.TITLE, GuessKind.ARTIST}:
        return GuessKind.BOTH
    if a == GuessKind.NONE:
        return b
    return a


def round_solved_award(round: Round) -> int:
    """The maximum possible score for a player that has just solved a round
    at this exact moment. Useful for ranking *near-perfect* solvers."""
    return speed_score(round.elapsed(), duration=round.duration_seconds, base=FULL_AWARD)
