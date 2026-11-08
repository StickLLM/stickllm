# sticklink: Hosting Options (Canadian relay VPS + portable signalling)

All prices below were fetched on **2026-10-28**. Currencies are as the provider lists them: **OVHcloud is in CAD, the others are in USD**. Where I convert USD to CAD, I use a rate of about **1.40 CAD per USD**. That rate is approximate and I did not verify it. No prices include tax (13% HST in Ontario), and I did not sign up for or contact any provider.

## 1. Recommendation (TL;DR)

**Run one small VPS in a Canadian datacentre with both derper and the signalling server on it.** Use Cloudflare only for free DNS (and optionally its free proxy, for signalling only). Write the signalling code against Hono so the same code can be deployed to Node/Bun on any VPS, or back onto Cloudflare Workers later.

| Choice | Monthly | Why |
|---|---|---|
| **Primary: OVHcloud VPS-1, Beauharnois QC (BHS)** | **CAD 7.30** with no commitment (CAD 6.93 on a 6-month term, CAD 6.20 on a 12-month term). The catalog also lists a mandatory daily-backup add-on at CAD 0.60, which may make the real price about CAD 7.90. **Confirm at checkout.** | Traffic is **unmetered at 500 Mbps**, so there is no bandwidth bill shock. It comes with 2 vCores, 4 GB RAM, 40 GB NVMe, IPv4 and IPv6, and anti-DDoS. |
| **Low-traffic alternative: LunaNode m.1s, Toronto (Canadian company)** | **USD 3.50** (about CAD 4.90) | 1 GB RAM and 1 TB transfer. Extra transfer is only USD 0.003/GB. Billing is hourly with no commitment. |
| DNS | $0 | Cloudflare Free DNS. Keep the registrar separate from the DNS host. |
| Certificates | $0 | Let's Encrypt (derper has ACME built in). |
| **Total** | **About CAD 7.30–7.90/month** (OVH), or **about CAD 4.90/month** (LunaNode), plus a domain at roughly USD 10–15/year | |

**How this stays portable:** every piece is a stock Linux binary or service (derper, a Node/Bun process, Caddy or certbot). If a price goes up, you rebuild on another provider with the same cloud-init/Ansible script, lower the DNS TTL, switch the A/AAAA records, and you're moved. Keep one cheap hourly-billed account warm (LunaNode, Vultr, DigitalOcean or Linode, all in Toronto) so you can move within an hour.

**Rule of thumb for choosing a plan:** relayed bytes count once as egress (the receiving side is free on most providers). Under about 1 TB/month of relay egress, LunaNode is the cheapest option. Well above 1–2 TB/month, OVH's unmetered traffic wins.

## 2. Canadian VPS options (cheapest plans that work)

