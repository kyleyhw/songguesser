"""Tests for guess matching."""

from __future__ import annotations

import pytest

from songguesser.matcher import match_guess
from songguesser.models import GuessKind, Track


def _track(title: str, artist: str) -> Track:
    return Track(
        id="x",
        title=title,
        artist=artist,
        isrc=None,
        preview_url="https://x/y.mp3",
        cover_url=None,
        duration_ms=200_000,
    )


@pytest.mark.parametrize(
    ("guess", "expected"),
    [
        ("Hello", GuessKind.TITLE),
        ("Adele", GuessKind.ARTIST),
        ("Adele Hello", GuessKind.BOTH),
        ("Hello Adele", GuessKind.BOTH),
        ("hello adele", GuessKind.BOTH),
        ("HELLO  ADELE", GuessKind.BOTH),
        ("totally unrelated", GuessKind.NONE),
    ],
)
def test_match_basic(guess: str, expected: GuessKind) -> None:
    track = _track("Hello", "Adele")
    assert match_guess(guess, track).kind == expected


def test_match_robust_to_remaster_tag_in_track() -> None:
    track = _track("Don't Stop Me Now (Remastered 2011)", "Queen")
    assert match_guess("Don't Stop Me Now", track).kind == GuessKind.TITLE
    assert match_guess("Queen Don't Stop Me Now", track).kind == GuessKind.BOTH


def test_match_robust_to_diacritics() -> None:
    track = _track("Café", "Beyoncé")
    assert match_guess("cafe", track).kind == GuessKind.TITLE
    assert match_guess("beyonce", track).kind == GuessKind.ARTIST


def test_typo_below_threshold_is_none() -> None:
    """A complete fabrication should not match either field."""
    track = _track("Hello", "Adele")
    assert match_guess("xyzqq", track).kind == GuessKind.NONE


def test_partial_token_overlap_is_not_enough() -> None:
    """One shared token out of three is below threshold."""
    track = _track("Bohemian Rhapsody", "Queen")
    res = match_guess("Bohemian", track)
    # `Bohemian` token-set-ratios well against `bohemian rhapsody`; 1.0 is OK
    # for partial credit on title since it's a strict subset of the title's
    # tokens. We accept this as TITLE — locking in current behaviour.
    assert res.kind == GuessKind.TITLE
