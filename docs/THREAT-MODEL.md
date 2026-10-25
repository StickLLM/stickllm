# Threat model (v0.1)

StickLLM reduces **cloud** exposure. It does **not** make you anonymous,
source-protected, or safe against a determined state-level adversary, a
hostile hardware vendor, a compromised phone, or a **malicious model file**.
Read this before trusting it with sources, cases, or classified-adjacent work.

## What StickLLM is for

A bootable USB that turns a known desktop into a **local** LLM appliance.
Prompts are meant to stay on that machine and your LAN — not OpenAI/Google.

## Assets

| Asset | Sensitivity |
|---|---|
| Chat prompts / completions | High |
| Model weights on USB | **High for high-risk users** — weights are executable behavior, not just data |
| LAN UI / API (HTTP) | Medium — anyone on LAN can use it in v0.1 |
| Host internal disks | High — must not be written by default |
| USB stick image | Medium — only mutate on explicit persist/download |
| Pairing keys / future client crypto | High (not implemented yet) |

## Trust boundaries (what you are trusting)

1. **Host PC** — CPU, RAM, motherboard, BMC/IPMI, BIOS/UEFI, disks.
2. **GPU + its firmware** — NVIDIA (or later AMD/Intel) silicon and VBIOS/GSP.
3. **USB image** — whatever you built/flashed from this repo (and your build PC).
4. **LAN** — every device that can reach the stick’s IP.
5. **Phone / browser** — OS, browser, keyboard apps, screenshots, backups.
6. **Optional Web lookup** — DuckDuckGo / fetched sites when Web is enabled.
7. **Model publisher / fine-tuner** — weights define behavior. Closed, opaque,
   or “abliterated” models are a **first-class** trust decision (see below).

---

## For journalists, NGOs, and government / high-risk users

StickLLM is a **tool to keep inference off Big-Tech clouds**. It is **not** a
complete protective security program. If you are protecting sources, witnesses,
investigations, or sensitive government material, assume the following.

### What this product does *not* give you

| Expectation | Reality |
|---|---|
| “Air-gapped anonymity” | Default chat is **plaintext on the LAN**. Hotel/cafe Wi‑Fi is hostile. |
| “Phone app = secure” | Stock iOS/Android (and browsers) can log, backup, or exfiltrate on-device text. GrapheneOS helps; it is not magic. |
| “Encrypted means the PC can’t see it” | The stick **must** see prompts to run the model. Encryption only helps *in transit* (future client). |
| “USB wipe = no evidence” | Ephemeral RAM helps. Seizure of a **running** machine, cameras, shoulder-surfing, BMC, or a phone backup can still burn you. |
| “Open-source USB = trustworthy model” | The **OS** and the **weights** are separate. A clean StickLLM image can still run a **hostile or backdoored GGUF**. |
| “Uncensored/abliterated = more private” | Often the opposite for trust: mystery fine-tunes are easy places to hide instructions or triggers (see **Models**). |
| “Local = legally safe” | Local hosting does not create privilege, shield subpoenas, or replace counsel / org security policy. |

### Operational limitations (treat as requirements)

1. Use a **dedicated** machine when possible; know firmware boot order (USB vs host OS).  
2. Prefer a **dedicated** LAN or direct link; never expose `:80`/`:8080` to the internet.  
3. Turn **Web** lookup **off** unless you accept outbound queries.  
4. Treat **Term/SSH** mode as admin access with a published default password in v0.1.  
5. Verify **model hashes** yourself; do not casually “download a hotter uncensored merge.”  
6. Plan for **physical** seizure and travel borders — ephemeral helps, it does not erase physics.  
7. Separate **source identity** from the chat channel (tradecraft ≠ software feature).  

### Threat actors this does *not* fully address

- Nation-state implant on GPU/CPU/BMC firmware  
- Compelled vendor assistance (cloud *or* silicon)  
- Coercion / physical access to you or the device  
- Supply-chain substitution of ISO or GGUF  
- Your own endpoint (phone notifications, cloud photos of the screen, etc.)  

If your bar is “resistant to a well-funded adversary,” StickLLM is at best **one
component** next to device hardening, procedures, and legal advice — not the
whole answer.

---

## Models: closed weights, merges, and abliteration

The model is part of your TCB (trusted computing base). StickLLM running
“locally” does **not** make arbitrary weights safe.

### Closed-weight / opaque models

