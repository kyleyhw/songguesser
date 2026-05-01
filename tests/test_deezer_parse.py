"""Direct tests for Deezer payload parsing (no network)."""

from __future__ import annotations

import httpx
import pytest
import respx

from songguesser.deezer import DEEZER_API, DeezerClient


@pytest.mark.asyncio
async def test_playlist_paginates_until_next_is_null() -> None:
    """Deezer's `/playlist/{id}/tracks` uses a `next` cursor; we follow it
    until it disappears."""
    page1 = {
        "data": [
            {
                "id": 1,
                "title": "T1",
                "isrc": "X1",
                "duration": 200,
                "preview": "https://cdn/p1.mp3",
                "artist": {"name": "A1"},
                "album": {"cover_big": "https://cdn/a1.jpg"},
            },
        ],
        "next": "https://api.deezer.com/playlist/123/tracks?index=25",
    }
    page2 = {
        "data": [
            {
                "id": 2,
                "title": "T2",
                "isrc": "X2",
                "duration": 200,
                "preview": "https://cdn/p2.mp3",
                "artist": {"name": "A2"},
                "album": {"cover_big": "https://cdn/a2.jpg"},
            },
        ],
        # No `next` => listing exhausted.
    }
    pl_payload = {
        "id": 123,
        "title": "My playlist",
        "tracks": page1,
    }
    async with httpx.AsyncClient(base_url=DEEZER_API) as h, respx.mock() as mock:
        mock.get(f"{DEEZER_API}/playlist/123").mock(
            return_value=httpx.Response(200, json=pl_payload)
        )
        mock.get("https://api.deezer.com/playlist/123/tracks?index=25").mock(
            return_value=httpx.Response(200, json=page2)
        )
        deezer = DeezerClient(client=h)
        pl = await deezer.playlist(123)
        assert pl.name == "My playlist"
        assert [t.id for t in pl.tracks] == ["1", "2"]


@pytest.mark.asyncio
async def test_track_with_empty_preview_is_dropped() -> None:
    """Country-locked tracks have ``preview = ""``; they cannot be played."""
    payload = {
        "id": 1,
        "title": "Locked",
        "isrc": "X",
        "duration": 200,
        "preview": "",
        "artist": {"name": "A"},
        "album": {"cover_big": "c"},
    }
    async with httpx.AsyncClient(base_url=DEEZER_API) as h, respx.mock(base_url=DEEZER_API) as mock:
        mock.get("/track/1").mock(return_value=httpx.Response(200, json=payload))
        deezer = DeezerClient(client=h)
        assert await deezer.track_by_id(1) is None
