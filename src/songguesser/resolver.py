"""Spotify-track-stub -> Deezer-Track resolution.

Strategy
--------
1. **ISRC join** (primary). Both catalogs publish the International Standard
   Recording Code on each track; this is the only key that uniquely
   identifies a *recording* across catalogs (not just the work). When
   Deezer has a hit on ``GET /track/isrc:{isrc}`` we accept it directly.

2. **Fuzzy fallback**. When the Spotify track has no ISRC (sometimes true
   for podcasts, very recent releases, or local files), or Deezer returns
   404 for the ISRC, we fall back to a constrained search:

       artist:"<artist>" track:"<title>"

   We score each candidate by

       s = α · sim(artist) + β · sim(title)

   where ``sim`` is the normalized indel similarity from rapidfuzz
   (``rapidfuzz.fuzz.token_set_ratio / 100``) and ``α + β = 1`` with
   ``α = 0.4``, ``β = 0.6`` — title carries slightly more weight because
   featuring/remaster tags inflate artist false-positives more than title
   ones. The best candidate is accepted iff ``s ≥ 0.78``; otherwise the
   track is dropped from the playlist (caller can decide whether to surface
   a "could-not-resolve" warning to the user).

The 0.78 threshold was chosen empirically (see
``docs/resolver_threshold.md``) to balance recall against the cost of
false matches, which would harm gameplay by playing the wrong song.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from .deezer import DeezerClient
from .models import Track

log = logging.getLogger(__name__)

ARTIST_WEIGHT = 0.4
TITLE_WEIGHT = 0.6
ACCEPT_THRESHOLD = 0.78

# Strip parenthesised tags that frequently differ across catalogs.
# Examples: "(Remastered 2011)", "(feat. ...)", "- 2009 Remaster",
# "(Deluxe Edition)". These survive verbatim into title strings on Spotify
# but are routinely cleaned on Deezer (or vice versa).
_TAG_RE = re.compile(
    r"""
    \s*[\(\[]\s*(?:feat|featuring|with|prod|remaster(?:ed)?|deluxe|bonus|live|edit|version|mix|remix|instrumental|acoustic)
    \b[^)\]]*[\)\]]\s*
    | \s*-\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|edit|version|mix|remix|instrumental|acoustic)\b.*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize(s: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, drop edition tags."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _TAG_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


def similarity(a: str, b: str) -> float:
    """Normalized similarity in [0, 1]. Uses token_set_ratio: order-insensitive
    and resilient to one string having extra tokens (common with featuring
    artists or remaster suffixes)."""
    return fuzz.token_set_ratio(normalize(a), normalize(b)) / 100.0


@dataclass
class ResolutionStats:
    total: int = 0
    by_isrc: int = 0
    by_search: int = 0
    unresolved: int = 0


async def resolve_one(
    deezer: DeezerClient, stub: dict[str, Any]
) -> tuple[Track | None, str]:
    """Try to resolve a single Spotify stub. Returns (track, mode).

    `mode` is one of ``isrc | search | unresolved`` for telemetry.
    """
    isrc = stub.get("isrc")
    if isrc:
        try:
            t = await deezer.track_by_isrc(isrc)
            if t is not None:
                return t, "isrc"
        except Exception as exc:
            log.debug("ISRC lookup failed for %s: %s", isrc, exc)

    artist = stub.get("artist") or ""
    title = stub.get("title") or ""
    if not artist or not title:
        return None, "unresolved"
    candidates = await deezer.search_track(artist=artist, title=title, limit=5)
    if not candidates:
        return None, "unresolved"
    best, best_score = None, 0.0
    for c in candidates:
        score = ARTIST_WEIGHT * similarity(c.artist, artist) + TITLE_WEIGHT * similarity(
            c.title, title
        )
        if score > best_score:
            best, best_score = c, score
    if best is not None and best_score >= ACCEPT_THRESHOLD:
        return best, "search"
    return None, "unresolved"


async def resolve_many(
    deezer: DeezerClient, stubs: list[dict[str, Any]], *, concurrency: int = 8
) -> tuple[list[Track], ResolutionStats]:
    """Resolve a batch of Spotify stubs concurrently.

    `concurrency` caps simultaneous Deezer calls. Deezer rate-limits at
    ~50 req / 5 s per IP for unauthenticated calls (per their forum FAQ);
    8 in-flight calls keeps us well under that without leaving capacity on
    the table.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _bound(stub: dict[str, Any]) -> tuple[Track | None, str]:
        async with sem:
            return await resolve_one(deezer, stub)

    results = await asyncio.gather(*(_bound(s) for s in stubs))
    tracks: list[Track] = []
    stats = ResolutionStats(total=len(stubs))
    for track, mode in results:
        if track is None:
            stats.unresolved += 1
            continue
        tracks.append(track)
        if mode == "isrc":
            stats.by_isrc += 1
        elif mode == "search":
            stats.by_search += 1
    return tracks, stats
