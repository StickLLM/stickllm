# sticklink DERP relay — relay-tor1.stickllm.com

Set up 2026-10-29 (America/Toronto). Tailscale `derper` running as a private DERP + STUN relay for sticklink.
For now it is **closed to everyone**: every client goes through an admission check, and a local stub denies them all.

## Server

| Item | Value |
|---|---|
| Provider / plan | Luna Node, Toronto, m.1s (1 vCPU, 1 GB RAM, 15 GB disk), VM `relay-tor1` (id f000b53e-668a-40aa-96d2-9197fb378339) |
| OS | Debian 12.15 (bookworm), kernel 6.1.0-54-amd64 after full-upgrade and reboot |
| IPv4 | 170.75.167.152, NAT'd by Luna Node to private 172.16.0.21 on `ens3` |
| IPv6 | 2602:ffb6:4:e3b0:f816:3eff:feb6:d562 |
| DNS | `relay-tor1.stickllm.com` A + AAAA, DNS-only (Cloudflare) |
| Login | `debian` + ed25519 key (`/home/box/.ssh/sticklink_relay` on the box), passwordless sudo |
| Timezone | UTC |
| Swap | 512 MB swap partition `/dev/vdb`, provided by Luna Node. Swap already existed, so no 1 GB swapfile was added. |

## What was installed / configured

| Component | Version | Config |
|---|---|---|
| derper (tailscale.com/cmd/derper) | **1.104.4** (`1.104.4-t27047635f`, tag v1.104.4, the latest stable on 2026-10-29), built with Go 1.27.3, static, CGO_ENABLED=0, sha256 `6bc30e90843a78806970b771c9c82db3ed36facf5739b4b6eac405b7ac378c23` | `/usr/local/bin/derper`, `/etc/systemd/system/derper.service`, `/etc/default/derper` |
| derp-admit (deny-all admission stub) | Python 3.11.2 stdlib | `/usr/local/lib/sticklink/derp-admit.py`, `/etc/systemd/system/derp-admit.service` |
| nftables | 1.0.6-2+deb12u2 | `/etc/nftables.conf` |
| fail2ban | 1.0.2-2 | `/etc/fail2ban/jail.d/sshd.local` (systemd backend, 5 failures in 10 min → 1 h ban, nftables action) |
| unattended-upgrades | 2.9.1+nmu3 | `/etc/apt/apt.conf.d/20auto-upgrades`; Debian default `50unattended-upgrades` installs only `bookworm-security` updates |
| openssh-server | 1:9.2p1-2+deb12u10 | `/etc/ssh/sshd_config.d/10-sticklink-hardening.conf` |
| journald | — | `/etc/systemd/journald.conf.d/sticklink.conf` (200 MB cap, 7-day retention) |
| systemd-resolved | — | `/etc/systemd/resolved.conf.d/sticklink.conf` (LLMNR/mDNS off) |

Reproducible copies of all of these files: `/workspace/sticklink/relay/files/`. Provisioning script: `/workspace/sticklink/relay/install.sh`.
Test tools: `relay/stun_test.py` (STUN probe) and `relay/ts/cmd/derpdenytest` (tries to relay with an unregistered key).

### SSH (`sshd -T` result)
`permitrootlogin no`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `pubkeyauthentication yes`, `authenticationmethods publickey`, `permitemptypasswords no`, `x11forwarding no`, `maxauthtries 3`. The `debian` and `root` passwords are locked (`passwd -S` → `L`).
Checked: a second session with the key worked before and after `sshd` restarted; root with the same key was refused; the server offers only `publickey`.

