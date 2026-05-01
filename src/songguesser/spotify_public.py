"""Public Spotify playlist parser — no OAuth, no developer app required.

We fetch ``https://open.spotify.com/embed/playlist/{id}`` (a public iframe
endpoint Spotify uses for embedding) and parse the embedded
``__NEXT_DATA__`` JSON blob. This blob contains the full track list with
title, artist, duration, and a 30-second `audioPreview.url` served from
Spotify's own CDN at ``p.scdn.co``. Per-track album covers are obtained
lazily from each track's public page via the ``og:image`` meta tag.

This approach has no auth, no client id, no quota.

Caveats:
  * It is technically scraping a public web page; the structure can
    change without notice. We pin the few fields we depend on and fail
    loudly when the schema drifts.
  * Some tracks have ``audioPreview = None`` (regional / takedown);
    those are dropped from the playlist before play.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from .models import Playlist, Track
from .spotify import parse_playlist_id as _parse_playlist_id

log = logging.getLogger(__name__)

EMBED_URL = "https://open.spotify.com/embed/playlist/{id}"
TRACK_PAGE_URL = "https://open.spotify.com/track/{id}"
USER_AGENT = "Mozilla/5.0 (compatible; songguesser/0.1)"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
_OG_IMAGE_RE = re.compile(r'<meta property="og:image" content="([^"]+)"')

parse_playlist_id = _parse_playlist_id  # re-export for callers


class SpotifyPublicError(RuntimeError):
    """Raised when the embed page is missing or its schema has drifted."""


async def fetch_playlist(
    url_or_id: str, *, enrich_covers: bool = True, cover_concurrency: int = 20
) -> Playlist:
    """Return a Playlist parsed from the public Spotify embed page.

    Parameters
    ----------
    url_or_id
        A Spotify playlist URL, URI, or bare ID.
    enrich_covers
        When True (default), fetch each track's album cover concurrently
        from the track's public page via the ``og:image`` meta. When
        False, ``Track.cover_url`` is left as None.
    cover_concurrency
        Maximum simultaneous cover fetches.
    """
    playlist_id = parse_playlist_id(url_or_id)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=True,
    ) as client:
        resp = await client.get(EMBED_URL.format(id=playlist_id))
        resp.raise_for_status()
        data = _extract_next_data(resp.text)
        try:
            entity = data["props"]["pageProps"]["state"]["data"]["entity"]
        except (KeyError, TypeError) as exc:
            raise SpotifyPublicError(f"unexpected embed schema: {exc}") from exc

        playlist_name = str(entity.get("title") or entity.get("name") or "Spotify playlist")
        playlist_cover = _extract_playlist_cover(entity)
        raw_tracks = entity.get("trackList") or []

        tracks_partial = [_parse_track(raw, fallback_cover=playlist_cover) for raw in raw_tracks]
        tracks_partial = [t for t in tracks_partial if t is not None]

        if enrich_covers and tracks_partial:
            tracks_partial = await _enrich_covers(client, tracks_partial, cover_concurrency)

        return Playlist(
            source="spotify",
            source_id=playlist_id,
            name=playlist_name,
            tracks=tuple(tracks_partial),
        )


def _extract_next_data(html: str) -> dict[str, Any]:
    m = _NEXT_DATA_RE.search(html)
    if m is None:
        raise SpotifyPublicError("__NEXT_DATA__ blob not found in embed page")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise SpotifyPublicError(f"__NEXT_DATA__ is not valid JSON: {exc}") from exc


def _extract_playlist_cover(entity: dict[str, Any]) -> str | None:
    cover = entity.get("coverArt") or {}
    sources = cover.get("sources") or []
    for src in sources:
        u = src.get("url")
        if u:
            return str(u)
    return None


def _parse_track(raw: dict[str, Any], *, fallback_cover: str | None) -> Track | None:
    """Build a Track from an embed-JSON track entry. Skips unplayable items."""
    audio = raw.get("audioPreview") or {}
    preview_url = audio.get("url")
    if not preview_url:
        return None
    title = str(raw.get("title") or "").strip()
    subtitle = str(raw.get("subtitle") or "").strip()
    if not title or not subtitle:
        return None
    track_uri = raw.get("uri") or ""
    track_id = track_uri.rsplit(":", 1)[-1] if ":" in track_uri else str(raw.get("uid") or title)
    duration_ms = raw.get("duration") if isinstance(raw.get("duration"), int) else None
    return Track(
        id=track_id,
        title=title,
        artist=subtitle,
        isrc=None,  # not exposed in the public embed
        preview_url=str(preview_url),
        cover_url=fallback_cover,  # replaced by per-track cover below if enriched
        duration_ms=duration_ms,
    )


async def _enrich_covers(
    client: httpx.AsyncClient, tracks: list[Track], concurrency: int
) -> list[Track]:
    """Fetch each track's ``og:image`` from its public page concurrently."""
    sem = asyncio.Semaphore(concurrency)

    async def _fetch_one(t: Track) -> Track:
        async with sem:
            try:
                r = await client.get(TRACK_PAGE_URL.format(id=t.id))
                if r.status_code == 200:
                    m = _OG_IMAGE_RE.search(r.text)
                    if m:
                        return t.model_copy(update={"cover_url": m.group(1)})
            except httpx.HTTPError as exc:
                log.debug("cover fetch failed for %s: %s", t.id, exc)
        return t

    return list(await asyncio.gather(*(_fetch_one(t) for t in tracks)))
