# Models

## Distribution: small stick, download the rest

**Problem:** Baking a 24 GB–tier model into every ISO forces a fast **64 GB** stick even
when the user only has an **8 GB** GPU. That is expensive and wasteful.

**Design:** ship a **small base image** that runs on almost anything; upgrade models
on demand from a **pinned Hugging Face catalog**, with hashes that live on the USB.

| Image | Approx size | Stick | What’s on it |
|---|---|---|---|
| **Base (default ship)** | ~4–6 GB ISO | **16 GB** USB is enough | OS + runtime + **lite** model (anything / RAM / 8 GB class) |
| **Optional fat build** | ~18–22 GB | 32–64 GB | Base + large model pre-baked (power users / air-gap) |

Current ship **v0.3.6** and checkpoint `v0.2.1-local-nvidia-kbd` ship small text models
on the ISO (3B + 7B class) and download larger catalog entries (e.g. 27B) to
`STICKLLM-DATA` when space/VRAM allow. Optional durable store: encrypted SSD vault
([VAULT.md](VAULT.md)). Target retail base still moves toward a cheaper **16 GB** stick + lite GGUF.

## First boot / “upgrade models” flow

When StickLLM has network (and the user is not in pure offline mode):

1. Detect **GPU VRAM** (`nvidia-smi` / fail → RAM-only tier).  
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

## VRAM / RAM tiers (target catalog)

StickLLM stays on the **Qwen** family only (no Moondream / SmolVLM / random merges).

| Host | What we ship / offer |
|---|---|
| **CPU / no usable VRAM** | **Text-only** Qwen (lite). **No mmproj** — vision not offered. |
| **~8 GB+ NVIDIA VRAM** | Qwen text and/or **Qwen2.5-VL** (GGUF + mmproj) when pinned |
| **16–24 GB** | Qwen **3.8** line; optimum **27B + vision** when pinned |

- **Lite / small VRAM / RAM:** Qwen **3.5** text (base stick target)  
- **Small vision (optional upgrade / later base on GPU sticks):** **Qwen2.5-VL-3B** + mmproj — only if VRAM allows  
- **Larger VRAM (16–24 GB):** Qwen **3.8** line  
- **Optimum on 24 GB (RTX 3090):** **Qwen3.8-27B Q4_K_M + vision (mmproj)** — downloaded, not baked into the cheap stick  

Rule: **never load or advertise mmproj on RAM-only / failsafe paths.**

| Tier | Hardware | Target model (Qwen) | Quant (typical) | Approx size | Notes |
|---|---|---|---|---|---|
| **RAM-only** | No usable GPU / CUDA failed | Qwen3.5 tiny/small instruct | Q4_K_M | ~1–3 GB | Baked into base ISO |
| **8 GB** | 8 GB VRAM | Qwen3.5 ~7–8B class | Q4_K_M / Q5_K_M | ~4–6 GB | Fits 16 GB stick after download |
| **12 GB** | 12 GB VRAM | Qwen3.5 ~14B class | Q4_K_M | ~8–10 GB | Needs ~32 GB stick or host cache |
| **16 GB** | 16 GB VRAM | Qwen3.8 mid / 27B IQ4_XS | Q4 / IQ4_XS | ~12–15 GB | 32–64 GB stick or SSD cache |
| **24 GB** | RTX 3090 class | **Qwen3.8-27B + vision** | **Q4_K_M** + mmproj | ~15–18 GB + ~1 GB | Highlighted when VRAM ≥ 24 and space allows |

Exact filenames and hashes go in `config/models/catalog.toml` when pinned.

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
4. Create **one** data partition in unallocated space; label `STICKLLM-DATA`.  
5. Layout (unencrypted by default for models is OK if user wants speed; prefer
   encrypted vault — see below):
   - `models/` — verified GGUFs (hash vs USB catalog before use)  
   - optional `vault/` — encrypted context / chat export (opt-in)  
6. Later boots: mount if present; if missing/corrupt, fall back to lite-in-RAM.

**Rules:** only the boot USB; never shrink existing host partitions; refuse if
the stick looks like a full disk clone of something else; confirm before write.

64 GB stick ≈ same boot image + ~50 GB `STICKLLM-DATA` for models/context.

## Encrypted vault: models + context (optional, increases risk)

People may want **chats / context** (and optionally model blobs) saved on the USB
or an internal SSD, encrypted at rest.

| Mode | Default | Notes |
|---|---|---|
| Ephemeral (RAM only) | **On** | Safest; reboot clears chats |
| USB `STICKLLM-DATA` models | Off until first-boot claim | Needed for download SKU |
| Encrypted **context vault** (USB or user-chosen SSD file) | **Off** | Passphrase unlock each boot |
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
overlay/.../stickllm-usb-claim    # first-boot: probe USB, create STICKLLM-DATA
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