### Firewall (`nft list ruleset`, one `inet` table covers IPv4 and IPv6)
```
#!/usr/sbin/nft -f
# /etc/nftables.conf — sticklink relay-tor1 host firewall (IPv4 + IPv6 via inet family)
flush ruleset

table inet filter {
	chain input {
		type filter hook input priority filter; policy drop;

		ct state established,related accept
		ct state invalid drop
		iif "lo" accept

		# ICMP / ICMPv6 (needed for PMTU discovery, IPv6 neighbour discovery & SLAAC)
		meta l4proto icmp accept
		meta l4proto ipv6-icmp accept

		tcp dport 22 accept comment "SSH"
		tcp dport 80 accept comment "HTTP (Let's Encrypt HTTP-01 + redirect)"
		tcp dport 443 accept comment "DERP over HTTPS"
		udp dport 3478 accept comment "STUN"

		# DHCPv4 client replies (Luna Node assigns the private IPv4 via DHCP)
		udp sport 67 udp dport 68 accept
	}
	chain forward {
		type filter hook forward priority filter; policy drop;
	}
	chain output {
		type filter hook output priority filter; policy accept;
	}
}
```
Only TCP 22/80/443 and UDP 3478 are open inbound. ICMP/ICMPv6 is also allowed because IPv6 neighbour discovery and path-MTU discovery need it. The DHCPv4 reply rule exists because Luna Node assigns the private IPv4 over DHCP. Outbound traffic is not restricted.

### Luna Node security group
The VM is in security group `default` (id 4, toronto). `securitygroup rule-list` returns `{"success":"yes"}` with no rule list, so the API didn't show the rules. Live tests showed the needed ports are open: TCP 22/80/443 answer from the internet, and Let's Encrypt validated the cert. UDP 3478 sent to the public IPv4 goes through Luna Node's NAT and answers. **No security-group changes were made.**

## derper

### Flags
| Flag | Value | Why |
|---|---|---|
| `-hostname` | `relay-tor1.stickllm.com` | TLS name / ACME |
| `-certmode` | `letsencrypt` | autocert |
| `-certdir` | `/var/lib/derper/certs` | in the StateDirectory |
| `-c` | `/var/lib/derper/derper.key` | DERP server's node private key. Required because derper doesn't run as root; it is created on first start. |
| `-a` | `:443` | HTTPS / DERP, all IPv4+IPv6 addresses |
| `-http-port` | `80` | ACME HTTP-01 + redirect |
| `-stun` / `-stun-port` | on / `3478` | STUN |
| `-home` | `blank` | empty page at `/` instead of the default Tailscale homepage |
| `-verify-client-url` | `${DERP_VERIFY_URL}` from `/etc/default/derper` (currently `http://127.0.0.1:9099/derp/admit`) | admission controller |
| `-verify-client-url-fail-open` | `false` | if the controller can't be reached, the client is **rejected** (the default is `true`) |

### Logging
derper has no flag to turn off per-connection logging. It always logs failed or rejected connections with the client IP and node key, plus TLS handshake errors from scanners. Steps taken to keep logs small:
- The unit sets `LogRateLimitIntervalSec=60` / `LogRateLimitBurst=100`.
- journald keeps at most 200 MB for 7 days.
- derp-admit logs nothing.
- No access log, no mesh, no `-verify-clients`.

For zero logging you would have to patch derper, or set `StandardOutput=null`/`StandardError=null`, which would also hide certificate errors. Not done.

### systemd unit — `/etc/systemd/system/derper.service`
```ini
[Unit]
Description=Tailscale DERP relay (sticklink, relay-tor1.stickllm.com)
Documentation=https://tailscale.com/kb/1118/custom-derp-servers
Wants=network-online.target derp-admit.service
After=network-online.target derp-admit.service nftables.service

[Service]
Type=simple
User=derper
Group=derper
EnvironmentFile=/etc/default/derper
ExecStart=/usr/local/bin/derper \
    -hostname relay-tor1.stickllm.com \
    -certmode letsencrypt \
    -certdir /var/lib/derper/certs \
    -c /var/lib/derper/derper.key \
    -a :443 \
    -http-port 80 \
    -stun \
    -stun-port 3478 \
    -home blank \
    -verify-client-url ${DERP_VERIFY_URL} \
    -verify-client-url-fail-open=false
Restart=always
RestartSec=5

# State (node key + Let's Encrypt certs) lives in /var/lib/derper
StateDirectory=derper
StateDirectoryMode=0700
UMask=0077

# Privileges: only allowed to bind ports < 1024
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes

# Sandboxing
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
ProtectProc=invisible
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
LimitNOFILE=65536

# Minimal logging: derper has no flag to silence per-connection errors, so rate-limit them
LogRateLimitIntervalSec=60
LogRateLimitBurst=100

[Install]
WantedBy=multi-user.target
```

