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


def test_partial_token_does_not_match() -> None:
    """A subset of the title's tokens must NOT count as a match.

    Strict policy: after normalisation the guess must equal the field
    exactly. "Bohemian" alone does not equal "Bohemian Rhapsody".
    """
    track = _track("Bohemian Rhapsody", "Queen")
    assert match_guess("Bohemian", track).kind == GuessKind.NONE
    assert match_guess("Rhapsody", track).kind == GuessKind.NONE


def test_full_title_matches() -> None:
    track = _track("Bohemian Rhapsody", "Queen")
    assert match_guess("Bohemian Rhapsody", track).kind == GuessKind.TITLE
    assert match_guess("bohemian rhapsody!", track).kind == GuessKind.TITLE
    assert match_guess("  Bohemian   Rhapsody  ", track).kind == GuessKind.TITLE
