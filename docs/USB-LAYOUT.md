# USB layout (one stick vs dual USB)

How StickLLM uses disks after flash. Flash steps: [FLASH.md](FLASH.md). Vault / settings unlock: [VAULT.md](VAULT.md).

## Preferred: everything on one stick

After first-boot claim on a large enough USB, expect roughly:

| Piece | Role |
|-------|------|
| Live ISO / boot partitions | Read-only-ish system from the flashed image |
| `STICKLLM-DATA` | Models, docker graph (`stickllm-docker`), optional vault pointer / `vault.key` |
| `STICKLLM-SETTINGS` (~256 MB LUKS) | Pairing hints, HF token, portable secrets; opened with the **same vault passcode** |

**Use this layout when you can.** Boot + DATA + settings on the same physical stick avoids the dual-USB traps below.

Windows often shows **no drive letter** after an isohybrid flash — the disk is still there (Get-Disk / size / bus). That is not “missing USB.”

## Dual USB (lab / reclaim)

Typical lab setup that fails today on **v0.8.8**:

- **Stick A** — freshly flashed boot ISO only (no claimed DATA/settings).
- **Stick B** — older `STICKLLM-DATA` (+ LUKS settings) with models, vault, HF token, Agent Zero graph.

What works today:

- Vault unlock with the passcode can open the vault blob on Stick B’s DATA.
- StickLink may pair.

What breaks on v0.8.8 (**ISS-074**):

- Settings discovery only accepts `STICKLLM-SETTINGS` on the **boot** disk.
- Status can show vault unlocked but Agent stuck `settings_missing` / `agent_not_running`.
- `vault.key` alone does **not** open settings LUKS — you need the vault passcode (or matching keyslot).

**Planned v0.8.9:** open settings on the same disk as mounted DATA when boot has none. Until then, prefer one stick, or manually ensure settings can open on the DATA stick after unlock.

Corrupt Agent Zero docker graph on DATA (`/bin/bash` missing inside the image) is separate (**ISS-075**) — reseed/repair is planned for v0.8.9; lab fix is move bad `stickllm-docker` aside and reseed from `/opt/stickllm/docker`.

## After reflash

Reflashing **erases** the target stick. Models and vault on that stick are gone unless they lived on a **different** DATA stick you kept. After a clean flash:

1. Boot StickLLM.
2. Claim DATA / complete setup on that stick (or attach vault per [VAULT.md](VAULT.md)).
3. Unlock so settings + HF token can persist.
4. Re-download models if needed ([NINFER.md](NINFER.md) / [MODELS.md](MODELS.md)).

## Quick checks

| Check | Healthy |
|-------|---------|
| Boot disk | USB you selected in firmware |
| `STICKLLM-DATA` mounted | Models path writable |
| Settings after unlock | `/mnt/stickllm-settings` present (not `usb_settings: absent`) |
| Agent Zero | `/agent-zero/` HTTP 200 when vault/settings story matches product rules |

Open bake items: [NEXT-0.8.9.md](NEXT-0.8.9.md) (DU1 / AZ1 / VL1).
