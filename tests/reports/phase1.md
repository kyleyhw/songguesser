# Phase 1 Test Report

**Date:** 2026-05-01
**Suite:** `tests/` (29 tests)
**Total runtime:** 0.25 s
**Result:** 29 passed, 0 failed

## Coverage of Phase 1 deliverables

| Deliverable | Tests |
|---|---|
| Data models (`models.py`) | `test_models.py` (7 tests) |
| Deezer client (`deezer.py`) | `test_deezer_parse.py` (2 tests) |
| Spotify URL parser & PKCE primitives (`spotify.py`) | `test_spotify_parse.py` (8 tests) |
| Spotify→Deezer resolver (`resolver.py`) | `test_resolver.py` (12 tests) |

## What was tested and why

### `test_models.py`
**What.** Verifies that `Track` is immutable (Pydantic `frozen=True`), that
`Playlist.with_tracks` returns a new instance without mutating the original,
that `Round.elapsed` and `Round.progress` behave correctly under
`time.monotonic()`, and that `Room.leaderboard` orders by score descending
with case-insensitive name as the tiebreaker.

**Why.** The domain layer is the foundation of everything downstream; bugs
here would surface as gameplay errors that are hard to diagnose. The
immutability tests are particularly important because multiple coroutines
read `Track`/`Playlist` concurrently.

**Inputs.** Synthetic `Track` instances built by `_track(i)`. Three players
with scores `[10, 20, 20]` and names `["Alice", "bob", "Carol"]` exercise
both the score ordering and the case-insensitive name tiebreak.

### `test_spotify_parse.py`
**What.** Exhaustively tests `parse_playlist_id` against five URL/URI/ID
shapes Spotify uses in the wild (including `intl-fr/` localised paths and
`?si=` share suffixes). Verifies the PKCE verifier length bounds (RFC 7636
§4.1) and confirms `code_challenge_from` is bit-exact equal to
`BASE64URL(SHA256(verifier))` using the canonical example from RFC 7636 §A.1
(verifier = `dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk`).

**Why.** A wrong PKCE challenge breaks OAuth silently. Anchoring the test
to the RFC's own example eliminates any ambiguity about the encoding.

### `test_resolver.py`
**What.** Five categories:
1. `normalize` — five parametrised cases: diacritics, parenthesised
   remaster tags, dash-suffix remaster tags, `feat.` tags, multi-space.
2. `similarity` — self-similarity equals 1.0; remaster tag does not crater
   similarity (≥ 0.95 vs the clean title).
3. `resolve_one` ISRC hit path (mocked Deezer returns 200).
4. `resolve_one` ISRC miss → search fallback (mocked Deezer returns the
   `code: 800` "no data" envelope on ISRC, then a successful search).
5. `resolve_one` search-below-threshold path (low-similarity result).
6. `resolve_many` correctness and stats (one ISRC hit, one search hit, one
   unresolved; verifies `ResolutionStats` counts match exactly).
7. A regression-guard that pins `ACCEPT_THRESHOLD == 0.78`.

**Why.** Resolution is the gameplay-critical step: a wrong join plays the
wrong song and breaks the round. The threshold pin forces a future change
to be intentional and reviewed.

**Inputs chosen because.**
- `"Hello"` by Adele (ISRC `USRC17607839`) is a well-known recording with
  a documented ISRC, useful for memorability.
- `"Don't Stop Me Now (Remastered 2011)"` and `"Hello - 2009 Remaster"`
  exercise both parenthesised and dash-suffix forms of remaster tags.

### `test_deezer_parse.py`
**What.** Pagination via the `next` cursor (single page → `next` →
exhausted), and the rule that tracks with empty `preview` are dropped (these
are country-locked tracks and cannot drive a guessing round).

**Why.** Both behaviours are silent failure modes: a missing page causes a
short playlist, a present-but-empty preview causes a 0-byte audio response.

## Failure encountered & fix

The first run of `test_normalize[Hello - 2009 Remaster-hello]` failed because
the dash-suffix tag regex required the keyword to follow the dash directly:

```
\s*-\s*(?:remaster|live|edit|...)\b.*$
```

In `Hello - 2009 Remaster` the dash is followed by the year `2009`, not the
keyword. Fix: allow an optional `\d{4}\s+` between the dash and the keyword.

```diff
- \s*-\s*(?:remaster(?:ed)?|...)\b.*$
+ \s*-\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|...)\b.*$
```

Re-run: 29 passed.

## Slowest tests

| Test | Time |
|---|---|
| `test_playlist_paginates_until_next_is_null` | 0.03 s |
| `test_track_with_empty_preview_is_dropped` | 0.02 s |
| `test_resolve_one_isrc_hit` | 0.02 s |
| `test_resolve_one_isrc_miss_falls_back_to_search` | 0.02 s |
| `test_resolve_one_search_below_threshold_is_unresolved` | 0.02 s |
| `test_resolve_many_concurrency_and_stats` | 0.02 s |

All other 23 tests ran in < 5 ms each. The asyncio mocked-network tests
dominate runtime due to `respx` setup overhead.
