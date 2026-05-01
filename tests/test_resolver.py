"""Resolver tests with mocked Deezer responses (respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from songguesser.deezer import DEEZER_API, DeezerClient
from songguesser.resolver import (
    ACCEPT_THRESHOLD,
    normalize,
    resolve_many,
    resolve_one,
    similarity,
)


def _deezer_track_payload(
    *,
    id: int = 1,
    title: str = "Title",
    artist: str = "Artist",
    isrc: str | None = "ABCDE1234567",
) -> dict:
    return {
        "id": id,
        "title": title,
        "isrc": isrc,
        "duration": 210,
        "preview": "https://cdn.example/preview.mp3",
        "artist": {"id": 1, "name": artist},
        "album": {
            "id": 1,
            "title": "Album",
            "cover": "https://cdn.example/cover.jpg",
            "cover_big": "https://cdn.example/cover_big.jpg",
            "cover_medium": "https://cdn.example/cover_medium.jpg",
        },
    }


# ---- normalize ----------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Café", "cafe"),
        ("Don't Stop Me Now (Remastered 2011)", "don t stop me now"),
        ("Hello - 2009 Remaster", "hello"),
        ("Believer (feat. Lil Wayne)", "believer"),
        ("  multiple   spaces  ", "multiple spaces"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# ---- similarity ---------------------------------------------------------------

def test_similarity_self_is_one() -> None:
    assert similarity("Imagine Dragons", "Imagine Dragons") == 1.0


def test_similarity_with_remaster_tag_still_high() -> None:
    s = similarity("Don't Stop Me Now (Remastered 2011)", "Don't Stop Me Now")
    assert s >= 0.95


# ---- resolve_one (network mocked) ---------------------------------------------

@pytest.mark.asyncio
async def test_resolve_one_isrc_hit() -> None:
    async with httpx.AsyncClient(base_url=DEEZER_API) as h, respx.mock(base_url=DEEZER_API) as mock:
        mock.get("/track/isrc:USRC17607839").mock(
            return_value=httpx.Response(200, json=_deezer_track_payload(title="Hello"))
        )
        deezer = DeezerClient(client=h)
        track, mode = await resolve_one(
            deezer,
            {"isrc": "USRC17607839", "artist": "Adele", "title": "Hello"},
        )
        assert mode == "isrc"
        assert track is not None and track.title == "Hello"


@pytest.mark.asyncio
async def test_resolve_one_isrc_miss_falls_back_to_search() -> None:
    async with httpx.AsyncClient(base_url=DEEZER_API) as h, respx.mock(base_url=DEEZER_API) as mock:
        # ISRC lookup returns Deezer's "no data" error envelope.
        mock.get("/track/isrc:UNKNOWN0001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "error": {
                        "type": "DataException",
                        "message": "no data",
                        "code": 800,
                    }
                },
            )
        )
        mock.get("/search/track").mock(
            return_value=httpx.Response(
                200,
                json={"data": [_deezer_track_payload(title="Hello", artist="Adele")]},
            )
        )
        deezer = DeezerClient(client=h)
        track, mode = await resolve_one(
            deezer,
            {"isrc": "UNKNOWN0001", "artist": "Adele", "title": "Hello"},
        )
        assert mode == "search"
        assert track is not None


@pytest.mark.asyncio
async def test_resolve_one_search_below_threshold_is_unresolved() -> None:
    async with httpx.AsyncClient(base_url=DEEZER_API) as h, respx.mock(base_url=DEEZER_API) as mock:
        mock.get("/search/track").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _deezer_track_payload(
                            title="Completely Different Title",
                            artist="Unrelated Artist",
                        )
                    ]
                },
            )
        )
        deezer = DeezerClient(client=h)
        track, mode = await resolve_one(
            deezer,
            {"isrc": None, "artist": "Adele", "title": "Hello"},
        )
        assert mode == "unresolved" and track is None


@pytest.mark.asyncio
async def test_resolve_many_concurrency_and_stats() -> None:
    """Resolver should batch-process and produce accurate stats."""
    payload_isrc_hit = _deezer_track_payload(title="Track A", isrc="A")
    async with httpx.AsyncClient(base_url=DEEZER_API) as h, respx.mock(base_url=DEEZER_API) as mock:
        mock.get("/track/isrc:A").mock(
            return_value=httpx.Response(200, json=payload_isrc_hit)
        )
        mock.get("/track/isrc:B").mock(
            return_value=httpx.Response(
                200,
                json={"error": {"type": "DataException", "code": 800}},
            )
        )
        # B falls through to search and finds a good match.
        mock.get("/search/track").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [_deezer_track_payload(title="Track B", artist="Artist B")]
                },
            )
        )
        deezer = DeezerClient(client=h)
        stubs = [
            {"isrc": "A", "artist": "Artist A", "title": "Track A"},
            {"isrc": "B", "artist": "Artist B", "title": "Track B"},
            {"isrc": None, "artist": "", "title": ""},  # unresolved
        ]
        tracks, stats = await resolve_many(deezer, stubs, concurrency=2)
        assert stats.total == 3
        assert stats.by_isrc == 1
        assert stats.by_search == 1
        assert stats.unresolved == 1
        assert len(tracks) == 2


def test_threshold_is_documented() -> None:
    """The accept threshold is a knob that gameplay quality depends on; lock
    it down so a future change is intentional and reviewed."""
    assert ACCEPT_THRESHOLD == 0.78
