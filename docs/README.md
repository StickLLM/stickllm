# StickLLM docs

**Current ship:** **v0.8.8** (`StickLLM-v0.8.8.iso`, [`checksums/v0.8.8.sha256`](../checksums/v0.8.8.sha256) → `c5aa2305…`)  
**N-1 restore:** **v0.8.7** · **Next bake:** [NEXT-0.8.9.md](NEXT-0.8.9.md)  
Front door: [README.md](../README.md) · Features: [FEATURES.md](../FEATURES.md) · Changelog: [CHANGELOG.md](../CHANGELOG.md)

## Start here

| Doc | Use |
|-----|-----|
| [FLASH.md](FLASH.md) | Rufus DD / `dd` + full readback |
| [BOOT.md](BOOT.md) | Boot menu, Secure Boot off, SSH modes |
| [RESTORE.md](RESTORE.md) | N / N-1 rolling window |
| [HARDWARE.md](HARDWARE.md) | Minimum + tested GPUs |
| [VAULT.md](VAULT.md) | Passcode, settings partition, recovery |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common kiosk / A0 / pair issues |

## Build & maintain

| Doc | Use |
|-----|-----|
| [BUILD.md](BUILD.md) | Host tools → `STICKLLM_VERSION=… ./scripts/build.sh` |
| [DEV-WORKFLOW.md](DEV-WORKFLOW.md) | Hotfix loop, product vs A0 fork |
| [MAINTAINER.md](MAINTAINER.md) | Lab flash / integrity / not for end users |
| [MODELS.md](MODELS.md) | Baked vs catalog models |
| [DEBIAN13-EXPERIMENTAL.md](DEBIAN13-EXPERIMENTAL.md) | Experimental tab / NInfer / unlocks |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | PR / ship rules |

## Product areas

| Doc | Use |
|-----|-----|
| [APPS.md](APPS.md) | Apps page catalog + Agent Zero install path |
| [ARCHITECTURE-AGENTZERO.md](ARCHITECTURE-AGENTZERO.md) | Ports, Docker data-root, open_app |
| [sticklink/README.md](sticklink/README.md) | StickLink is closed-source / commercial |
| [WEB-MODE.md](WEB-MODE.md) | Internet / Tor / No internet |
| [CHATS.md](CHATS.md) | Chat persistence |
| [UI-PHONE.md](UI-PHONE.md) | Phone UI notes |
| [THREAT-MODEL.md](THREAT-MODEL.md) | Threat model (security work parked) |
| [VERIFIED.md](VERIFIED.md) | Hash-pinned add-on digests |

## Bake / issue tracking

| Doc | Use |
|-----|-----|
| [NEXT-0.8.9.md](NEXT-0.8.9.md) | Must-bake for next ISO (source of truth) |
| [ISSUES.md](../ISSUES.md) | Open ISS ids (074–076 for v0.8.9; 065–073 shipped in 0.8.8) |
| [NEXT-0.8.8.md](NEXT-0.8.8.md) … [NEXT-0.8.3.md](NEXT-0.8.3.md) | **SHIPPED** historical punch lists — do not treat as current |
| [HOTFIX-AFTER-STICK-SWAP.md](HOTFIX-AFTER-STICK-SWAP.md) | Historical live hotfix table (v0.8.2 era) |
| [BASELINE-v0.2.md](BASELINE-v0.2.md) | Retired early baseline (not a restore slot) |

## Historical / archive

| Doc | Use |
|-----|-----|
| [CURSOR-HISTORY-agentzero.md](CURSOR-HISTORY-agentzero.md) | What was already built on the A0 fork line |
| [PLUGIN-REVIEWS.md](PLUGIN-REVIEWS.md) | Old plugin allowlist notes |
| [legal/AGENT-ZERO-LOGO.md](legal/AGENT-ZERO-LOGO.md) | Logo attribution |
