"""URL/URI parsing for Spotify playlist identifiers and PKCE primitives."""

from __future__ import annotations

import base64
import hashlib

import pytest

from songguesser.spotify import (
    code_challenge_from,
    make_code_verifier,
    parse_playlist_id,
)


@pytest.mark.parametrize(
    ("input_str", "expected_id"),
    [
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "37i9dQZF1DXcBWIGoYBM5M",
        ),
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abcd",
            "37i9dQZF1DXcBWIGoYBM5M",
        ),
        (
            "https://open.spotify.com/intl-fr/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "37i9dQZF1DXcBWIGoYBM5M",
        ),
        ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DXcBWIGoYBM5M"),
        ("37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DXcBWIGoYBM5M"),
    ],
)
def test_parse_playlist_id_accepts_all_forms(input_str: str, expected_id: str) -> None:
    assert parse_playlist_id(input_str) == expected_id


def test_parse_playlist_id_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_playlist_id("https://example.com/foo")
    with pytest.raises(ValueError):
        parse_playlist_id("not an id with spaces!")


def test_pkce_verifier_length_bounds() -> None:
    """RFC 7636 §4.1 mandates 43 ≤ length ≤ 128."""
    with pytest.raises(ValueError):
        make_code_verifier(length=42)
    with pytest.raises(ValueError):
        make_code_verifier(length=129)
    v = make_code_verifier(length=64)
    assert len(v) == 64


def test_pkce_challenge_matches_rfc7636() -> None:
    """Challenge MUST equal BASE64URL(SHA256(verifier)) without padding."""
    v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 §A.1 example
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert code_challenge_from(v) == expected
