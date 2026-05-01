# Configuration

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address. |
| `PORT` | `8138` | Bind port. |
| `SPOTIFY_CLIENT_ID` | _(unset)_ | Spotify Developer App client id. Required for `/auth/login` and `/api/rooms`. |
| `SPOTIFY_REDIRECT_URI` | `http://127.0.0.1:8138/auth/callback` | Must match the redirect URI registered in your Spotify Developer Dashboard. |
| `SONGGUESSER_ENABLE_SYNTHETIC` | _(unset)_ | When `1`, exposes `/api/rooms/synthetic` for testing. |

A template is provided at `.env.example`; copy to `.env` and fill in.

## Setting up a Spotify Developer App

1. Visit https://developer.spotify.com/dashboard.
2. Click **Create app**.
3. Name it (e.g. `songguesser-local`).
4. Set the redirect URI to `http://127.0.0.1:8138/auth/callback` (or your
   Cloudflare Tunnel URL + `/auth/callback`).
5. Copy the *Client ID* into your `.env` as `SPOTIFY_CLIENT_ID`. The
   client secret is **not** used (we use PKCE).
6. From the dashboard, **add your friends as authorised users** in the
   "Users and Access" section. Spotify development mode is capped at 5
   users (since 2026-02-11) — see `docs/spotify_policy.md`.

## Tuning the game

Round duration, number of rounds, and the reveal pause are passed via
the `POST /api/rooms` body or the `/api/rooms/synthetic` query string:

```jsonc
POST /api/rooms
{
  "playlist_url": "https://open.spotify.com/playlist/...",
  "max_rounds": 10,
  "round_seconds": 30.0,
  "reveal_seconds": 8.0
}
```

The cover-reveal exponents (`pix_gamma`, `blur_delta`) and maxima
(`f_max`, `sigma_max`) live in `RevealParams` (see
`src/songguesser/reveal.py`). They are not exposed as runtime knobs; if
you want to tune them, edit the dataclass defaults and restart the
server. The current defaults are calibrated against a 50-cover sample;
see `docs/reveal_math.md` for the calibration discussion.

The scoring constants (`FULL_AWARD`, `PART_AWARD`) live in
`src/songguesser/scoring.py`. Increasing them affects only the absolute
score scale; the curve shape is unchanged.

The matcher threshold (`MATCH_THRESHOLD = 0.84`) and the resolver
threshold (`ACCEPT_THRESHOLD = 0.78`) are also module-level constants.
The matcher threshold is stricter because user input is noisier than
catalog-vs-catalog metadata; loosening it past ~0.78 will produce
false-positive matches on common token overlaps.