| Issue | Why it matters |
|---|---|
| **No audit of training or alignment** | You cannot inspect how the model was taught to handle secrets, jailbreaks, or “phone home” style behaviors in the weight matrix. |
| **License / redistribution traps** | Some weights forbid the exact use you need; compliance is on you. |
| **Silent updates** | If you pull “latest” from a host you don’t control, behavior can change under you. |
| **Vendor alignment ≠ your ethics** | Refusal/safety stacks may log patterns in cloud products; locally, closed stacks still hide *why* the model acts. |

Prefer models with **public weights**, **documented lineage**, and **pinned
hashes** baked into your image. StickLLM’s default Qwen GGUF is still a
**third-party** artifact — verify it; don’t assume “shipped on the stick” equals
“reviewed.”

### Abliterated / “uncensored” / mystery fine-tunes

“Abliteration” and similar techniques strip refusal behavior. That can be
legitimate for research — and it is also an **easy back door** for a malicious
publisher:

| Risk | Reality |
|---|---|
| **Hidden system-style behavior** | Fine-tunes can embed sticky instructions (“exfiltrate,” “weaken advice,” “bias outputs”) that look like normal chat. |
| **Trigger phrases** | Rare tokens/phrases can unlock dormant behavior; hard to detect without eval harnesses. |
| **Distribution channel** | Random Hugging Face merges, torrents, and “uncensored 3090 God Mode” posts are high-risk supply chain. |
| **False sense of security** | Users pick abliterated models for “no censorship” and skip hash/provenance checks — ideal for a trojaned GGUF. |
| **Evaluation gap** | Standard chat tests won’t show a back door aimed at journalists or specific topics. |

**Guidance:** For high-risk work, only run weights your organization has
**provenance + hash pinning + basic eval** for. Treat unknown abliterated merges
like running an untrusted binary with your secrets as stdin.

### Model-level residual risk (even with “good” weights)

- Hallucination presented as fact (editorial risk, not just IT risk)  
- Prompt injection via pasted documents or Web-fetched pages  
- Memorization / regurgitation of training data  
- Bias and targeted manipulation in answers  

---

## Risks we do **not** fully cover (please read)

### Pairing (v0.2+)

LAN clients enter a **6-digit code shown only on the stick screen**. A session
token unlocks chat + Models control (USB claim / download). The code is
one-time; reboot clears pair state.

This stops casual LAN strangers from using the stick **after** you pair from a
trusted browser. It does **not** stop a sniffer who sees the HTTP token after
pairing, or someone who can read the stick screen. TLS for the tunnel is next.

### Network & browser (v0.1 today)

| Risk | Reality |
|---|---|
| **Plaintext HTTP** | Chat UI and API are **not TLS**. Same-LAN sniffing (evil Wi‑Fi, compromised router, mirrored port) can read prompts. |
| **No authentication** | Anyone who can open `http://<stick-ip>/` can chat and hit `:8080`. |
| **WAN exposure** | If you port-forward or put the stick on the public internet, treat it as world-readable/world-usable. **Don’t.** |
| **Browser leftovers** | Phone/PC browser history, cache, OS backups, and screenshots are outside StickLLM. |
| **Web toggle** | With **Web** on, queries/snippets leave the stick to search/fetch. That path is intentional and visible — turn Web off for air‑gapped **chat answers**. **Web off is not OS offline:** Terminal, model downloads, and other processes can still use the NIC. True “nothing in, nothing out” lockdown is planned as **ISS-023** (not implemented). |
| **OS offline / NINO (planned)** | Settings Offline / air-gap mode should firewall or disconnect the network so nothing enters or leaves except, on a remote **client stick**, the allowlisted secure tunnel to the paired server. Until ISS-023 ships, do not treat the stick as air-gapped merely because Web is off. |

### Physical & host

| Risk | Reality |
|---|---|
| **Physical access** | Keyboard, cold-boot/RAM scrape, DMA (Thunderbolt), evil maid on the USB, or booting another OS can expose a live session. |
| **Internal disks** | Default is not to use them for chat; a malicious/buggy image or user action could still mount them. You must trust the image. |
| **BMC / IPMI / remote management** | Server boards (e.g. ROMED8) often have a BMC with its own OS/network. That can out-of-band the machine independent of StickLLM. |
| **Host firmware (BIOS/UEFI)** | Unsigned or vendor-controlled firmware can persist malware below the live USB. |
| **“USB always boots”** | Firmware boot order is yours to set. Wrong order → you land in the host OS and think you’re in StickLLM. |

