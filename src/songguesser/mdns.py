"""mDNS advertisement for LAN discovery.

We register the server as ``_http._tcp.local`` with the instance name
``songguesser-<hostname>``. Other devices on the same network can browse
``_http._tcp.local`` (e.g. with ``avahi-browse`` or Apple's Bonjour) and see
the server without needing to be told the IP.

Lifecycle
---------
The ``Zeroconf`` instance is held in a module-global so it survives until
process exit. ``atexit`` unregisters the service cleanly so other devices
do not see a stale advertisement. The advertisement runs in a background
thread owned by the ``zeroconf`` library.
"""

from __future__ import annotations

import atexit
import logging
import socket
from typing import Any

log = logging.getLogger(__name__)

_zc: Any = None  # held alive
_info: Any = None


def advertise(*, port: int, instance: str | None = None) -> None:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf

    global _zc, _info
    if _zc is not None:
        return  # already advertising

    hostname = socket.gethostname().split(".")[0]
    instance_name = instance or f"songguesser-{hostname}"
    fq_name = f"{instance_name}._http._tcp.local."
    addr = _local_ip()

    _info = ServiceInfo(
        type_="_http._tcp.local.",
        name=fq_name,
        addresses=[socket.inet_aton(addr)],
        port=port,
        properties={"app": "songguesser", "version": "0.1.0"},
        server=f"{instance_name}.local.",
    )
    _zc = Zeroconf(ip_version=IPVersion.V4Only)
    _zc.register_service(_info)
    log.info("Advertising %s on %s:%d", fq_name, addr, port)
    atexit.register(_unadvertise)


def _unadvertise() -> None:
    global _zc, _info
    if _zc is not None and _info is not None:
        try:
            _zc.unregister_service(_info)
            _zc.close()
        except Exception:
            pass
    _zc = None
    _info = None


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
