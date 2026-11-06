# Models

## Distribution: small stick, download the rest

**Problem:** Baking a 24 GB–tier model into every ISO forces a fast **64 GB** stick even
when the user only has an **8 GB** GPU. That is expensive and wasteful.

**Design:** ship a **small base image**; upgrade models on demand from a **pinned
Hugging Face catalog**, with hashes that live on the USB.

**Advertised minimum host:** **16 GB** system RAM + **8 GB** GPU
([HARDWARE.md](HARDWARE.md)). Do not market weaker GPUs (e.g. 4 GB) as supported.

| Image | Approx size | Stick | What’s on it |
|---|---|---|---|
| **Base (default ship)** | ~6–8 GB ISO | **16 GB** USB is enough; **32 GB** preferred | OS + runtime + **7B Q4_K_M** (~4.4 GB; 8 GB GPU @ 32K) |
| **Optional fat build** | ~18–22 GB | 32–64 GB | Base + large model pre-baked (power users / air-gap) |

**v0.6.7+** bakes **Qwen2.5-7B Instruct Q4_K_M** (official split GGUF under
`/opt/stickllm/models/appagent/`, catalog id `qwen25-7b-q4km`). That is the Open
model / probe default. **Q5_K_M** stays a pinned optional download (catalog
`min_vram_gb = 10`) — slightly better quality, but tight on a true 8 GB card at
the Agent Zero **32K** floor. **Qwen3.5-4B** stays an **optional catalog download**
(`probe_recommend = false`); it is **not** baked and not on the Open model screen.

**v0.3.8** and earlier 0.3.x ships baked both the **3B** and the **7B**. **v0.3.9**
baked the 3B only. Mid-0.5.x / 0.6.x through 0.6.6 baked **Qwen3.5-4B**. Optional
durable store: encrypted SSD vault ([VAULT.md](VAULT.md)).

## First boot / “upgrade models” flow

When StickLLM has network (and the user is not in pure offline mode):

1. Detect **GPU VRAM** (NVIDIA: **sum** of cards for CUDA multi-GPU; Vulkan/AMD:
   largest single card only / fail → RAM-only tier).  
2. Detect **free space on the USB** (and optional host cache — see below).  
3. Contact **Hugging Face** only for catalog entries we already list (allow-list URLs).  
4. Show **suitable models** for that VRAM + free space.  
5. **Highlight the optimum** (largest tier that fits VRAM *and* disk, with useful context headroom).  
6. **If the user does nothing for ~30 seconds → auto-download the highlighted model.**  
7. After download: **SHA-256 verify against hashes on the USB catalog** → only then activate.  
8. If verify fails: delete the blob, keep running the baked-in lite model, show error.

Offline / high-risk: skip network; run baked-in lite only. No auto-download without
connectivity; no mystery URLs outside the catalog.

### Where the UI lives

| Surface | When |
|---|---|
| First-boot console / bootstatus | Probe + 30s countdown + list |
| Chat UI menu (**Models → Download…**) | Anytime after boot (v0.x) |
| iOS / Android app | Later — same catalog API / URLs |

“Do nothing → auto pick best” applies to the **first-boot / first-network** prompt.
In the chat menu, download stays **explicit** (no surprise mid-session pulls).

## Trust: hashes on the USB

**TODO (design later):** downloads for models *not* on the approved/pinned list —
where the list lives (today: `config/models/catalog.toml` on the USB), how it
updates (shipped ISO vs signed OTA catalog), and UI warning + hash policy for
ad-hoc / host-found GGUFs. No full approved-list system yet.

Model weights are executable behavior. StickLLM never treats “a GGUF from the
internet” as trusted just because Hugging Face hosted it.

| Piece | Role |
|---|---|
| **`config/models/catalog.toml` on the USB** | Allow-list: HF repo, filenames, **SHA-256**, approx size, min VRAM |
| **Download** | Only those files; abort if free space &lt; size + margin |
| **Verify** | Hash must match USB catalog before load |
| **Reject** | Wrong hash → discard; do not fall back to unverified weights |

Swapping a file next to the stick does nothing useful unless the attacker also
rewrites the StickLLM image (at which point they already own the stick).

See [THREAT-MODEL.md](THREAT-MODEL.md) — open weights ≠ safe weights; abliterated
merges stay out of the default catalog unless we pin and test them ourselves.

## VRAM / RAM tiers (supported recommends)

StickLLM stays on the **Qwen** family only (no Moondream / SmolVLM / random merges).
One **recommend** per advertised tier (probe picks the highest `quality_rank` that
fits detected VRAM + free disk). Other catalog rows may still download manually.

| Tier | Role | Catalog id | Model | Approx size | Notes |
|---|---|---|---|---|---|
| **8 GB** | **Installed default (baked)** | `qwen25-7b-q4km` | Qwen2.5-7B Instruct **Q4_K_M** | ~4.4 GB | Open model / probe default @ 32K |
| **12 GB** | Optional download | `qwen25-14b-q4km` | Qwen2.5-14B Instruct **Q4_K_M** | ~9.0 GB | 32K on a 12 GB card |
| **16 GB** | Optional download | `qwen25-32b-q3km` | Qwen2.5-32B Instruct **Q3_K_M** | ~15.9 GB | 32K may shrink / light offload |
| **24 GB** | Optional download | `qwen38-27b-q4km` | Qwen3.8-27B **Q4_K_M** | ~16.3 GB | RTX 3090 class; 32K headroom |
| **32 GB** | Optional download | `qwen25-32b-q4km` | Qwen2.5-32B Instruct **Q4_K_M** | ~19.9 GB | Comfortable 32K on 32 GB |
| **Dual 24 GB** | Optional download | `qwen25-72b-q3km` | Qwen2.5-72B Instruct **Q3_K_M** | ~37.7 GB | CUDA **tensor-split** across both cards (~48 GB pooled). Probe **sums** NVIDIA VRAM. Vulkan stays one-card (no cross-GPU split). Q4 (~47 GB) is too tight for 48 GB + KV. |

