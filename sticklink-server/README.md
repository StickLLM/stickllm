<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# sticklink server

Private. Copyright (c) 2026 Nink Inc. All rights reserved. No open-source licence.

The signalling server (Cloudflare Worker + Durable Objects + D1, TypeScript) and the relay
admission sidecar (Go) for sticklink. **Built and tested locally only. Not deployed.**

| Path | What |
|---|---|
| `API.md` | wire protocol, revoked-peer API, routing IDs and mailboxes, relay API, AI KVM profile, local dev |
| `OPEN-QUESTIONS.md` | every decision the specs left open (the conservative option was taken) |
| `DEPLOY.md` | what deploying needs (resources, cost, relay change, rollback). Needs approval. |
| `worker/` | the Worker: `src/`, `migrations/`, `test/` (vitest-pool-workers), `scripts/` (dev vars, fixtures, provisioning, prod secret generation) |
| `sidecar/` | `sticklink-admit`, which serves derper's `-verify-client-url` from the signed allowlist; `deploy/` holds the systemd unit and notes |
| `integration/` | `run.sh`: wrangler dev + sidecar + `derper -dev` + a DERP probe, end to end |
| `vectors/` | `signalling-v2.json`, `ikpsk2-v2.json` and their Python generators |

## Tests

```
cd worker && npm ci && npx tsc --noEmit && npx vitest run      # Worker unit + miniflare integration
cd sidecar && go test -race ./...                                # sidecar unit + fake-Worker tests
integration/run.sh                                               # full local stack incl. real derper (needs ../relay/ts)
#   ports: SL_INT_PORT_WORKER (8787) / SL_INT_PORT_ADMIT (9099); derper -dev is fixed at :3340
e2e/start-stack.sh --detach && e2e/smoke.sh                      # E2E connectivity (E2E.md, ENDPOINTS.md)
e2e/bundle.sh                                                    # dist/sticklink-e2e-bundle.tar.gz for the desktop
```

Regenerate vectors (Python with `cryptography` and `noiseprotocol==0.3.1`):
```
cd vectors && python3 gen_signalling_vectors.py ../../vectors/kvm-usb-v1.json ../../vectors/qr-v1.json signalling-v2.json
python3 gen_ikpsk2_vectors.py signalling-v2.json > ikpsk2-v2.json
```

## For StickLLM: test in a VM

**Please run sticklinkd against this server inside a VM**, not on a real stick or on the host OS (Nink's request).
With QEMU user-mode networking the host is `10.0.2.2`: the WS is `ws://10.0.2.2:8787/v1/ws`, and the dev relay
is `http://10.0.2.2:3340/derp`. Fixtures (test credentials, a home, slots, the relay token) are in
`worker/fixtures/dev-fixtures.json` after `node scripts/seed-dev.mjs --apply`. See API.md §11.

## Copyright header

Every source and doc file starts with `Copyright (c) 2026 Nink Inc. All rights reserved.` JSON files carry it
as a `"//"` or `"_copyright"` key. **Exceptions** (generated, can't carry a header): `sidecar/go.sum` and
`worker/package-lock.json`.
