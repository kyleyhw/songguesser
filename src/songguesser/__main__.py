"""Entry point: ``python -m songguesser`` starts the game server.

Defaults bind to ``0.0.0.0:8138`` so LAN clients can join. mDNS advertisement
is opt-in via ``--advertise``; when enabled, the host's machine appears as
``songguesser-<hostname>._http._tcp.local`` so other devices on the same
network can discover it without typing IPs.

Internet exposure is delegated to ``cloudflared`` (see ``docs/networking.md``);
this module does not start a tunnel itself, so the host can keep the tunnel
under their own control.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="songguesser", description="songguesser game server")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8138")))
    parser.add_argument("--reload", action="store_true", help="auto-reload on file changes")
    parser.add_argument(
        "--advertise",
        action="store_true",
        help="advertise the server over mDNS (zeroconf) for LAN discovery",
    )
    parser.add_argument(
        "--log-level", default="info", choices=["critical", "error", "warning", "info", "debug"],
    )
    args = parser.parse_args()

    if args.advertise:
        from .mdns import advertise

        # Start mDNS in a background thread; stops automatically on process exit.
        advertise(port=args.port)

    log = logging.getLogger("songguesser")
    log.info(
        "Starting songguesser on http://%s:%d (LAN IP: %s)",
        args.host,
        args.port,
        _local_ip(),
    )
    print()  # blank line before uvicorn's own banner
    print(f"  songguesser  ->  http://localhost:{args.port}")
    print(f"  LAN clients  ->  http://{_local_ip()}:{args.port}")
    print(f"  internet     ->  run: cloudflared tunnel --url http://localhost:{args.port}")
    print()

    uvicorn.run(
        "songguesser.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


def _local_ip() -> str:
    """Best-effort LAN IPv4 address of this machine.

    We open a UDP socket to a public address; the OS assigns the local
    interface IP without actually sending any packets.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    main()
