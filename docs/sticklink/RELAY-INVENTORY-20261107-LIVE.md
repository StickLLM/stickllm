# Live relay inventory — 2026-11-07 18:28–18:29 EST

Source: Sticklink read-only SSH inventory (operator-confirmed).  
**No private-key transfer to this agent PC was required.** SSH access is resolved on Sticklink’s side.

## Confirmed running state

| Item | Value |
|---|---|
| Host | `relay-tor1.stickllm.com` |
| `derper.service` | **active** — Tailscale DERP **1.104.4** |
| DERP / HTTPS | TCP **443** |
| ACME / HTTP | TCP **80** |
| STUN | UDP **3478** |
| `derp-admit.service` | **active** — Python deny-all verifier |
| Admit listen | `127.0.0.1:9099/derp/admit` |
| Admit response | `{"Allow": false}` (deny-all) |
| derper fail-open | **`false`** (`-verify-client-url-fail-open=false`) |
| `sticklink-admit.service` | **not installed** |
| TLS validation | **passed** |
| Relay-originated STUN IPv4 / IPv6 | **passed** |
| External browser / WSS forced-relay | **untested** |

## Paths to preserve (do not rewrite identity / TLS / firewall / SSH)

| Path | Role |
|---|---|
| `/usr/local/bin/derper` | DERP binary 1.104.4 |
| `/etc/systemd/system/derper.service` | Unit (`Wants=`/`After=` → `derp-admit.service`) |
| `/etc/default/derper` | `DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit` |
| `/var/lib/derper/derper.key` | Relay node private key (**identity**) |
| `/var/lib/derper/certs/` | Let's Encrypt material |
| `/usr/bin/python3` + `/usr/local/lib/sticklink/derp-admit.py` | Deny-all stub |
| `/etc/systemd/system/derp-admit.service` | Admit stub unit |
| `/etc/nftables.conf` | Host firewall (22/80/443 TCP, 3478 UDP) |
| SSH hardening under `/etc/ssh/sshd_config.d/` | Leave unchanged |

## Conditional rollback (live procedure — use after any admit cutover)

Emergency lock = restore deny-all on the **same** verify URL derper already uses:

1. Ensure `derp-admit.service` is enabled and running on `127.0.0.1:9099`.
2. Set `/etc/default/derper` → `DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit`.
3. Restore `derper.service` `Wants=`/`After=` to `derp-admit.service` if changed.
4. `systemctl daemon-reload && systemctl restart derper` (**interrupts** new DERP handshakes briefly).
5. Confirm: POST/GET admit → `Allow:false`; unknown nodekey rejected; TLS/STUN still OK.

Do **not** rotate `/var/lib/derper/derper.key`, certs, nftables, or SSH as part of rollback.

## Staging note

Real `sticklink-admit` must be proven on a **separate loopback port** (plan: `127.0.0.1:9109`) while `derp-admit` remains on **9099** and derper stays pointed at 9099, until an explicit interruption approval for Phase 3.
