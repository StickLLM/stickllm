# StickLink app-mux v1 (browser DataChannel)

Phase 0 lock for Phase 1 lab. Noise transport plaintext is UTF-8 JSON after
Method C IKpsk2 + pair_psk confirm. All Agent Zero application traffic uses
these types on the authenticated DataChannel. No cleartext HTTP/WS to the stick
from the browser after `agent_ready`.

## Session binding

- Mux opens only after `agent_ready` on that DC session.
- Every `http_*` / `ws_*` stream is bound to that session; closing the DC aborts all streams.
- Server may only target local Agent Zero / StickLLM paths (allowlist below).

## Allowlist (server)

Permit only:

- `/agent-zero` and subpaths
- `/socket.io` and subpaths  
- `/api/agent`, `/api/csrf_token`, `/api/pair/status` (if required by embed)
- static prefixes already used by A0 under `/agent-zero/…`

Reject everything else with `http_res` status 403 `forbidden path`.

## Chunking

Max Noise PT body recommendation: **48 KiB** decoded payload per JSON message.

- Small HTTP body: inline `body_b64` on `http_req` / `http_res`.
- Large body: `body_b64` omitted; `body_len` set; followed by `http_chunk` frames:
  - `{ "t":"http_chunk", "id":"…", "role":"req"|"res", "seq":0…, "eof":false|true, "body_b64":"…" }`
- Reassembly cap: **8 MiB**. Overflow → error, stream reset.
- **Never truncate** silently (no `x-sticklink-truncated`).

## HTTP

```json
{ "t":"http_req", "id":"r1", "method":"GET", "path":"/agent-zero/…", "headers":{…}, "body_len":0 }
{ "t":"http_res", "id":"r1", "status":200, "headers":{…}, "body_len":1234 }
```

Headers: subset only (content-type, accept, x-csrf-token, x-stickllm-client, …).
Strip Hop-by-hop. Cookie jar lives on the **stick/lab bridge** (CSRF session), not in the browser jar for stick HTTPS.

Backpressure: client allows at most **4** concurrent HTTP streams; server processes FIFO per session with a bounded queue.

## WebSocket (Socket.IO)

Browser uses a **WebSocket transport adapter** (constructor patch / factory), not a Service Worker.

```json
{ "t":"ws_open", "id":"w1", "url":"/socket.io/?EIO=4&transport=websocket", "protocols":[] }
{ "t":"ws_opened", "id":"w1" }
{ "t":"ws_data", "id":"w1", "binary":false, "body_b64":"…" }   // chunk via http_chunk-style if large: ws_chunk
{ "t":"ws_chunk", "id":"w1", "seq":0, "eof":true, "body_b64":"…", "binary":false }
{ "t":"ws_close", "id":"w1", "code":1000, "reason":"" }
{ "t":"ws_error", "id":"w1", "message":"…" }
```

Upstream: bridge opens real WS to local Agent Zero. DC `bufferedAmount` high-water → pause reading upstream until drained.

## Control

- `ping` / `pong` (existing)
- `close` (existing) — tears down mux + DC

## Out of scope (Phase 1)

- Moving peer onto stick `sticklinkd` (Phase 2)
- DERP-over-WS for browsers
- Native mobile UDP path
