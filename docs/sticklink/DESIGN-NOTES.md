# sticklink rendezvous server: design notes (from StickLLM bot, 2026-10-28)

Status: these are notes on the decisions Nink has made in chat. There is no formal architecture doc yet. Nothing has been approved for build or deploy (the 2026-10-28 relay change is design-only).
Repo: StickLLM/sticklink on GitHub (private, created by Nink 2026-10-28; empty or near-empty as far as I know). Related private repos: stickios and stickdroid (iPhone and Android clients), plus stickapp (role not yet stated).

## Purpose
One rendezvous service shared by StickLLM (a bootable secure-app USB with private AI) and AI KVM, Nink's KVM client that drives corporate PCs via AI. Clients (phone, browser, client stick, AI KVM) find the user's StickLLM server and connect to it. It's a hosted service, not a product. Paid connection subscriptions are the business model, so it will need account and subscription checks (design TBD).

## Decisions Nink has made
1. **Handshake-only signalling (revised 2026-10-28 9:00 PM ET, approved by Nink via AI KVM).** The rendezvous server does discovery, pairing and signalling, then gets out of the loop. It never carries device traffic. The old rule "Nink Inc. runs no relay" is replaced by decision 4: a Nink Inc.-run relay is allowed only as a fallback, and only for end-to-end encrypted traffic.
2. **Transport for signalling:** a secure WebSocket (TCP/443). No UDP server is needed on our side.
3. **Data path:** a direct peer-to-peer connection via UDP hole punching, using free public STUN servers.
4. **Fallback when direct fails (revised 2026-10-28 9:00 PM ET):** traffic falls back to a Nink Inc.-run DERP relay (Tailscale's relay protocol, TLS over TCP/443) on a small Canadian VPS. AI KVM's firmware already has a DERP client (microlink). Reason: AI KVM can't run Tor, and hotel, mobile and CGNAT networks often break UDP hole punching. **Hard rule:** the relay carries only traffic that is end-to-end encrypted with the keys pinned at QR pairing. It sees only metadata and could drop traffic, but it can't read or MITM it, so zero trust (decision 6) holds. Keep metadata logging minimal. The StickLLM stick's Tor onion service stays as an extra option for StickLLM (Tor is slow, so it suits chat and files, not live voice). Alternative considered and rejected: Cloudflare Realtime TURN (US$0.05/GB), because the AI KVM board has no TURN client.
5. **Live voice:** a local agent on the phone or client runs speech-to-text and text-to-speech, and only text crosses the link.
6. **Zero trust (from 2026-10-12):** trust comes only from the key fingerprint pinned at QR pairing. End-to-end encryption means the rendezvous server (and Nink himself) can't read or impersonate connections. A compromised sticklink must not be able to MITM a paired connection.
7. **Hosting:** Cloudflare, on its free tier. Cloudflare Pages for the website, and Workers plus Durable Objects for the API and the WebSocket signalling and matchmaking. The Vercel project was deleted, and Vercel serverless can't hold long-lived WebSockets anyway.
8. **Licensing:** the code stays in a private repo, owned by Nink Inc. The public StickLLM code is PolyForm Noncommercial 1.0.0, with a commercial license included with each device purchase or subscription.

## Open items for review
- Cloudflare free-tier limits (Workers requests, Durable Objects and WebSocket hibernation, Pages) against expected use. I haven't verified these yet.
- Account and subscription model, and how a paid subscription gates signalling.
- Pairing flow details: the QR payload, re-pairing, revocation, and multiple clients.
- How often direct UDP fails on mobile carriers or CGNAT, and the UX for the relay and Tor fallbacks.
- Relay: which Canadian VPS, relay auth via the subscription, and the metadata retention policy.
- An earlier, now-superseded idea: Plex-style per-server subdomains with Let's Encrypt DNS-01 certs for LAN HTTPS. Decide whether sticklink still answers DNS-01, or whether pinned-key pairing replaces it.
- Shared protocol between StickLLM and AI KVM. AI KVM (another of Nink's bots) has its own client-side needs.
