# Phase 5: Final Test Report (consolidated)

**Date:** 2026-05-01
**Suite:** `tests/` (80 tests, of which 5 are new in Phase 5)
**Total runtime:** 1.46 s
**Result:** 80 passed, 0 failed

## Per-module breakdown

| Module | Tests | Coverage focus |
|---|---|---|
| `test_models.py` | 7 | Domain immutability, monotonic timing, leaderboard ordering. |
| `test_spotify_parse.py` | 8 | Spotify URL/URI/ID parser; PKCE primitives anchored to RFC 7636 §A.1. |
| `test_resolver.py` | 12 | Normalisation, similarity, ISRC primary, fuzzy fallback, threshold pin. |
| `test_deezer_parse.py` | 2 | Pagination via `next` cursor; country-locked tracks dropped. |
| `test_scoring.py` | 10 | Linear curve at boundaries, lattice transitions, no-double-pay, monotonicity. |
| `test_reveal.py` | 6 | Pixelation/blur monotonicity, JPEG output validity, parameter sensitivity. |
| `test_matcher.py` | 12 | Title/artist/both classification, remaster/diacritic robustness, threshold. |
| `test_engine.py` | 10 | Lobby→playing, host election, scoring, everyone-solved signal. |
| `test_server_http.py` | 8 | HTTP envelope, auth status, synthetic-room gating. |
| `test_server_ws.py` | 5 | WebSocket lobby/play/guess/reveal flow, ping/pong, error path, host gating. |

## What was new in Phase 5

### `test_server_ws.py` — 5 tests

The key gap before Phase 5 was end-to-end coverage of the WebSocket
protocol. FastAPI's `TestClient` wraps `httpx`'s WebSocket-over-ASGI
support, so we can drive the server entirely in-process. New tests:

1. `test_lobby_and_round_flow` — two clients (Alice host, Bob guest)
   join a synthetic room with `round_seconds=10, reveal_seconds=0.1`.
   Both receive a `state` envelope on join. Alice starts; both receive
   `round_start`. Alice submits "Bohemian Rhapsody Queen" (the round 0
   track), and a `guess_result` arrives with `kind="both"` and
   `points > 0`. This is the primary integration check; if the engine
   regresses on any of model wiring, message dispatch, or scoring, this
   test fails.

2. `test_unknown_room_closes_websocket` — connecting to room `ZZZZZZ`
   raises `WebSocketDisconnect`. Pins the close-on-not-found path so a
   future refactor cannot silently accept unknown rooms.

3. `test_non_host_cannot_start` — Bob (the second player) sends a
   `start` message; the server replies with an `error` whose message
   contains "host". This covers the host-only authorisation check.

4. `test_ping_pong` — keepalive round-trip. Trivial but pins the wire
   format.

5. `test_bad_message_returns_error` — malformed JSON (`"not json at all"`)
   yields an `error` message rather than crashing the WebSocket. Pins
   the validation envelope.

### Performance fix discovered during Phase 5

The first WS test run took 64 s wall-clock because of three issues:

- The synthetic room defaulted to `round_seconds=8.0`; multiple tests
  re-instantiated rooms whose runners outlived the test assertions.
- Even after asserting and exiting `with websocket_connect(...)`, the
  TestClient lifespan teardown waited for in-flight runner tasks to
  finish their tick loops.
- One test used `round_seconds=30`.

Fix: in the lifespan `finally` block, cancel any in-flight `entry.runner`
tasks before closing the HTTP/Deezer/Spotify clients. New tests use
`round_seconds=1, reveal_seconds=0.1` (short enough to never block).
After both fixes: full suite runs in **1.46 s**.

## Linting and types

- `uv run ruff check .` → All checks passed.
- `uv run ty check` → not yet run in CI (not part of the suite); the
  pre-commit hook is configured to invoke it. Adding it as a CI gate is
  a follow-up.

## Test data rationale

- **Synthetic playlist** — `[("Bohemian Rhapsody", "Queen"), ("Hello",
  "Adele"), ("Believer", "Imagine Dragons")]`. Three universally-known
  tracks across rock, pop, alternative — diverse enough to exercise the
  matcher's normalisation across genres without depending on any third-
  party network for tests.
- **PKCE verifier** — RFC 7636 §A.1's canonical example
  `dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk`. Anchoring the test to
  the RFC removes any ambiguity about base64url encoding.
- **Deezer ISRC fixture** — `USRC17607839` (Adele's "Hello"). This is a
  real, well-known ISRC; tests mock the response so no network is hit.

## What is still untested

- **Reconnection sticky-state** under simulated network drop. The code
  path exists (`reconnect_player` preserves score) but no test drives a
  socket close + reconnect.
- **Concurrent guesses** in the same round from two clients hitting
  simultaneously. The engine has a per-room `asyncio.Lock`; an explicit
  test for ordering would harden the contract.
- **Spotify OAuth round-trip.** Cannot be unit-tested without a real
  Spotify dev app. PKCE primitives and URL parsing are unit-tested; the
  HTTP exchange is mocked at the transport level only.
- **Cloudflare Tunnel and mDNS.** These are infra integrations; tested
  by manual dogfooding rather than automation.

## Summary

| Phase | New tests | Cumulative | Runtime |
|---|---|---|---|
| 1 | 29 | 29 | 0.25 s |
| 2 | 38 | 67 | 0.60 s |
| 3 | 8 | 75 | 1.39 s |
| 5 | 5 | 80 | **1.46 s** |

(Phase 4 added the LAN/networking modules and documentation; no new
tests were appropriate.)