| Provider | Plan | Price | vCPU / RAM | Included transfer | Overage | IPv4 / IPv6 | Canadian DC | Source |
|---|---|---|---|---|---|---|---|---|
| **OVHcloud** | VPS-1 | **CAD 7.30/mo** with no commitment; CAD 6.20 on 12 months | 2 / 4 GB, 40 GB NVMe | **Unlimited, 500 Mbps** | n/a | Yes / Yes | Beauharnois QC (BHS). Toronto is **not** offered for VPS. | https://www.ovhcloud.com/en-ca/vps/ ; catalog API https://ca.api.ovh.com/1.0/order/catalog/public/vps?ovhSubsidiary=CA |
| **LunaNode** (Canadian) | m.1s | **USD 3.50/mo** (hourly) | 1 / 1 GB, 15 GB SSD | 1000 GB | **USD 0.003/GB** | Yes (1 free floating IP) / Yes (SLAAC; /64 per network) | Toronto (Cogent, 245 Consumers Rd) | https://www.lunanode.com/pricing ; https://www.lunanode.com/locations ; https://wiki.lunanode.com/index.php/Frequently_asked_questions |
| **Akamai / Linode** | Nanode 1GB (g6-nanode-1) | **USD 5.00/mo** | 1 / 1 GB, 25 GB | 1 TB (pooled) | **USD 0.005/GB** (no Toronto surcharge) | Yes / Yes | Toronto (ca-central) | Public API https://api.linode.com/v4/linode/types and https://api.linode.com/v4/network-transfer/prices ; https://www.akamai.com/cloud/pricing |
| **Vultr** | Cloud Compute vc2-1c-1gb | **USD 5.00/mo** | 1 / 1 GB, 25 GB | 1 TB (pooled) | USD 0.01/GB | Yes / Yes | Toronto (yto) | https://www.vultr.com/pricing/ ; public API https://api.vultr.com/v2/plans |
| Vultr | High Perf vhp-1c-1gb | USD 6.00/mo | 1 / 1 GB NVMe | 2 TB | USD 0.01/GB | Yes / Yes | Toronto | same |
| **DigitalOcean** | Basic 512 MiB | **USD 4.00/mo** | 1 / 0.5 GiB, 10 GiB | 500 GiB (pooled) | USD 0.01/GiB | Yes / Yes | Toronto (TOR1) | https://www.digitalocean.com/pricing/droplets ; https://docs.digitalocean.com/platform/billing/bandwidth/ |
| DigitalOcean | Basic 1 GiB | USD 6.00/mo | 1 / 1 GiB | 1000 GiB | USD 0.01/GiB | Yes / Yes | Toronto | same |
| RackNerd | KVM 512 MB | USD 26.99/**yr** (about 2.25/mo) | 1 / 0.5 GB | 500 GB @ 1 Gbps | ? | Yes / **No IPv6 in Toronto** | Toronto | https://www.racknerd.com/kvm-vps |
| GreenCloud VPS | BudgetKVMCA-2 | USD 25/**yr** | 2 / 4 GB | 4 TB @ 10 Gbps | ? | Yes / /64 | Toronto | https://greencloudvps.com/billing/store/budget-kvm-sale (**0 in stock** today, no refunds) |

**Excluded:**
- **Hetzner:** no Canadian location (EU, Hillsboro OR, Ashburn VA, Singapore).
- **Contabo:** no Canadian region (its nearest is US-East New York, with a location fee). Source: https://help.contabo.com/en/support/solutions/articles/103000269774-what-is-the-location-fee-
- **BuyVM:** Las Vegas, New York and Luxembourg only.
- **Vultr USD 2.50/3.50 plans:** not offered in Toronto, per the public API's `locations` field.

**Not checked:** Canadian Web Hosting (the product URL returned 404). Annual-prepay "deal" hosts (RackNerd, GreenCloud) are cheap but are a single-vendor gamble. They conflict with the requirement for reputable providers and lack IPv6 or stock.

## 3. derper findings (source: tailscale/tailscale `main`, fetched 2026-10-28)

- **Sources:** https://github.com/tailscale/tailscale/blob/main/cmd/derper/derper.go , `derp/derpserver/websocket.go` , `tailcfg/derpmap.go` , https://tailscale.com/kb/1118/custom-derp-servers
- **Install:** `go install tailscale.com/cmd/derper@latest`. Rebuild periodically.
- **Ports:** TCP 80 (HTTP, used for the ACME HTTP-01 challenge), TCP 443 (HTTPS/DERP) and UDP 3478 (STUN; turn it off with `-stun=false` if you don't need it). Allow ICMP.
- **No proxies in front of the relay.** Tailscale says DERP must have direct internet access, **not behind NAT or load balancers**, because it needs real source IPs and HTTP Upgrade. So the relay hostname must be a **DNS-only (grey-cloud)** record in Cloudflare, not proxied.
- **Certificates:** `-certmode=letsencrypt` is the default, with `-hostname=relay.example.com` and `-certdir`. Let's Encrypt is built in, so derper needs no separate certbot. `--acme-ip-certs` (IP-only certs) also exists.
- **WebSocket / browser support:** yes. `/derp` is wrapped with `derpserver.AddWebSocketSupport`. It accepts `Upgrade: websocket` with the `Sec-WebSocket-Protocol: derp` subprotocol and binary frames. Compression is disabled, and `OriginPatterns: ["*"]` means any origin is accepted. The code comment says the browser client (tsconnect/wasm) can only reach DERP via WebSocket.
  - **Caveat:** inside the WebSocket the client still has to speak the **DERP framing and key handshake** (Curve25519 node key, NaCl box). A sticklink browser client needs a DERP client implementation in JS or Go-WASM. This is not trivial. Budget engineering time for it, or use Tailscale's Go `derphttp` client compiled to WASM.
- **Client gating:**
  - `--verify-clients` checks clients through a **local tailscaled**. It only fits a Tailscale tailnet, so it is **not suitable** for sticklink.
  - **`--verify-client-url=<URL>`** is the one to use. derper POSTs JSON `{"NodePublic": <node key>, "Source": <client IP>}` (tailcfg.DERPAdmitClientRequest) and expects `{"Allow": true|false}`.
    - **There is no custom token field.** The gate works on the DERP node public key.
    - **Suggested design:** when signalling issues a session, the client registers its DERP public key with the signalling server (authenticated by your signed token). Signalling stores an allow-list with expiry. derper's admission URL points at a localhost endpoint on the signalling server (for example `http://127.0.0.1:8787/derp-admit`), which answers Allow only for registered keys.
  - **Set `--verify-client-url-fail-open=false`.** The default is **true**, which admits everyone if the admission URL is unreachable.
  - Extra hardening: `-accept-connection-burst`, plus an experimental `-rate-config` JSON for rate limits.
- **Resources:** I found **no official minimum spec** (unverified). derper is a single Go binary and the work is mostly bandwidth and TLS. A 1 GB RAM / 1 vCPU VM is commonly enough for a small relay. 512 MB probably works for light use, but leaves less headroom if signalling shares the box. Practical floor: **1 GB** when signalling is co-hosted. Watch NIC throughput (OVH caps VPS-1 at 500 Mbps).

## 4. Signalling portability

| Option | Monthly cost | Lock-in | Notes |
|---|---|---|---|
| **(a) Cloudflare Workers + Durable Objects, with Hono** | $0 within Free limits. Paid is a USD 5/mo minimum. | Medium | Hono's `upgradeWebSocket` has adapters for **Cloudflare Workers, Node (`@hono/node-server` + `ws`), Bun and Deno** (https://hono.dev/docs/helpers/websocket), so the routing code is portable. **The Durable Objects state/hibernation API is not portable**, so wrap room state behind an interface (in-memory Map on a VPS, a DO on Cloudflare). Free plan: DO requests are capped at 100k/day and 13,000 GB-s/day, and **once a free limit is exceeded, operations fail with errors.** Incoming WS messages bill at 20:1 (https://developers.cloudflare.com/durable-objects/platform/pricing/). The derper admission URL would then have to call out to Workers over the internet (more latency, and a failure mode). |
| **(b) Signalling on the same VPS from day one (recommended)** | $0 extra | Lowest | One Node/Bun process with Hono and an in-memory room map. It shares the box with derper, so the admission check is a localhost call. Fully portable. Downside: the VPS is a single point of failure for both signalling and relay. That's acceptable at this stage; mitigate with the rebuild script and a short DNS TTL. Keep the Hono code adapter-clean so (a) stays available as a fallback. |
| (c) Separate cheap VPS for signalling | +USD 3.50–5 | Low | Isolation and redundancy. Not worth paying for yet. |

**Port layout for (b):**
- derper owns 443/80 on `relay.example.com` (DNS-only).
- Signalling listens on **8443** with its own Let's Encrypt cert (Caddy or certbot DNS-01, so it doesn't clash with derper on port 80).
- Optionally, put `signal.example.com` behind the free Cloudflare proxy (orange cloud). Cloudflare proxies WebSockets and supports origin port 8443, which hides the origin IP. Leaving Cloudflare later just means pointing clients to `wss://signal.example.com:8443` directly.

**Alternative layout:** run a second public IPv4. OVH, Linode and others charge for extra IPs. I did not price this.

## 5. Domain, DNS and certificates

- **Registrar:** keep it separate from DNS hosting and from the VPS provider. Use a registrar that supports easy auth-code transfers, such as Porkbun, Namecheap or Cloudflare Registrar (at-cost).
  - Note the ICANN 60-day transfer lock after registration or transfer.
  - **.ca** domains need CIRA's Canadian Presence Requirements (Nink Inc. qualifies). Cloudflare Registrar may not support .ca (**unverified**).
- **DNS:** Cloudflare Free. Its BIND zone export makes moving to deSEC, Bunny DNS or the registrar's own DNS easy. Avoid Cloudflare-only features (Workers routes, origin certs, Tunnel) in the critical path.
- **Certificates:** Let's Encrypt everywhere (derper autocert, plus Caddy or certbot for signalling). Don't use Cloudflare Origin CA certs, because they only work behind Cloudflare.

## 6. Unverified / to confirm before buying

1. **OVH:** whether the CAD 0.60 "auto-backup" add-on is actually charged on VPS-1 (the catalog marks it mandatory), and Quebec/Canada tax handling. OVH also has a Toronto DC, but the VPS catalog lists only BHS for Canada.
2. **Vultr:** prices may vary by location (the API shows uniform prices for yto).
3. **RackNerd:** overage policy and promo deals.
4. **Real resource use of derper** at your expected concurrency. Load-test it.
5. **USD→CAD rate** of about 1.40 is approximate.
6. **Canadian Web Hosting** and other Canadian hosts (for example WebHosting.net/Netfirms) were not checked.
