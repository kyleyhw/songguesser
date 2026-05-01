"""Deezer API client (anonymous, public endpoints only).

Deezer's public API does not require authentication for catalog reads, so all
calls in this module are unauthenticated GETs against `api.deezer.com`. The
endpoints we depend on:

  GET /track/{id}                — single track
  GET /track/isrc:{isrc}          — track lookup by ISRC (cross-catalog key)
  GET /search/track?q=...         — fuzzy search fallback
  GET /playlist/{id}              — playlist + first page of tracks
  GET /playlist/{id}/tracks       — paged tracks (index, limit)

Pagination on `/playlist/{id}/tracks` follows Deezer's `next` link convention;
when `next` is absent the listing is exhausted.

All methods are async (`httpx.AsyncClient`) so the FastAPI server can fan out
N parallel ISRC lookups without blocking the event loop.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

from .models import Playlist, Track

log = logging.getLogger(__name__)

DEEZER_API = "https://api.deezer.com"


class DeezerError(RuntimeError):
    """Raised when Deezer returns an error payload or unparseable response."""


def _parse_track(raw: dict[str, Any]) -> Track | None:
    """Map a raw Deezer track JSON object into our domain `Track`.

    Returns ``None`` when the track is not playable for our purposes — i.e.
    when Deezer omits the `preview` URL (some country-locked tracks have an
    empty string in that field).
    """
    preview = raw.get("preview") or ""
    if not preview:
        return None
    artist = (raw.get("artist") or {}).get("name") or ""
    album = raw.get("album") or {}
    cover = album.get("cover_big") or album.get("cover_medium") or album.get("cover") or None
    duration_seconds = raw.get("duration")
    duration_ms = int(duration_seconds) * 1000 if isinstance(duration_seconds, int) else None
    return Track(
        id=str(raw["id"]),
        title=raw.get("title") or raw.get("title_short") or "",
        artist=artist,
        isrc=raw.get("isrc"),
        preview_url=preview,
        cover_url=cover,
        duration_ms=duration_ms,
    )


class DeezerClient:
    """Async Deezer client. Reuse one instance per process; share its session."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=DEEZER_API,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"User-Agent": "songguesser/0.1"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> DeezerClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- catalog ----------------------------------------------------------------

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise DeezerError(f"Deezer error on {path}: {data['error']}")
        return data

    async def track_by_id(self, track_id: str | int) -> Track | None:
        data = await self._get(f"/track/{track_id}")
        return _parse_track(data)

    async def track_by_isrc(self, isrc: str) -> Track | None:
        """Cross-catalog lookup. Returns ``None`` when no track is found.

        Deezer responds with `{"error": {"type": "DataException", "code": 800}}`
        for unknown ISRCs. We catch that specific case and return ``None``.
        """
        try:
            data = await self._get(f"/track/isrc:{quote_plus(isrc)}")
        except DeezerError as exc:
            if "code': 800" in repr(exc) or "code\": 800" in repr(exc):
                return None
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return _parse_track(data)

    async def search_track(self, *, artist: str, title: str, limit: int = 5) -> list[Track]:
        """Fuzzy fallback when ISRC lookup fails.

        Deezer's advanced search syntax allows separate `artist:` and `track:`
        terms — much more reliable than free-text search. Quotes are stripped
        because they are control characters in the search DSL.
        """
        query = f'artist:"{_strip_quotes(artist)}" track:"{_strip_quotes(title)}"'
        data = await self._get("/search/track", params={"q": query, "limit": limit})
        return [t for raw in data.get("data", []) if (t := _parse_track(raw)) is not None]

    # -- playlists --------------------------------------------------------------

    async def playlist(self, playlist_id: str | int) -> Playlist:
        data = await self._get(f"/playlist/{playlist_id}")
        tracks_section = data.get("tracks") or {}
        raws = list(tracks_section.get("data") or [])
        # Follow pagination if Deezer reports more tracks than the first page.
        next_url = tracks_section.get("next")
        while next_url:
            page = await self._get_absolute(next_url)
            raws.extend(page.get("data") or [])
            next_url = page.get("next")
        tracks = tuple(t for raw in raws if (t := _parse_track(raw)) is not None)
        return Playlist(
            source="deezer",
            source_id=str(data["id"]),
            name=str(data.get("title") or "Untitled playlist"),
            tracks=tracks,
        )

    async def _get_absolute(self, url: str) -> dict[str, Any]:
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()


def _strip_quotes(s: str) -> str:
    return s.replace('"', "").replace("“", "").replace("”", "")
