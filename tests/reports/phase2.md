# Phase 2 Test Report

**Date:** 2026-05-01
**Suite:** `tests/` (67 tests, of which 38 are new in Phase 2)
**Total runtime:** 0.60 s
**Result:** 67 passed, 0 failed

## Coverage of Phase 2 deliverables

| Deliverable | New tests |
|---|---|
| Score curve (`scoring.py`) | `test_scoring.py` (10 tests) |
| Cover-art reveal (`reveal.py`) | `test_reveal.py` (6 tests) |
| Guess matcher (`matcher.py`) | `test_matcher.py` (12 tests) |
| Engine glue (`engine.py`) | `test_engine.py` (10 tests) |

## What was tested and why

### `test_scoring.py`
**What.** Exhaustively verifies the score curve $s(t) = \lfloor B \cdot (1 - t/T) \rfloor$
at the four boundary points $t \in \{0, T/2, T, T+\Delta\}$, plus a numeric
sample at $t = T/3$. Verifies the five lattice transitions of `award_for`:
NONE→TITLE, TITLE→BOTH (top-up arithmetic), TITLE→TITLE (no double-pay),
BOTH→BOTH (no double-pay), and NONE→NONE (zero match → zero points).
Also asserts strict monotonic non-increase of the BOTH-from-NONE award
across $t \in \{0, 5, 10, 15, 20, 25, 30\}$.

**Why.** Scoring is the most arithmetic-sensitive part of the game; an
off-by-one in the floor function or a missed lattice transition would
produce silent score drift across many rounds.

**Inputs chosen because.** $t = 0, T/2, T$ pin down the analytic boundaries
of the linear curve. The TITLE-then-ARTIST upgrade case uses $t_1 = 5$,
$t_2 = 12$ — both well inside the round and not at boundaries, so any
boundary-special-case bug surfaces.

### `test_reveal.py`
**What.** Synthesises a deterministic 256×256 noise image (seed = 42),
then verifies:
1. Output luminance variance is monotone in progress (var(p=0) <
   var(p=1) and at least 2× larger at p=1).
2. Progress is clamped to [0, 1] (negative and ≥ 1 inputs map to the
   endpoints; pixel-equality assertion).
3. Output is always 512×512 (the documented `output_size`).
4. JPEG output is a valid JPEG (FF D8 FF prefix, FF D9 suffix).
5. At p = 1, output luminance variance is ≥ 35 — close to the input's
   noise variance (theoretical 47.4 for i.i.d. uniform RGB).
6. More aggressive `RevealParams` (`σ_max=32, f_max=64` vs `σ_max=4,
   f_max=4`) produce strictly more obscuration at p = 0.

**Why.** The reveal transform is the user-visible heart of the game; a
regression in either the pixelation or blur curve would produce images
that are too easy or too hard to recognise. We verify the *direction* of
the effect (monotonicity and parameter sensitivity) rather than exact
pixel values, because PIL's resampling is platform-dependent.

**Inputs chosen because.** A high-frequency noise image is the worst
case for both pixelation (no large coherent regions to anchor on) and
Gaussian blur (every frequency is present), so any monotonicity violation
is maximally visible.

### `test_matcher.py`
**What.** Twelve cases covering: title-only guesses, artist-only guesses,
both-orders ("Adele Hello" and "Hello Adele"), case insensitivity, extra
whitespace, complete fabrications, remaster-tag tolerance ("Don't Stop Me
Now" matches "Don't Stop Me Now (Remastered 2011)"), diacritic stripping
("cafe" matches "Café"), and the BOHEMIAN-RHAPSODY token-subset case (a
single title token suffices for partial credit).

**Why.** Matcher false positives award unearned score; matcher false
negatives produce a frustrating "I typed it correctly!" experience. We
test both directions.

### `test_engine.py`
**What.** End-to-end engine flows: lobby→playing transition, first-player
becomes host, correct guess awards score, wrong guess yields zero,
"everyone solved" signal fires when all *connected* players have BOTH,
disconnected players don't block the everyone-solved signal, guesses
outside PLAYING return None, `max_rounds` correctly clips longer
playlists, playlist exhaustion raises `StopIteration` and marks the room
FINISHED.

**Why.** These are the integration points between matcher, scoring,
models, and external callers (the websocket server). Each represents a
behaviour the UI relies on.

## Failures encountered & fixes

**1. Matcher: single-token guesses incorrectly classed as BOTH.**

The first implementation included a "combined" similarity score against
the concatenation `"<title> <artist>"`. Because `token_set_ratio` returns
1.0 whenever the smaller set is a subset of the larger, a guess of
"Hello" against title="Hello" + artist="Adele" had:

  - title_s = 1.0 (subset)
  - artist_s ≈ 0
  - combined = 1.0 (subset of "hello adele")

The branch `combined_hit ∧ title_hit → BOTH` then fired, awarding full
credit for a title-only guess. Fix: drop the combined logic entirely; rely
on per-field scores. With `token_set_ratio`, a multi-token guess like
"Adele Hello" already maxes both fields individually because each is a
subset, so the BOTH path fires correctly without help.

**2. Reveal: tight luminance-std threshold off by ~1.6.**

The first test used `> 50.0` for the input luminance std. Theoretical
expectation for an i.i.d. uniform[0,255] RGB image converted to luminance
($0.299R + 0.587G + 0.114B$) is

$$\sigma_L = \sqrt{(0.299^2 + 0.587^2 + 0.114^2) \cdot \tfrac{255^2}{12}} \approx 47.4,$$

so the observed 49.3 was within the expected fluctuation. Threshold
relaxed to `> 40.0` (input) and `> 35.0` (output, after LANCZOS resize)
with a comment justifying the bound.

## Slowest tests

| Test | Time |
|---|---|
| `test_progress_clamped_to_unit_interval` | 0.04 s |
| `test_custom_params_increase_obscuration` | 0.03 s |
| `test_reveal_to_jpeg_bytes_returns_jpeg` | 0.03 s |
| `test_playlist_paginates_until_next_is_null` | 0.03 s |
| `test_progress_zero_is_more_obscured_than_progress_one` | 0.03 s |

Reveal tests dominate because each one allocates a 512×512 image and runs
PIL's LANCZOS resize + Gaussian blur. Total runtime stays well under one
second.
