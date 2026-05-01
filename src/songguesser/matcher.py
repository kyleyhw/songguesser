"""Guess matching against the current track.

Algorithm
---------
The guess and the track's title and artist are first normalised:

  * Unicode → ASCII (diacritics dropped).
  * Edition tags such as ``(Remastered 2011)`` or ``(feat. ...)`` removed.
  * Punctuation collapsed to whitespace.
  * Lower-cased, runs of whitespace collapsed.

After normalisation the comparison is **exact equality** — no fuzzy
threshold. A guess matches the title (resp. artist) iff the normalised
guess string equals the normalised title (resp. artist). A guess
matches BOTH if the normalised guess equals either ``"<title> <artist>"``
or ``"<artist> <title>"``, *or* both individual fields match (which can
happen when the title equals the artist, e.g. on self-titled singles).

This is intentionally strict: the previous token-set fuzzy match would
accept "Bohemian" alone for "Bohemian Rhapsody / Queen", which is too
lenient. Tags and diacritics are still stripped so e.g. "Cafe" matches
"Café" and "Don't Stop Me Now" matches "Don't Stop Me Now (Remastered
2011)".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import GuessKind, Track

_TAG_RE = re.compile(
    r"""
    \s*[\(\[]\s*(?:feat|featuring|with|prod|remaster(?:ed)?|deluxe|bonus|live|edit|version|mix|remix|instrumental|acoustic)
    \b[^)\]]*[\)\]]\s*
    | \s*-\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|edit|version|mix|remix|instrumental|acoustic)\b.*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize(s: str) -> str:
    """Lowercase, strip diacritics + edition tags, collapse punctuation."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _TAG_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


@dataclass(frozen=True)
class MatchResult:
    """Outcome of matching one guess against the current track.

    ``title_score`` and ``artist_score`` are 1.0 on exact normalised match
    and 0.0 otherwise; ``combined_score`` is 1.0 iff the guess matched
    BOTH (either by combined string or by both fields individually).
    """

    kind: GuessKind
    title_score: float
    artist_score: float
    combined_score: float


def match_guess(guess: str, track: Track) -> MatchResult:
    """Classify a guess as matching TITLE / ARTIST / BOTH / NONE.

    Returns NONE for an empty guess or when the normalised guess equals
    neither the title, the artist, nor any concatenation thereof.
    """
    g = normalize(guess)
    t = normalize(track.title)
    a = normalize(track.artist)

    if not g:
        return MatchResult(GuessKind.NONE, 0.0, 0.0, 0.0)

    title_hit = bool(t) and g == t
    artist_hit = bool(a) and g == a
    combined_hit = bool(t) and bool(a) and g in {f"{t} {a}", f"{a} {t}"}

    if combined_hit or (title_hit and artist_hit):
        kind = GuessKind.BOTH
    elif title_hit:
        kind = GuessKind.TITLE
    elif artist_hit:
        kind = GuessKind.ARTIST
    else:
        kind = GuessKind.NONE

    return MatchResult(
        kind=kind,
        title_score=1.0 if title_hit else 0.0,
        artist_score=1.0 if artist_hit else 0.0,
        combined_score=1.0 if combined_hit else 0.0,
    )
