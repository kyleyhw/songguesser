# Networking — LAN and internet

## LAN play

The server binds `0.0.0.0:8138` by default. To play on a LAN:

1. Run `python -m songguesser` (or `bash scripts/serve.sh`).
2. The startup banner prints the LAN IPv4 address, e.g.

   ```
   songguesser  →  http://localhost:8138
   LAN clients  →  http://192.168.1.101:8138
   ```

3. Guests on the same Wi-Fi visit the LAN URL in their browser.

### mDNS discovery (optional)

Pass `--advertise` to publish the server as `songguesser-<hostname>._http._tcp.local`.
Other devices on the LAN can then discover the host without typing IPs:

- macOS: in Safari, type `songguesser-<hostname>.local:8138`.
- iOS: same.
- Linux: `avahi-browse -rt _http._tcp` lists advertised services.
- Windows: install Bonjour Print Services if not already present.

The mDNS advertisement uses IPv4 only and unregisters cleanly on process
exit.

## Internet play with Cloudflare Tunnel

Cloudflare Tunnel ([cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)) exposes
your locally-running server at a public HTTPS URL with no port-forwarding
or DDNS:

```bash
# In a second terminal, after the server is running:
cloudflared tunnel --url http://localhost:8138
```

`cloudflared` prints a URL like `https://random-words-1234.trycloudflare.com`.
Share that URL with friends and they can join from anywhere. The tunnel
terminates TLS, so WebSocket upgrades work end-to-end.

The bundled `scripts/serve.sh` will start the tunnel automatically when
`TUNNEL=1`:

```bash
TUNNEL=1 bash scripts/serve.sh
```

### Why not ngrok / localtunnel / Tailscale Funnel?

- **ngrok** free tier rotates URLs and limits concurrent tunnels;
  acceptable but Cloudflare Tunnel's free tier is more permissive.
- **localtunnel** lacks WebSocket support on its free tier in 2026.
- **Tailscale Funnel** requires every guest to install Tailscale; great
  if your friends already use it, friction otherwise.

Cloudflare Tunnel is the lowest-friction zero-cost option.

## Firewall notes

If LAN clients cannot connect, your OS firewall is likely blocking
inbound connections to port 8138. On Windows, allow Python in *Windows
Defender Firewall*. On macOS, *System Settings → Network → Firewall →
Options* and add the Python interpreter. On Linux,
`sudo ufw allow 8138/tcp` if `ufw` is active.