`/etc/default/derper`:
```
# /etc/default/derper — runtime settings for derper.service
# Admission controller derper asks about every client (POST, expects HTTP 200 + {"Allow": true|false}).
# Placeholder: local deny-all stub (derp-admit.service). Swap for the real sticklink signalling endpoint later.
DERP_VERIFY_URL=http://127.0.0.1:9099/derp/admit
```

### Admission stub — `/etc/systemd/system/derp-admit.service`
```ini
[Unit]
Description=sticklink DERP admission controller (deny-all placeholder)
Before=derper.service

[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/sticklink/derp-admit.py
DynamicUser=yes
Restart=always
RestartSec=2
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
LockPersonality=yes
SystemCallArchitectures=native
CapabilityBoundingSet=
IPAddressAllow=localhost
IPAddressDeny=any
MemoryMax=64M

[Install]
WantedBy=multi-user.target
```
`/usr/local/lib/sticklink/derp-admit.py`:
```python
#!/usr/bin/python3
"""Deny-all DERP admission controller for sticklink (placeholder).

derper POSTs a JSON tailcfg.DERPAdmitClientRequest {"NodePublic": "...", "Source": "ip"}
to -verify-client-url and expects HTTP 200 with a tailcfg.DERPAdmitClientResponse
JSON body {"Allow": bool}. Any non-200 or non-JSON reply is also treated as a reject.
This stub answers {"Allow": false} to everything, so no client may use the relay
until the real sticklink signalling service replaces it. It logs nothing.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DENY = b'{"Allow": false}\n'

class H(BaseHTTPRequestHandler):
    server_version = "derp-admit-deny"
    sys_version = ""
    def _deny(self):
        n = int(self.headers.get("Content-Length") or 0)
        if 0 < n <= 4096:
            self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(DENY)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(DENY)
    do_POST = do_GET = do_HEAD = do_PUT = _deny
    def log_message(self, *a):  # no per-request logging
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 9099), H).serve_forever()
```

#### Admission protocol (from derper v1.104.4 source: `derp/derpserver/derpserver.go` `verifyClient`, `tailcfg/derpmap.go`)
- Request: for every new client, derper sends `POST <verify-client-url>` with JSON `{"NodePublic":"nodekey:<64 hex>","Source":"<client IP>"}` (`tailcfg.DERPAdmitClientRequest`). The timeout is 5 s.
- Response: must be HTTP **200** with JSON `{"Allow": true}` to admit (`tailcfg.DERPAdmitClientResponse`). These are all rejections: `{"Allow": false}`, any non-200 status, or a body that isn't JSON. Unreachable or timed out is also a rejection, because fail-open=false. Only the first 4 KB of the body is read.
- Trusted mesh peers skip the check. No mesh is configured.

