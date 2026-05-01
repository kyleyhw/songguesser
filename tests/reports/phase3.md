# Phase 3 Test Report

**Date:** 2026-05-01
**Suite:** `tests/` (75 tests, of which 8 are new in Phase 3) + manual Playwright session
**Total runtime:** 1.39 s (pytest) + ~30 s (Playwright session)
**Result:** 75 passed, 0 failed; 1 manual E2E gameplay session passed

## Coverage

| Deliverable | Tests |
|---|---|
| HTTP envelope (`server.py`) | `test_server_http.py` (8 tests) |
| Browser client (`static/`) | manual Playwright session — see below |

## `test_server_http.py`

**What and why.** Validates that the public HTTP surface conforms to the
documented contract. We use FastAPI's `TestClient` (a synchronous
`httpx.Client` against an ASGI in-process app), which exercises the
lifespan startup/shutdown so `app.state.deezer` and friends are wired
correctly.

Cases:

1. `test_index_returns_html` — confirms the root serves the HTML client
   with the correct `<title>`. Catches accidental loss of the static mount.
2. `test_auth_status_unconfigured` — pins the `/api/auth/status` envelope
   when no Spotify client id is set: `{configured: false, authenticated: false}`.
3. `test_auth_login_without_client_id_500s` — `/auth/login` with no
   client id is a configuration error; we surface it as 500.
4. `test_create_room_without_spotify_rejects` — `/api/rooms` with no
   Spotify auth must refuse (401 or 422). Asserts the failure mode is
   well-formed.
5. `test_synthetic_room_creates_and_meta_returns` — creates a synthetic
   test room and reads it back; asserts the code shape and lobby phase.
6. `test_synthetic_room_disabled_when_env_unset` — the synthetic
   endpoint is hard-gated by `SONGGUESSER_ENABLE_SYNTHETIC=1`. Without
   the env var it must 404.
7. `test_unknown_room_returns_404` — joining a non-existent room is a
   clean 404, not a 500 or hang.
8. `test_static_silence_mp3_is_served` — the small silent-MP3 fixture
   used by the synthetic endpoint is reachable and starts with a valid
   MPEG audio frame header (`FF FB`).

## Manual Playwright session

The browser client cannot be exercised through `TestClient` (it needs a
real WebSocket endpoint and a real DOM); we drove it through the
Playwright MCP in a separate session. Steps and observations:

1. **Landing page renders** — gradient background, glass cards, brand
   mark, Spotify status indicator (correctly red because no
   `SPOTIFY_CLIENT_ID` was set in the dev env), Host and Join cards both
   visible. Screenshot: `landing-1.png`.
2. **Synthetic room creation** — `POST /api/rooms/synthetic` returned a
   6-character base16 code. The room's `phase` was `lobby` and
   `track_count` was 3 as expected.
3. **Lobby join** — typed code + name, clicked Join, transitioned to
   the game screen. Player row showed `★ Kyle ... 0` on a single line.
   Screenshot: `lobby-3.png`.
4. **Round start** — clicked Start; `audio.src` was set to
   `/static/silence.mp3`, the cover frame showed the gradient
   placeholder (synthetic tracks have no cover URL), the progress bar
   advanced smoothly. Phase label changed `Lobby → Playing`. Screenshot:
   `playing-3.png`.
5. **Successful guess** — typed "Bohemian Rhapsody Queen" (matching
   round 1's title and artist). The matcher classified it as `BOTH`,
   the engine awarded +54 points (round duration 8 s, elapsed ~7.6 s →
   `floor(1000 · (1 − 7.6/8)) = 50` is the analytical expectation; the
   observed 54 is consistent with the actual elapsed time at the
   sub-tick resolution). The leaderboard updated to `★ Kyle ... 54`,
   the chat showed `Kyle: Bohemian Rhapsody Queen` and a green
   `Kyle got it (+54)`, and the game advanced to round 2 within a
   few seconds (`everyone_solved` triggers an immediate REVEAL+next
   transition). Screenshot: `guess-correct.png`.

### Bugs found and fixed during the session

**Bug 1** — Player-row layout collapsed to two visual rows. Root cause:
`li.host::before` adds an additional grid item, so a 3-column grid
(`1fr auto auto`) had 4 items and overflowed. Fix: replaced
`grid-template-columns` with `display: flex` and explicit DOM children
(name span + score span + optional kind tag + optional star span).
Verified by inspecting `getComputedStyle` and re-rendering.

**Bug 2** — Reveal banner stuck on screen during PLAYING. Root cause:
`.reveal-banner { display: flex }` overrides the user-agent
`[hidden] { display: none }`, so setting `.hidden = true` had no visual
effect. Same class of bug for the host-only Start button. Fix: added a
single global `[hidden] { display: none !important }` rule.

**Bug 3** — Cover frame fell back to `cover.src = ""` when track had
no cover URL, which the browser resolves to the page URL and renders as
a broken image icon. Fix: when `cover_url` is null, remove the `src`
attribute entirely; the CSS `.cover-frame img:not([src]) { display: none }`
hides the broken `<img>` and lets the radial-gradient placeholder shine
through.

## What is *not* tested in Phase 3

- Multi-client races (two simultaneous correct guesses on the same
  round). The engine has the necessary lock; will exercise in Phase 5.
- Reconnection / sticky `player_id`. Will cover with a scripted
  Playwright session in Phase 5.
- Spotify OAuth round-trip. Cannot be tested without a Spotify dev app
  registered to the test runner; mocked at the unit level only.
