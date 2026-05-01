"""Tests for the score curve and award lattice."""

from __future__ import annotations

import pytest

from songguesser.models import GuessKind
from songguesser.scoring import (
    FULL_AWARD,
    PART_AWARD,
    ScoreDelta,
    award_for,
    speed_score,
)

# ---- speed_score --------------------------------------------------------------

@pytest.mark.parametrize(
    ("elapsed", "duration", "base", "expected"),
    [
        (0.0, 30.0, 1000, 1000),  # fastest possible
        (15.0, 30.0, 1000, 500),  # exactly half
        (30.0, 30.0, 1000, 0),    # exactly the duration
        (40.0, 30.0, 1000, 0),    # past the end
        (10.0, 30.0, 500, int(500 * (1 - 10 / 30))),  # 333
    ],
)
def test_speed_score(elapsed: float, duration: float, base: int, expected: int) -> None:
    assert speed_score(elapsed, duration=duration, base=base) == expected


def test_speed_score_zero_duration() -> None:
    assert speed_score(0.0, duration=0.0, base=1000) == 0


# ---- award_for: lattice + monotonicity ----------------------------------------

def test_award_first_full_match_at_t0_yields_full_award() -> None:
    delta = award_for(
        elapsed=0.0, duration=30.0, new_match=GuessKind.BOTH, current=GuessKind.NONE,
    )
    assert delta == ScoreDelta(FULL_AWARD, GuessKind.NONE, GuessKind.BOTH)


def test_award_partial_then_full_upgrades_total_to_full() -> None:
    """A title-then-artist sequence should leave the player with the
    *full* award at the time of the final completing guess — never less."""
    duration = 30.0
    t1 = 5.0
    t2 = 12.0

    # 1) Title at t1 -> PART_AWARD * (1 - 5/30) = floor(500 * 25/30) = 416
    d1 = award_for(elapsed=t1, duration=duration, new_match=GuessKind.TITLE, current=GuessKind.NONE)
    assert d1.to_kind == GuessKind.TITLE
    expected_part = int(PART_AWARD * (1 - t1 / duration))
    assert d1.points == expected_part

    # 2) Artist at t2 -> upgrades to BOTH; should top up to full at t2.
    d2 = award_for(
        elapsed=t2, duration=duration, new_match=GuessKind.ARTIST, current=GuessKind.TITLE
    )
    assert d2.to_kind == GuessKind.BOTH
    expected_full_at_t2 = int(FULL_AWARD * (1 - t2 / duration))
    expected_already = int(PART_AWARD * (1 - t2 / duration))  # what they would have at t2
    expected_topup = max(expected_full_at_t2 - expected_already, 0)
    assert d2.points == expected_topup
    # Total over both deltas = expected_part + expected_topup; but we want
    # to verify "never less than full at t2": partial at t1 ≥ full at t2 - topup
    assert d1.points + d2.points >= expected_full_at_t2 - 1  # +/- floor rounding


def test_award_no_match_is_zero() -> None:
    d = award_for(elapsed=5.0, duration=30.0, new_match=GuessKind.NONE, current=GuessKind.NONE)
    assert d.points == 0 and d.to_kind == GuessKind.NONE


def test_award_repeat_match_does_not_double_pay() -> None:
    """If a player guesses the title twice, the second guess pays nothing."""
    d = award_for(elapsed=5.0, duration=30.0, new_match=GuessKind.TITLE, current=GuessKind.TITLE)
    assert d.points == 0 and d.to_kind == GuessKind.TITLE


def test_award_both_after_both_pays_zero() -> None:
    d = award_for(elapsed=5.0, duration=30.0, new_match=GuessKind.BOTH, current=GuessKind.BOTH)
    assert d.points == 0


def test_score_strictly_decreasing_in_elapsed() -> None:
    """As elapsed time increases, the (single-shot BOTH) score must
    monotonically non-increase. We sample 0, 5, 10, ..., 30."""
    duration = 30.0
    last = FULL_AWARD + 1
    for t in range(0, 31, 5):
        d = award_for(
            elapsed=float(t),
            duration=duration,
            new_match=GuessKind.BOTH,
            current=GuessKind.NONE,
        )
        assert d.points <= last
        last = d.points
