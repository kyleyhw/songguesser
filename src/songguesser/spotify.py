"""Spotify Web API client (host-only PKCE OAuth) — playlist read only.

Scope and policy
----------------
This module reads playlist metadata only (track id / name / artist / ISRC).
No audio is ever fetched from Spotify. Audio playback is served from Deezer
(see ``deezer.py``) by joining on ISRC. We use this approach because
Spotify's Developer Policy III.2 prohibits "creating a game"; restricting
Spotify usage to a private host-only OAuth and sourcing audio elsewhere
keeps the application clear of Spotify's audio-sync prohibitions while
still letting the host browse their own playlists.

Auth flow
---------
PKCE (RFC 7636) is used because Spotify recommends it for desktop/CLI apps
and because it requires no client secret — well-suited for a hobby app the
user runs locally.

  1. Server generates ``code_verifier`` (43–128 chars, RFC 7636 §4.1).
  2. ``code_challenge = BASE64URL(SHA256(code_verifier))``.
  3. Browser is sent to ``/authorize?...&code_challenge=...&state=...``.
  4. Spotify redirects back to ``REDIRECT_URI?code=...&state=...``.
  5. Server POSTs to ``/api/token`` with ``code`` and ``code_verifier``.

Tokens are cached in-memory only; a refresh token is used to obtain new
access tokens silently for the host's session.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .models import Playlist, Track

log = logging.getLogger(__name__)

SPOTIFY_AUTH = "https://accounts.spotify.com"
SPOTIFY_API = "https://api.spotify.com/v1"
PLAYLIST_SCOPES = "playlist-read-private playlist-read-collaborative"

PLAYLIST_URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z]{2}/)?playlist/|spotify:playlist:)([A-Za-z0-9]+)",
)


class SpotifyError(RuntimeError):
    """Spotify returned an error or an unexpected response."""


def parse_playlist_id(url_or_id: str) -> str:
    """Accept a Spotify URL, URI, or bare ID and return the ID.

    Examples
    --------
    >>> parse_playlist_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
    '37i9dQZF1DXcBWIGoYBM5M'
    >>> parse_playlist_id("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
    '37i9dQZF1DXcBWIGoYBM5M'
    >>> parse_playlist_id("37i9dQZF1DXcBWIGoYBM5M")
    '37i9dQZF1DXcBWIGoYBM5M'
    """
    s = url_or_id.strip()
    m = PLAYLIST_URL_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]+", s):
        return s
    raise ValueError(f"Not a Spotify playlist URL/URI/ID: {url_or_id!r}")


# ---------------------------------------------------------------------------
# PKCE primitives
# ---------------------------------------------------------------------------


def _b64url(b: bytes) -> str:
    """RFC 7636 §3 base64url encoding without padding."""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def make_code_verifier(length: int = 64) -> str:
    """RFC 7636 §4.1: 43–128 chars from [A-Z][a-z][0-9]-._~."""
    if not 43 <= length <= 128:
        raise ValueError("code_verifier length must be 43..128")
    # token_urlsafe yields URL-safe chars; we trim to the requested length.
    raw = secrets.token_urlsafe(length)
    return raw[:length]


def code_challenge_from(verifier: str) -> str:
    """RFC 7636 §4.2: BASE64URL(SHA256(code_verifier))."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


# ---------------------------------------------------------------------------
# Token + client
# ---------------------------------------------------------------------------


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: float  # epoch seconds

    def is_expired(self, *, leeway: float = 30.0) -> bool:
        return time.time() + leeway >= self.expires_at


@dataclass
class PendingAuth:
    """Server-side state for an in-flight PKCE handshake."""

    state: str
    verifier: str
    created_at: float = field(default_factory=time.time)


class SpotifyClient:
    """Async Spotify client with PKCE OAuth.

    Designed for a single host user. Call ``begin_auth`` once to mint a state
    and verifier, redirect the host's browser to ``authorize_url``, then call
    ``complete_auth`` from the redirect handler.
    """

    def __init__(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"User-Agent": "songguesser/0.1"},
        )
        self._tokens: TokenSet | None = None
        self._pending: dict[str, PendingAuth] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- auth -------------------------------------------------------------------

    def begin_auth(self) -> str:
        """Returns the URL the host's browser must visit."""
        verifier = make_code_verifier()
        challenge = code_challenge_from(verifier)
        state = secrets.token_urlsafe(16)
        self._pending[state] = PendingAuth(state=state, verifier=verifier)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": PLAYLIST_SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        return f"{SPOTIFY_AUTH}/authorize?{httpx.QueryParams(params)}"

    async def complete_auth(self, *, code: str, state: str) -> None:
        pending = self._pending.pop(state, None)
        if pending is None:
            raise SpotifyError("Unknown or expired OAuth state")
        resp = await self._client.post(
            f"{SPOTIFY_AUTH}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": pending.verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise SpotifyError(f"Token exchange failed: {resp.status_code} {resp.text}")
        data = resp.json()
        self._tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + int(data.get("expires_in", 3600)),
        )

    @property
    def is_authenticated(self) -> bool:
        return self._tokens is not None

    async def _ensure_token(self) -> str:
        if self._tokens is None:
            raise SpotifyError("Not authenticated. Call begin_auth/complete_auth first.")
        if self._tokens.is_expired():
            await self._refresh()
        assert self._tokens is not None
        return self._tokens.access_token

    async def _refresh(self) -> None:
        if self._tokens is None or self._tokens.refresh_token is None:
            raise SpotifyError("No refresh token; re-authenticate.")
        resp = await self._client.post(
            f"{SPOTIFY_AUTH}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._tokens.refresh_token,
                "client_id": self.client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise SpotifyError(f"Token refresh failed: {resp.status_code} {resp.text}")
        data = resp.json()
        self._tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", self._tokens.refresh_token),
            expires_at=time.time() + int(data.get("expires_in", 3600)),
        )

    # -- API --------------------------------------------------------------------

    async def _api_get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._ensure_token()
        resp = await self._client.get(
            f"{SPOTIFY_API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            await self._refresh()
            token = await self._ensure_token()
            resp = await self._client.get(
                f"{SPOTIFY_API}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    async def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Return raw track dicts: ``{name, artists[].name, external_ids.isrc}``.

        Resolution to Deezer happens in :mod:`songguesser.resolver`.
        """
        items: list[dict[str, Any]] = []
        # Spotify's Feb-2026 dev-mode changes restrict /tracks batch endpoint but
        # /playlists/{id}/tracks remains available. We page using next links.
        # https://developer.spotify.com/documentation/web-api/reference/get-playlists-tracks
        next_url: str | None = None
        params: dict[str, Any] | None = {
            "fields": (
                "items(track(name,external_ids.isrc,artists(name),id,duration_ms)),next"
            ),
            "limit": 100,
        }
        path: str | None = f"/playlists/{playlist_id}/tracks"
        while path:
            data = await self._api_get(path, params=params)
            for entry in data.get("items", []):
                track = entry.get("track")
                if track is not None:
                    items.append(track)
            next_url = data.get("next")
            if next_url:
                # `next` is an absolute URL; strip the API base and re-use _api_get.
                path = next_url[len(SPOTIFY_API) :] if next_url.startswith(SPOTIFY_API) else None
                params = None  # everything is encoded in `next`
            else:
                path = None
        return items

    async def playlist_meta(self, playlist_id: str) -> dict[str, Any]:
        return await self._api_get(
            f"/playlists/{playlist_id}",
            params={"fields": "id,name,owner.display_name"},
        )


def spotify_to_track_stub(raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Spotify track dict to the keys the resolver consumes."""
    artists = raw.get("artists") or []
    artist = artists[0]["name"] if artists else ""
    return {
        "spotify_id": raw.get("id"),
        "title": raw.get("name") or "",
        "artist": artist,
        "isrc": (raw.get("external_ids") or {}).get("isrc"),
        "duration_ms": raw.get("duration_ms"),
    }


def empty_playlist(name: str, source_id: str) -> Playlist:
    """A placeholder Playlist used when Spotify returns metadata but resolution
    has not run yet. Useful for the lobby UI which displays a name immediately."""
    return Playlist(source="spotify", source_id=source_id, name=name, tracks=())


__all__ = [
    "PLAYLIST_URL_RE",
    "PendingAuth",
    "SpotifyClient",
    "SpotifyError",
    "Track",
    "code_challenge_from",
    "empty_playlist",
    "make_code_verifier",
    "parse_playlist_id",
    "spotify_to_track_stub",
]