### GPU & vendor (NVIDIA today)

| Risk | Reality |
|---|---|
| **Proprietary CUDA / driver userspace** | Closed blobs; large attack surface; you cannot fully audit them. |
| **GPU firmware / GSP** | Runs on the card; opaque; a hostile vendor update or bad flash can brick or alter behavior. StickLLM cannot “sandbox away” firmware. |
| **Vendor dependence** | Driver/CUDA breaks, regional restrictions, or ecosystem kill-switches are business/supply-chain risks — not fixed by HTTPS on the LAN. |
| **Open kernel modules ≠ open stack** | NVIDIA open GPU kernel modules still use proprietary CUDA for fast inference. |
| **Speed vs openness** | Vulkan/CPU paths are more open-ish but usually **slower** on NVIDIA; ROCm is for AMD, not a drop-in 3090 replacement. |

### Supply chain & build

| Risk | Reality |
|---|---|
| **Compromised build PC** | Can inject malware into the ISO you flash. |
| **Compromised GitHub / CI / downloads** | Cloned repos, release assets, or `apt`/model mirrors could be swapped. Verify what you can (checksums, reproducible builds — partial today). |
| **Debian / NVIDIA packages** | Upstream compromise becomes your stick’s compromise. |
| **Model files (GGUF)** | Wrong or malicious weights → bad or hostile model behavior. Prefer known hashes; treat “download model” as a trust event. |
| **Flash tooling on Windows** | Admin raw-disk writers can wipe the wrong disk if mis-aimed. |

### Multi-tenant & ops

| Risk | Reality |
|---|---|
| **Shared LAN / office Wi‑Fi** | Not a personal trusted LAN. Assume others can hit the API. |
| **Multi-user** | No roles, no audit log, no per-user crypto in v0.1. |
| **Logs** | Service journals may hold prompts/errors in RAM until reboot; debugging over SSH widens who sees them. |
| **SSH Term mode** | Password is a known ephemeral default (`user` / `stickllm`). Anyone on the LAN can try it when Term mode is on. Change posture before untrusted networks. |
| **Persistence features** | Explicit persist/download **writes** durable state — that outlives reboot by design; protect the stick physically. |

### USB data partition + encrypted vault (planned, opt-in)

First boot may claim **unallocated space on the StickLLM USB** (`STICKLLM-DATA`)
for durable models. Optional encrypted **context vault** (chats/exports) on a
user-chosen SSD file. Optional **wipe after N failed unlocks**
(e.g. 3) deletes the vault.

A separate ~256 MB **settings partition** on that same boot USB (not inside the
ISO) is encrypted with the SSD vault passcode. It holds per-computer vault
locations and portable secrets. It is not a second password, not the chat
store, and not where voice weights live (`/opt/stickllm/speech`). Claim must
target only the boot stick and must not shrink an existing DATA partition.
The plaintext location hint on `STICKLLM-DATA` still has no passcode.

| Risk | Reality |
|---|---|
| **Leaving ephemeral** | Durable chats/models on USB/SSD are seizable; default should stay RAM-only for chats. |
| **USB claim mistakes** | Must target **only the boot stick’s unallocated space** — never auto-partition internal disks. |
| **Encryption ≠ invisible** | At rest: helps against cold seizure. While unlocked, plaintext is in RAM for inference/UI. |
| **Hash on USB (models)** | Catalog digest is the trust anchor; SSD/USB blobs must match before load. |
| **Wipe-after-N (duress)** | Optional anti-coercion. Also: fat-finger wipe, travel stress, power flicker counting as fails, and **proof you destroyed evidence**. Not a legal strategy. **Default off**; confirm phrase required. |
| **Evil maid / dual-boot** | Host OS can delete/corrupt DATA or plant blobs (models rejected by hash; vault still DoS’d). |
| **High-risk default** | Journalists/gov: no vault, no SSD, no wipe-after-N unless they accept the trade. |

### Host SSD encrypted model cache (planned, opt-in)

