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


def test_main_artist_accepted_featured_rejected() -> None:
    """Any main artist (comma-separated, before any 'ft.' marker) is
    accepted; featured artists are not."""
    track = _track("Run This Town", "Kanye West, Jay-Z ft. Rihanna")
    assert match_guess("Kanye West", track).kind == GuessKind.ARTIST
    assert match_guess("kanye west", track).kind == GuessKind.ARTIST
    assert match_guess("Jay-Z", track).kind == GuessKind.ARTIST
    assert match_guess("jay z", track).kind == GuessKind.ARTIST
    assert match_guess("Rihanna", track).kind == GuessKind.NONE


def test_inline_feat_no_parens_strips_featured() -> None:
    track = _track("We Found Love", "Calvin Harris feat. Rihanna")
    assert match_guess("Calvin Harris", track).kind == GuessKind.ARTIST
    assert match_guess("Rihanna", track).kind == GuessKind.NONE


def test_ampersand_within_single_artist_is_not_split() -> None:
    """'Mumford & Sons' is one artist — the '&' must not split it."""
    track = _track("The Cave", "Mumford & Sons")
    assert match_guess("Mumford", track).kind == GuessKind.NONE
    assert match_guess("Sons", track).kind == GuessKind.NONE
    assert match_guess("Mumford & Sons", track).kind == GuessKind.ARTIST


def test_both_with_main_artist_only() -> None:
    """The combined form accepts <title> + any main artist."""
    track = _track("Run This Town", "Kanye West, Jay-Z ft. Rihanna")
    assert match_guess("Run This Town Kanye West", track).kind == GuessKind.BOTH
    assert match_guess("kanye west run this town", track).kind == GuessKind.BOTH
    # Title + featured artist is neither title-only nor BOTH; it's NONE.
    assert match_guess("Run This Town Rihanna", track).kind == GuessKind.NONE
