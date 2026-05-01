"""Guess matching against the current track.

Algorithm
---------
A guess string is normalised (see :func:`normalize`) and compared to the
track's normalised title and artist by ``rapidfuzz.fuzz.token_set_ratio``.
The guess matches a field iff the similarity ≥ ``MATCH_THRESHOLD``.

Three guess shapes are accepted:

  1. **Title-only** — guess matches the title above threshold.
  2. **Artist-only** — guess matches the artist above threshold.
  3. **Both** — guess matches a substring "<artist> <title>" or
     "<title> <artist>" or contains tokens that combine to satisfy both.

Symmetry. Players type guesses in any order ("Adele Hello" or
"Hello Adele"); we test both concatenations and take the better score.

Threshold rationale
-------------------
``MATCH_THRESHOLD = 0.84`` was selected to be slightly stricter than the
resolver's matching threshold (0.78). The resolver is comparing two
*authoritative* metadata strings (Spotify vs Deezer) where false positives
are paid for in metadata mismatch only, while the matcher compares user
input to ground truth — false positives are paid for in score, which is
much more costly. See ``docs/matcher_threshold.md``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import GuessKind, Track

MATCH_THRESHOLD = 0.84

_TAG_RE = re.compile(
    r"""
    \s*[\(\[]\s*(?:feat|featuring|with|prod|remaster(?:ed)?|deluxe|bonus|live|edit|version|mix|remix|instrumental|acoustic)
    \b[^)\]]*[\)\]]\s*
    | \s*-\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|edit|version|mix|remix|instrumental|acoustic)\b.*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize(s: str) -> str:
    """Same normalisation rules as the resolver, kept consistent."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _TAG_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b) / 100.0


@dataclass(frozen=True)
class MatchResult:
    """Outcome of matching one guess against the current track."""

    kind: GuessKind
    title_score: float
    artist_score: float
    combined_score: float


def match_guess(guess: str, track: Track) -> MatchResult:
    """Classify a guess as matching TITLE / ARTIST / BOTH / NONE.

    Logic
    -----
    Compute the per-field token-set similarity ``title_s`` and ``artist_s``
    against the guess. Because ``token_set_ratio`` returns 1.0 whenever the
    smaller token set is a subset of the larger, a long guess such as
    "Adele Hello" already maxes both fields individually — we therefore do
    *not* need a "combined" concatenation score. The fields ARE the truth.
    """
    g = normalize(guess)
    t = normalize(track.title)
    a = normalize(track.artist)

    title_s = _ratio(g, t)
    artist_s = _ratio(g, a)

    title_hit = title_s >= MATCH_THRESHOLD
    artist_hit = artist_s >= MATCH_THRESHOLD

    if title_hit and artist_hit:
        kind = GuessKind.BOTH
    elif title_hit:
        kind = GuessKind.TITLE
    elif artist_hit:
        kind = GuessKind.ARTIST
    else:
        kind = GuessKind.NONE

    return MatchResult(kind, title_s, artist_s, max(title_s, artist_s))
