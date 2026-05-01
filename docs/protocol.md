# WebSocket protocol

All messages are JSON objects with a `type` discriminator.

## Inbound (client → server)

| `type` | Body | Effect |
|---|---|---|
| `join` | `{name: str}` | Records the player's display name. Sent implicitly by the URL query string `?name=...`; this `type` is reserved for future name changes. |
| `start` | `{}` | Host-only. Begins the first round. |
| `next` | `{}` | Host-only. Cancels the current round's runner and starts a fresh one (skip / debug). |
| `guess` | `{text: str}` | Submits a guess against the current track. |
| `ping` | `{}` | Keepalive. Server replies with `pong`. |

The WebSocket URL itself encodes the room and player identity:

```
ws[s]://host:port/ws/{room_code}?player_id={uuid}&name={url-encoded-name}
```

`player_id` should be persisted in `localStorage` so reconnecting
preserves the player's score and host status.

## Outbound (server → client)

| `type` | Body | When |
|---|---|---|
| `state` | `{room: RoomSnapshot}` | After any state transition (join, leave, phase change, score update). |
| `round_start` | `{round_index, audio_url, duration, cover_url}` | When PLAYING begins for a round. |
| `round_tick` | `{elapsed, progress}` | Every ~250 ms during PLAYING. |
| `round_end` | `{round_index, track, leaderboard, is_final}` | When PLAYING transitions to REVEAL. |
| `guess_result` | `{player_id, name, kind, points, total}` | After any non-NONE guess. |
| `chat` | `{player_id, name, text}` | Echoes every guess to all clients. |
| `error` | `{message}` | Validation/auth failure. |
| `pong` | `{}` | Reply to `ping`. |

## `RoomSnapshot`

```jsonc
{
  "code": "ABC123",
  "phase": "lobby" | "playing" | "reveal" | "finished",
  "playlist_name": "...",
  "round_index": -1,             // -1 before the first round starts
  "total_rounds": 10,
  "round_seconds": 30.0,
  "reveal_seconds": 8.0,
  "players": [
    {
      "id": "...",
      "name": "Alice",
      "score": 1234,
      "is_host": true,
      "connected": true,
      "round_kind": "none" | "title" | "artist" | "both"
    }
  ]
}
```

## Client-side state machine

```
landing  ──create-or-join──►  game (LOBBY)
   │                            │
   │              host clicks "start"
   │                            ▼
   │                      server "round_start"
   │                            │
   │                            ▼
   │                       PLAYING ──tick──► ...
   │                            │
   │                  server "round_end"
   │                            ▼
   │                        REVEAL  ──after reveal_seconds──►
   │                            │            (next round_start)
   │                            ▼
   │                       FINISHED
   ▼
```
