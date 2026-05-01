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

# Inline featured-artist marker that is *not* parenthesised, e.g.
# "Jay-Z ft. Rihanna" or "Calvin Harris featuring Dua Lipa". Anything from
# the marker to end-of-string is dropped when extracting the main artists.
_INLINE_FEATURE_RE = re.compile(
    r"\s+(?:feat|ft|featuring|with)\.?\s+.*$",
    re.IGNORECASE,
)


def normalize(s: str) -> str:
    """Lowercase, strip diacritics + edition tags, collapse punctuation."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _TAG_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


def main_artists(artist_raw: str) -> list[str]:
    """Return the list of *main* artists from a (possibly compound) artist
    string, each individually normalised.

    Spotify's embed page returns the artist field as a flat string such as
    "Kanye West, Jay-Z" or "Jay-Z, Kanye West feat. Rihanna". We:

      1. Strip parenthesised tags ("(feat. ...)", "(Remastered 2011)") via
         the existing :data:`_TAG_RE`.
      2. Strip any inline "feat./ft./featuring/with ..." suffix (no parens).
      3. Split the remainder on commas — the comma separator is what
         Spotify uses for co-headliners. We deliberately do *not* split on
         '&' because it appears inside legitimate single-artist names
         ("Mumford & Sons", "Earth, Wind & Fire").
      4. Normalise each piece and drop empties.
    """
    s = _TAG_RE.sub(" ", artist_raw)
    s = _INLINE_FEATURE_RE.sub("", s)
    parts = [normalize(p) for p in s.split(",")]
    return [p for p in parts if p]


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

    Title rule: normalised guess equals normalised title exactly.
    Artist rule: normalised guess equals *any one* of the main artists
        (see :func:`main_artists` — featured artists are excluded).
    BOTH rule: guess equals "<title> <X>" or "<X> <title>" where X is
        any main artist or the full normalised artist string.
    """
    g = normalize(guess)
    t = normalize(track.title)
    mains = main_artists(track.artist)
    full_a = normalize(track.artist)
    artist_candidates = list(dict.fromkeys([*mains, full_a])) if full_a else mains

    if not g:
        return MatchResult(GuessKind.NONE, 0.0, 0.0, 0.0)

    title_hit = bool(t) and g == t
    artist_hit = bool(artist_candidates) and g in artist_candidates

    combined_set: set[str] = set()
    if t:
        for a in artist_candidates:
            combined_set.add(f"{t} {a}")
            combined_set.add(f"{a} {t}")
    combined_hit = g in combined_set

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