## Verification (2026-10-29, after the reboot)
| Check | Result |
|---|---|
| derper + derp-admit active & enabled, survive reboot | PASS: rebooted at about 08:24 EDT (12:24 UTC). The boot id changed and both came back `active`/`enabled`. nftables, fail2ban, ssh and unattended-upgrades are also active. |
| Valid LE cert at https://relay-tor1.stickllm.com/ | PASS: `curl` without `-k` returns 200 and the cert verifies. Issuer `C=US, O=Let's Encrypt, CN=YE1`. Valid 2026-10-29 11:22:22 UTC to **2027-01-27 11:22:21 UTC**. autocert renews it automatically. |
| STUN on UDP 3478 | PASS on the server: Binding Success with the correct XOR-MAPPED-ADDRESS via 127.0.0.1, the public IPv6, and the public IPv4 (that path goes through Luna Node's NAT). The box can't send outbound UDP: requests to Cloudflare's public STUN also time out, and tcpdump on the relay saw no packets from the box. derper only answers Tailscale-style requests (SOFTWARE="tailnode" + FINGERPRINT); `stun_test.py` sends those. |
| Firewall | PASS: the ruleset is shown above. Only 22/80/443 TCP and 3478 UDP are open, on IPv4 and IPv6. |
| Unauthenticated client can't relay | PASS: `derpdenytest` with a fresh node key finished the DERP handshake and the server closed the connection. The server log showed `rejected: admission controller: nodekey:…/<ip> not allowed`. With derp-admit **stopped**, the client was still rejected (`connection refused`), so derper fails closed. |

## Operations

### Update derper
On the box (or any machine with Go ≥ the version in Tailscale's `go.mod`):
```bash
TAG=$(curl -sI https://github.com/tailscale/tailscale/releases/latest | sed -n 's#^location: .*/tag/\(v[0-9.]*\).*#\1#ip' | tr -d '\r')
git clone -q --depth 1 --branch "$TAG" https://github.com/tailscale/tailscale ts-$TAG && cd ts-$TAG
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 ./build_dist.sh -o ../derper ./cmd/derper   # stamps the release version
../derper -version
# copy the binary to the server (scp/sftp) as /tmp/derper, then on the server:
sudo install -m755 /tmp/derper /usr/local/bin/derper && sudo systemctl restart derper && /usr/local/bin/derper -version
```
Stable Tailscale releases have even minor numbers (1.104.x). Odd minors are unstable. After an upgrade, check `journalctl -u derper -n 20`, curl `https://relay-tor1.stickllm.com/`, and run `python3 stun_test.py`. Clients keep working across derper versions, but rebuild at least every few releases. Also run `go run ./cmd/derpdenytest` to confirm the relay still rejects clients: rebuild needs `relay/ts/cmd/derpdenytest/main.go` copied into the new tree.

### Switch the admission check to the real sticklink signalling service
1. The signalling service must expose an endpoint that accepts `POST` JSON `{"NodePublic":"nodekey:…","Source":"ip"}` and returns `200 {"Allow": true|false}` within 5 s. Use HTTPS, or a private, authenticated path. The request isn't authenticated by derper, so restrict who can call the endpoint, for example with a secret path or an mTLS/WireGuard tunnel. Its answer decides who can use the relay.
2. On the relay: `sudo sed -i 's#^DERP_VERIFY_URL=.*#DERP_VERIFY_URL=https://signal.stickllm.com/derp/admit#' /etc/default/derper && sudo systemctl restart derper`. Keep `-verify-client-url-fail-open=false` in the unit.
3. Check that `systemctl show derper -p ExecStart` shows the new URL. An unknown key must still be rejected (`derpdenytest`), and a key the service issued must be admitted.
4. After that, run `sudo systemctl disable --now derp-admit`. You can keep it installed as an emergency "lock the relay" switch: point `DERP_VERIFY_URL` back at `http://127.0.0.1:9099/derp/admit`.
5. If the endpoint is remote, the unit's `RestrictAddressFamilies`/sandbox already allows outbound IPv4/IPv6 HTTPS. The system CA roots under `/etc/ssl/certs` are readable under `ProtectSystem=strict`.

### Rebuild on another provider (portability)
Nothing here is specific to Luna Node except its security group.
1. Create a Debian 12 VM with a public IPv4 (and IPv6 if available) and your SSH key for a sudo user. Open TCP 22/80/443 and UDP 3478 in the provider's cloud firewall.
2. Point `relay-<site>.stickllm.com` A/AAAA records at it. In Cloudflare they must be **DNS-only (grey cloud)**: DERP and STUN can't go through the proxy, and the HTTP-01 challenge needs to reach port 80 directly.
3. Copy `relay/derper` (or a fresh build), `relay/install.sh` and `relay/files/` to the server. Run `sudo HOSTNAME_FQDN=relay-<site>.stickllm.com ./install.sh`, then open a second SSH session to make sure key login still works before you log out. The script adds a 1 GB swapfile only if there's no swap.
4. Optional: to keep the same DERP server identity, copy `/var/lib/derper/derper.key` from the old host. Clients pin the DERP server by hostname/TLS, not by this key, so a new key is fine. The certificate is re-issued automatically.
5. Run the checks in the Verification table again.
6. ARM hosts: build with `GOARCH=arm64`.