**Also in catalog (not tier recommends):**

| Catalog id | Role |
|---|---|
| `qwen35-4b-q4km` | Optional download for weak GPU / RAM-only — **not** baked, **not** Open default, `probe_recommend = false` |
| `qwen25-7b-q5km` | Optional 7B Q5 (needs ~10 GB); prefer Q4 on true 8 GB @ 32K |
| `qwen25-3b-q4km` | Optional small download |

Rule: **never load or advertise mmproj on RAM-only / failsafe paths.** Vision pins
(Qwen2.5-VL + mmproj) remain separate when added later.

Exact filenames and hashes: `config/models/catalog.toml`.

### Optimum picker (sketch)

```
eligible = models where min_vram ≤ detected_vram
           and approx_size + margin ≤ free_usb_or_cache
highlighted = max(eligible by quality rank)   # e.g. 24 > 16 > 12 > 8 > lite
countdown 30s → download(highlighted) unless user picks another / Cancel
```

If nothing larger than the baked-in model fits, skip the prompt (or show “USB full”).

### Speed vs quality (3090 ballpark)

| Model | Generate |
|---|---|
| Lite / 7–8B | ~100+ tok/s |
| 27B Q4 | ~35–45 tok/s |

## First-boot USB storage (required for durable models)

A DD-flashed ISO leaves most of a 32/64 GB stick **unallocated**. First boot must
**interrogate the USB** that StickLLM booted from and offer to claim that free
space so downloads survive reboot.

1. Detect boot device (the StickLLM USB only — never auto-touch internal disks).  
2. Show size, free/unallocated space, proposed `STICKLLM-DATA` partition.  
3. User confirms (or countdown accepts on first-boot setup).  
4. Create the data partition in unallocated space; label `STICKLLM-DATA`.
   Also reserve about **256 MB** at the end of that free space for the USB
   settings partition. It is not inside the ISO. Do not shrink an existing
   `STICKLLM-DATA` that already fills the stick.
5. Layout:
   - `STICKLLM-DATA/models/` — verified GGUFs (hash vs USB catalog before use)
   - USB settings partition — LUKS with the SSD vault passcode; per-computer
     vault locations and portable secrets. Not voice weights, not chats
   - SSD vault blob — chats (and the models folder the user chose)
6. Later boots: mount DATA if present; leave the settings partition locked
   until the vault passcode is entered. If DATA is missing or corrupt, fall
   back to lite-in-RAM.

**Rules:** only the boot USB; never shrink existing host partitions; refuse if
the stick looks like a full disk clone of something else; confirm before write.

64 GB stick ≈ same boot image + ~50 GB `STICKLLM-DATA` for models, plus about 256 MB for the settings partition.

## Encrypted vault: models + context (optional, increases risk)

People may want **chats / context** (and optionally model blobs) saved on the USB
or an internal SSD, encrypted at rest.

| Mode | Default | Notes |
|---|---|---|
| Ephemeral (RAM only) | **On** | Safest; reboot clears chats |
| USB `STICKLLM-DATA` models | Off until first-boot claim | Needed for download SKU |
| Encrypted **context vault** (USB or user-chosen SSD file) | **Off** | Passphrase unlock in UI (not at boot) |
| Wipe-after-N-fail (e.g. 3 bad passwords → delete vault) | **Off** | Duress / anti-coercion; see threat model |

Wipe-after-N is a deliberate **risk increaser**: typo lockouts, power loss mid-prompt,
and “evidence of destruction” can all hurt the user. Never enable by default;
require a typed confirm phrase and show the downside in the UI.

SSD path: same as before — **user-chosen data partition / file only**, refuse
EFI/system/BitLocker, hash models against USB catalog after unlock.

| Concern | Reality |
|---|---|
| **Integrity (models)** | SHA-256 on **USB catalog**; blob must match |
| **Confidentiality** | Encryption at rest; live session still exposes plaintext in RAM/VRAM |
| **Context on disk** | Seizable if unlocked or passphrase known; ephemeral is safer |
| **Wipe-after-N** | Optional; can destroy your own data; not a legal shield |

## Implementation sketch

```
config/models/catalog.toml        # tiers, HF pins, sha256 (trust anchor)
overlay/.../stickllm-usb-claim    # first-boot: STICKLLM-DATA + ~256 MB settings slot
overlay/.../stickllm-usb-settings # LUKS that slot with the vault passcode
overlay/.../stickllm-model-probe  # VRAM + free space on DATA → optimum
overlay/.../stickllm-model-menu   # first-boot 30s + chat “Download models”
overlay/.../stickllm-model-fetch  # HF download + verify + activate on DATA
overlay/.../stickllm-vault        # optional encrypted context (+ wipe-after-N)
overlay/.../stickllm-model-cache  # opt-in SSD model/context file
ui/ … Models + Vault menu entries
```

v0.1: baked Qwen2.5-7B; helpers stubbed. Next: USB claim → pin hashes →
probe + download → optional vault.

## Related

- [THREAT-MODEL.md](THREAT-MODEL.md) — model trust + SSD cache  
- [HARDWARE.md](HARDWARE.md) — GPU profiles  
- [BOOT.md](BOOT.md) — boot menu  
- [FLASH.md](FLASH.md) — imaging  
