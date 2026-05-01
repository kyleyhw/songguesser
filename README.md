# songguesser

A multiplayer song-guessing game in the style of `binb`. Paste any
public Spotify playlist URL, share a 6-character room code, and race to
name the title and artist before the round ends.

## Quickstart

```bash
git clone https://github.com/kyleyhw/songguesser.git
cd songguesser
uv sync
uv run python -m songguesser
```

Open `http://localhost:8138` in your browser, paste a Spotify playlist
URL (e.g. `https://open.spotify.com/playlist/37i9dQZEVXbLRQDuF5jeBp`),
click *Create room*, share the code with your friends.

No Spotify developer app is required — songguesser scrapes the public
Spotify embed page to get track titles, artists, and 30 s previews.

## Hosting for friends

### LAN

The server binds `0.0.0.0:8138` by default. The startup banner prints
your LAN IP. Friends on the same Wi-Fi visit `http://<your-lan-ip>:8138`.

Pass `--advertise` to publish over mDNS so the server appears as
`songguesser-<hostname>._http._tcp.local`:

```bash
uv run python -m songguesser --advertise
```

### Internet (Cloudflare Tunnel)

In a second terminal:

```bash
cloudflared tunnel --url http://localhost:8138
```

`cloudflared` prints a public `https://*.trycloudflare.com` URL. Share
it. WebSockets work end-to-end. No port forwarding, no DDNS.

The bundled `scripts/serve.sh` starts both at once:

```bash
TUNNEL=1 bash scripts/serve.sh
```

## How friends connect

The host runs the server (LAN or tunnel as above) and creates a room.
The room screen shows a 6-character code (e.g. `8F3KQ2`) at the top
left. Send each friend:

1. The URL they should open in their browser:
   - **LAN**: `http://<your-lan-ip>:8138` (printed in the host's
     startup banner).
   - **Internet**: the `https://<random>.trycloudflare.com` URL printed
     by `cloudflared`.
2. The 6-character room code.

On that page they fill in *Join a game*: paste the code, type a
display name, click *Join*. They appear in the host's lobby
immediately. Once everyone is in, the host clicks *Start game*.

Friends do **not** need a Spotify account, a developer app, or any
local install. Any modern browser works (audio playback uses the HTML
`<audio>` element with no autoplay).

## Rules and scoring

Each round plays a 30-second preview. The album cover is hidden during
play and revealed only when the round ends. You score by being fast.

For a guess landing at elapsed time $t$ in a round of duration $T$:

$$s(t) = \left\lfloor B \cdot \left( 1 - \tfrac{t}{T} \right) \right\rfloor$$

| What you guessed | Base $B$ | Score at $t=0$ | Score at $t=T/2$ |
|---|---|---|---|
| Title and artist (`BOTH`) | 1000 | 1000 | 500 |
| Just title or just artist | 500 | 500 | 250 |
| Wrong | 0 | 0 | 0 |

If you guess one half (say the title) at time $t_1$ and complete the
other half (artist) at time $t_2 > t_1$, your round total is *at least*
the full-credit score at $t_2$ — early partial guesses never hurt you.

Matching is forgiving: case-insensitive, diacritic-stripped, and tags
like `(Remastered 2011)` or `(feat. ...)` are ignored. Guesses are
classified `TITLE` / `ARTIST` / `BOTH` based on which fields the input
matches above the similarity threshold.

A round ends when **everyone** has guessed both parts, or when the
30 s preview elapses.

## Configuration

`POST /api/rooms` body fields tune game parameters:

```jsonc
{
  "playlist_url": "https://open.spotify.com/playlist/...",
  "max_rounds": 10,
  "round_seconds": 30.0,
  "reveal_seconds": 8.0
}
```

## Project layout

```
songguesser/
├── README.md
├── pyproject.toml          uv + ruff + ty + detect-secrets + pre-commit
├── scripts/
│   ├── serve.sh            LAN + optional Cloudflare Tunnel launcher
│   └── fake_players.py     N-player simulation
├── src/songguesser/
│   ├── __main__.py         `python -m songguesser`
│   ├── models.py           Track, Playlist, Room, Player, Round
│   ├── spotify_public.py   Public Spotify playlist embed parser
│   ├── matcher.py          Guess matching
│   ├── scoring.py          Score curve
│   ├── engine.py           Per-room state machine
│   ├── rooms.py            In-memory room registry
│   ├── protocol.py         WebSocket message schemas
│   ├── server.py           FastAPI app + WebSocket
│   ├── mdns.py             zeroconf LAN advertisement
│   └── static/             Browser client (HTML/CSS/JS)
└── tests/
```
