"""Spawn N concurrent fake players against a running songguesser server.

The fakes connect to a synthetic room (or a real room whose code is
provided), wait for round_start, and submit a guess after a random delay.
Their guess is correct with probability ``p_correct`` and otherwise a
plausible-but-wrong miss.

Usage
-----
Make sure the server is running with ``SONGGUESSER_ENABLE_SYNTHETIC=1``,
then::

    uv run python scripts/fake_players.py --players 5 --rounds 3

The script creates a synthetic room itself if no ``--code`` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import random
from dataclasses import dataclass

import httpx
import websockets

log = logging.getLogger("fake_players")
_bg_tasks: set[asyncio.Task] = set()

NAMES = [
    "Alice",
    "Bob",
    "Carol",
    "Dave",
    "Eve",
    "Frank",
    "Grace",
    "Heidi",
]

CORRECT_GUESSES = {
    "Bohemian Rhapsody": ["bohemian rhapsody queen", "queen bohemian rhapsody"],
    "Hello": ["adele hello", "hello adele"],
    "Believer": ["imagine dragons believer", "believer imagine dragons"],
}

MISSES = [
    "thriller michael jackson",
    "rolling stones",
    "billie eilish",
    "i don't know",
    "uhhh",
]


@dataclass
class FakeConfig:
    server: str
    code: str
    n_players: int
    p_correct: float
    min_delay_s: float
    max_delay_s: float


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8138")
    parser.add_argument("--code", default=None, help="existing room code (else create synthetic)")
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--p-correct", type=float, default=0.7)
    parser.add_argument("--min-delay", type=float, default=0.5)
    parser.add_argument("--max-delay", type=float, default=4.0)
    parser.add_argument("--round-seconds", type=float, default=8.0)
    parser.add_argument("--reveal-seconds", type=float, default=2.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    code = args.code
    if code is None:
        async with httpx.AsyncClient(base_url=args.server) as http:
            r = await http.post(
                f"/api/rooms/synthetic?round_seconds={args.round_seconds}"
                f"&reveal_seconds={args.reveal_seconds}"
            )
            r.raise_for_status()
            code = r.json()["code"]
            log.info("created synthetic room %s", code)

    cfg = FakeConfig(
        server=args.server,
        code=code,
        n_players=args.players,
        p_correct=args.p_correct,
        min_delay_s=args.min_delay,
        max_delay_s=args.max_delay,
    )
    names = random.sample(NAMES, k=min(cfg.n_players, len(NAMES)))
    await asyncio.gather(*(run_player(cfg, name, is_host=(i == 0)) for i, name in enumerate(names)))


async def run_player(cfg: FakeConfig, name: str, *, is_host: bool) -> None:
    ws_url = (
        cfg.server.replace("http", "ws")
        + f"/ws/{cfg.code}?player_id={name.lower()}&name={name}"
    )
    log.info("[%s] connecting to %s", name, ws_url)
    async with websockets.connect(ws_url) as ws:
        round_idx = -1
        score = 0
        if is_host:
            await asyncio.sleep(1.0)  # let everyone join
            log.info("[%s] sending start", name)
            await ws.send(json.dumps({"type": "start"}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "round_start":
                round_idx = msg["round_index"]
                log.info("[%s] round_start idx=%d", name, round_idx)
                # Fire-and-forget; reference held until the loop exits.
                _bg_tasks.add(
                    asyncio.create_task(_guess_after_delay(ws, name, round_idx, cfg))
                )
            elif msg["type"] == "round_end":
                board = msg["leaderboard"]
                me = next((p for p in board if p["name"] == name), None)
                score = me["score"] if me else 0
                log.info(
                    "[%s] round_end %s by %s, my score=%d",
                    name, msg["track"]["title"], msg["track"]["artist"], score,
                )
                if msg["is_final"]:
                    log.info("[%s] FINAL leaderboard: %s",
                             name, [(p["name"], p["score"]) for p in board])
                    return
            elif msg["type"] == "guess_result" and msg["name"] == name:
                log.info("[%s] guess_result kind=%s +%d total=%d",
                         name, msg["kind"], msg["points"], msg["total"])


async def _guess_after_delay(
    ws: websockets.WebSocketClientProtocol,
    name: str,
    round_idx: int,
    cfg: FakeConfig,
) -> None:
    """Submit a guess after a random delay. Picks correct or miss based on `p_correct`."""
    delay = random.uniform(cfg.min_delay_s, cfg.max_delay_s)
    await asyncio.sleep(delay)
    track_title = list(CORRECT_GUESSES.keys())[round_idx % 3]
    if random.random() < cfg.p_correct:
        text = random.choice(CORRECT_GUESSES[track_title])
    else:
        text = random.choice(MISSES)
    log.info("[%s] guessing after %.2fs: %r", name, delay, text)
    with contextlib.suppress(websockets.exceptions.ConnectionClosed):
        await ws.send(json.dumps({"type": "guess", "text": text}))


if __name__ == "__main__":
    asyncio.run(main())
