# Spotify Developer Policy and this project

This document records the contractual posture of `songguesser` against the
Spotify Developer Terms (effective 2025-05-15) and Developer Policy. It is
intended to be read once before the host registers a Spotify Developer App
and once after every Spotify policy update.

## The relevant clauses

The Spotify Developer Policy ([source](https://developer.spotify.com/policy))
contains three clauses that apply to a song-guessing game:

> **III.2** — Do not create a game, including trivia quizzes.

> **III.6** — Do not synchronize any sound recordings with any visual media
> (including a music video, film, TV show, advertisement, broadcast, etc.)
> without our express written permission.

> **III.7** — Do not permit any device or system to segue, mix, re-mix, or
> overlap any Spotify Content with any other audio content.

## How `songguesser` is positioned

`songguesser` plays *Deezer* preview clips, not Spotify audio. Spotify is
used only for **metadata**: the host pastes a Spotify playlist URL, the
server reads `playlist tracks (name, artists, ISRC)` via the Spotify
Web API under the host's own OAuth, and the server then resolves each
track to a Deezer preview by ISRC.

Because no Spotify audio is ever streamed to clients:

- III.6 (sync of Spotify sound recordings to visual media) does not apply
  to anything `songguesser` does — there is no Spotify sound recording in
  the application.
- III.7 (segueing/remixing Spotify content with other audio) does not
  apply for the same reason.
- III.2 ("do not create a game") is the remaining contractual concern.
  A literal reading prohibits *any* application that is a game from using
  the Web API at all, including for metadata-only lookups. `songguesser`
  is therefore in a contractual grey zone: technically the host's app
  *is* a game, but the Spotify-touching portion of the app is purely a
  read-only playlist lookup.

For private hobby use among ≤ 5 friends with no public listing, the
practical enforcement risk is negligible but **non-zero**. Spotify's
enforcement signal is a manual review trigger (e.g. a complaint or a
public listing); read-only access patterns to one's own playlists do
not generate flags on their own.

## What you should do

- **Personal hobby**: register a Spotify Developer App in development
  mode (capped at 5 authenticated users since 2026-02-11, per the
  [February 2026 policy update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)).
  Add yourself + your friends as authorised users from the dashboard.
- **Public deployment**: do not. Either move to Deezer playlists only
  (use the `/api/rooms/demo` endpoint), or skip music entirely.
- **Commercial deployment**: do not. The Extended Quota Mode application
  requires a registered business entity with ≥ 250 k MAU and the policy
  prohibition still applies.

## Alternatives

If you want a publicly-deployable variant of this game, replace the
Spotify entrypoint with a Deezer playlist URL. Deezer's terms (as of
2026) permit the use of preview URLs in third-party applications and
contain no analogue to Spotify's III.2 ("no games"). A `--source deezer`
mode is intentionally trivial to configure (the audio path is already
Deezer; only the playlist-loading step changes).
