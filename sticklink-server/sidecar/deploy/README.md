<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# sticklink-admit deploy files

NOT applied anywhere. These are for Nink to review before any relay change.

Build: `cd server/sidecar && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o sticklink-admit ./cmd/sticklink-admit`

| File | Goes to |
|---|---|
| `sticklink-admit.service` | `/etc/systemd/system/` (replaces `derp-admit.service`) |
| `admit-keys.example` | `/etc/sticklink/admit-keys` with the production public key |
| `derper.default.note` | notes only; `/etc/default/derper` is unchanged |

See `../../DEPLOY.md` for the full sequence and the rollback.