| Risk | Reality |
|---|---|
| **Breaks “USB-only” purity** | Mounting/writing internal disks is a new trust boundary; must be user-approved. |
| **Encryption ≠ invisible** | At rest: helps against cold disk seizure. While StickLLM runs, models are decrypted for load. |
| **Hash on USB** | Expected digest is baked into the USB catalog. SSD blob is verified against that. Replacing only the SSD copy fails verification. Forging a matching hash means altering the USB image — at that point the whole stick TCB is already lost. |
| **Evil maid / dual-boot** | Host OS can delete/corrupt the cache (DoS) or plant a bad blob (rejected by USB hash). Passphrase UX still matters. |
| **High-risk default** | Journalists/gov: leave **off**; accept slower USB loads. |

### Future clients (not built yet)

| Risk | Reality |
|---|---|
| **Encrypted tunnel phone↔stick** | Stops LAN sniffers. Does **not** hide prompts from the stick (inference needs plaintext) or from a compromised phone OS. |
| **Stock iOS / Android** | Vendor OS, app stores, IME, cloud backup, notifications can observe on-device text. |
| **GrapheneOS** | Stronger phone-side story; still not a proof against a rooted device or human factors. |
| **Apple / Google accounts** | Pairing UX that depends on Big-Tech identity reintroduces parties you’re trying to avoid. |

### What local LLM never fixes

| Risk | Reality |
|---|---|
| **The inference machine sees prompts** | By definition. “Encrypted to the server” still means the stick decrypts to run the model. |
| **Model hallucinations / data leakage in outputs** | Safety/policy of the model ≠ security of the channel. |
| **Side channels** | Power, RF, timing, acoustic — out of scope for a USB appliance. |
| **Legal / compelled access** | Local storage or a seized stick/phone is still seizable. Ephemeral helps; it is not immunity. |

---

## Default posture: ephemeral

- Live root and session state live in RAM overlays.
- Reboot → chats, runtime config, and temp files on the stick are gone.
- StickLLM does **not** use internal disks for chat storage by default.
- USB is written only on explicit **Persist** / **Download model** (with confirmation).

## What v0.1 *does* claim

- No cloud inference API in the default path.
- No intentional telemetry from StickLLM itself.
- LAN-only HTTP service bindings (still trust the LAN).
- Ephemeral session unless you opt into persistence.
- Optional Web lookup is user-visible and can be turned off.

## Outbound anonymity: Tor (not a commercial VPN)

**Decision:** StickLLM will use **Tor** for optional anonymity / onion access — **not**
Mullvad or other commercial VPNs as a bundled default.

A VPN moves all egress trust to one company and jurisdiction. Tor spreads trust across
relays (with well-documented limits: ISP can see Tor use, exits see cleartext HTTP,
global adversaries may correlate). That matches Tails’ stance: Tor is the strongest
common tool, not magic — and they note VPNs are weaker than Tor’s three-relay design
for anonymity. See [Tails: Limitations of the Tor network](https://tails.net/doc/about/warnings/tor/).

Users may run their own VPN outside StickLLM; we do not make that the product story.

## Out of scope (not implemented)

- Tor / onion remote access (planned direction; not in v0.2)  
- Bundled commercial VPN (rejected as default)  
- Mesh networking  
- Paired mobile client + encrypted tunnel  
- OS-level NINO / air-gap firewall (ISS-023; Offline switch not wired)  
- GrapheneOS client  
- Auto-update of OS / drivers / models  
- Mutual TLS, API keys, or multi-user auth  
- Secure Boot with signed NVIDIA modules  
- Non-NVIDIA production profiles (AMD ROCm, Vulkan-first, etc.)  
- Protection against a malicious LAN peer  
- Multi-tier model download menu + Qwen3.8-27B vision default  
- Encrypted host-SSD model cache  

## Residual risks (short list)

1. Physical access to a booted stick machine.  
2. Hostile or messy LAN + plaintext HTTP.  
3. NVIDIA software **and** firmware trust.  
4. Build/flash supply chain.  
5. Phone/browser endpoint security.  
6. Optional Web lookups leaving the stick.  
7. BMC/host firmware on server-class boards.  
8. **Untrusted / closed / abliterated model weights** (behavioral back doors).  
9. Tradecraft and legal exposure outside the software.  
10. Opt-in **host SSD model cache** (disk mount + key management).  

## Client crypto note (future)

A tunnel stops Wi‑Fi/LAN observers. It does not stop a compromised phone OS, and
the stick must decrypt prompts to run the model.

## Related

- Product stubs: [README — Future work](../README.md#future-work-stubs-only-in-v01)
- Boot / USB firmware order: [BOOT.md](BOOT.md)
- Model tiers / SSD cache: [MODELS.md](MODELS.md)
