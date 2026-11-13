# Public HTTPS gateway for a self-hosted Matrix server (illustrative)

A working pattern for a home-based Matrix/LiveKit deployment is:

````text
iOS / Matrix client → HTTPS (443) → public gateway → localhost-only SSH reverse tunnel → home Caddy → Synapse
````

This document is **an architecture example**, not the deployed server's configuration.
Use your own DNS names and network addresses, do not copy real secrets into a repo,
and keep the SSH listener bound to the public gateway's loopback address, `127.0.0.1`. The HTTPS edge should be an
existing proxy with a separate hostname virtual host, rather than taking over
a public port already used for another service.

For Docker-host bridging, bind a relay to the relevant private Docker bridge
gateway, protect access with Docker/host firewall rules, and verify certificate
hostname and trust when forwarding HTTPS. A dedicated SSH key restricted to the
required reverse listening port reduces exposure. Make both services persistent
with systemd and use monitoring, restart policies, and host key pinning.

Prefer client-facing Matrix endpoints only, avoid exposing Synapse administration
interfaces, and evaluate Matrix's public discovery and federation requirements
before choosing the production hostname.

LiveKit voice/video media is **not** carried by the basic Matrix HTTPS tunnel
alone: configure UDP/TCP media and TURN separately, with appropriate relay
addresses, NAT traversal, and firewall rules.

Never commit live Matrix databases, signing keys, registration secrets,
LiveKit API keys, APNs keys, TLS private keys, SSH identities, session tokens,
or user message/media storage.
