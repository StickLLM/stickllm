# Companion apps (potential catalog)

**First-pass list. Not shipping. Subject to change.**

Optional companion apps for StickLLM — usable by a human in the browser/UI and by an
agent via each app’s API or tool layer. Install target: StickLLM USB **DATA** partition
and/or the encrypted SSD **vault** ([VAULT.md](VAULT.md)). Nothing here is baked into
the current ISO unless noted below.

**Chat voice** is part of the StickLLM UI, not a companion download: whisper.cpp
tiny.en for the mic, KittenTTS mini 0.8 for read-aloud. Pins live in
`overlay/usr/local/lib/stickllm-speech.pin`. Piper is not the on-stick voice.

This catalog is a planning surface for humans and agents, not a commitment to ship any
specific app.

---

## Core (starter apps)

| App | License | Role |
|---|---|---|
| **ONLYOFFICE Docs** | AGPL | Documents, spreadsheets, and slides. The bot can edit open files live. |
| **Paperless-ngx** | GPL | Scans and files receipts and documents, with text recognition and tagging, through a REST API. |
| **SnappyMail** | AGPL | Webmail over IMAP and SMTP, so the bot can triage and draft. Sending is the user’s click. |
| **Radicale** | GPL | Calendar and contacts (CalDAV and CardDAV), very light. |
| **Trilium Notes** | AGPL | Notes and a knowledge base with an API. |

## Productivity

| App | License | Role |
|---|---|---|
| **Vikunja** | AGPL | Tasks and projects. |
| **Actual Budget** | MIT | Budgeting and bank CSV import. |
| **Immich** | AGPL | Photos, with search that runs on your local GPU. |
| **SearXNG** | AGPL | Private web search for the agent, which can run over Tor. |

## Communications

| App | License | Role |
|---|---|---|
| **Matrix** (Conduit + Element) | Apache | Encrypted chat and calls, with bridges to other messengers. |
| **SimpleX Chat** | AGPL | Anonymous messaging with no IDs, with self-hosted relays. |
| **Jitsi Meet** | Apache | Browser video calls. |
| **OnionShare** | GPL | Anonymous file sharing and a drop box over Tor. |

## Publishing

| App | License | Role |
|---|---|---|
| **Postiz** | AGPL | Posts to many social networks at once, with an API. |
| **OpenTimestamps** + a signing tool | LGPL or MIT | Proof that a published file hasn’t been changed. |

## Creative and technical

| App | License | Role |
|---|---|---|
| **ComfyUI** | GPL | Image generation on the 3090. |
| **whisper.cpp** and **KittenTTS mini 0.8** | MIT and Apache-2.0 | Chat mic and read-aloud. Baked with the image (see `stickllm-speech.pin`), not a companion app. Not Piper. Not Kitten TTS 2. |
| **code-server** and **Jupyter** | MIT and BSD | Coding and data analysis. |
| **n8n** | fair-code (not OSI open source) | Automations. Prefer an OSI-friendly stack unless license posture is explicit. |
| **Node-RED** | Apache | OSI-friendly automation alternative under consideration instead of (or beside) n8n. |

## Agent

| App | License | Role |
|---|---|---|
| **Agent Zero** | MIT | The operator that drives the above through each app’s tool layer. |

---

## Requirements

Estimates until the next test boot. The card line is `Disk X GB · RAM X GB · GPU: none/optional/X GB`, with minimum RAM and the recommended figure in parentheses when it differs. Each estimate is labelled **approx.** Agent Zero’s disk and the starter-app footprint below are the figures already measured on the stick. Do not record a measurement for a catalog app that is not installed.

| id | disk_gb (app only) | ram_gb min/rec | vram_gb | gpu | note |
|---|---|---|---|---|---|
| onlyoffice | 3 | 2 / 4 | 0 | none | Heavy for an office suite; 4 GB RAM for smooth editing |
| paperless-ngx | 1.5 | 1 / 2 | 0 | none | + Redis; OCR spikes RAM/CPU; documents stored extra |
| snappymail | 0.1 | 0.1 / 0.25 | 0 | none | Very light |
| radicale | 0.05 | 0.05 / 0.1 | 0 | none | Very light |
| trilium | 0.5 | 0.25 / 0.5 | 0 | none | |
| vikunja | 0.15 | 0.1 / 0.25 | 0 | none | |
| actual | 0.3 | 0.15 / 0.3 | 0 | none | |
| immich | 5 | 6 / 8 | 0 or 1-2 | optional | Server + ML + Postgres + Redis; photo library stored extra; GPU ML search uses ~1-2 GB VRAM |
| searxng | 0.2 | 0.25 / 0.5 | 0 | none | + Valkey/Redis; Tor adds ~0.1 GB |
| matrix | 0.2 | 0.25 / 0.5 | 0 | none | Conduit + Element web; bridges add more |
| simplex | 0.1 | 0.1 / 0.25 | 0 | none | SMP/XFTP relay servers; clients are phone/desktop apps |
| jitsi | 2 | 2 / 4 | 0 | none | 4 containers incl. Java video bridge; CPU heavy with many callers |
| onionshare | 0.1 | 0.1 / 0.25 | 0 | none | CLI + Tor |
| postiz | 2.5 | 2 / 4 | 0 | none | Node + Postgres + Redis |
| opentimestamps | 0.05 | 0.05 / 0.05 | 0 | none | Client + minisign; negligible |
| comfyui | 8 | 8 / 16 | 8 / 12-24 | required | PyTorch+CUDA install; models extra (SDXL ~7 GB, Flux 12-24 GB); unload or shrink the LLM to free VRAM |
| code-server-jupyter | 1.5 | 1 / 2 | 0 | optional | GPU only if notebooks use it |
| n8n | 0.5 | 0.5 / 1 | 0 | none | Pick n8n or Node-RED, not both by default |
| node-red | 0.3 | 0.2 / 0.5 | 0 | none | |
| agent-zero | 4 (measured) | 2 / 4 | 0 | none | Uses llama-server for the model; Kokoro TTS on CPU ~0.5-1 GB RAM; needs a few GB free while unpacking |

Base StickLLM with starter apps: ~25 MB extra, <3 GB RAM with a model loaded (measured on the stick).

After the next test boot, replace these estimates with measured disk (`du` of the app directory) and RAM (`docker stats` or RSS at idle and under use). Leave a figure labelled approx. until that measurement exists. Catalog apps that are not installed stay approx.

Before install, StickLLM checks free host-SSD space and total RAM. Below the minimum it shows a warning and still allows install. GPU required or optional cards show current free VRAM from `nvidia-smi` beside the requirement. If `nvidia-smi` is missing, the card says VRAM is unavailable.

## Notes

- Apps would be **downloadable** to USB DATA or vault — not required for StickLLM chat.
- Prefer projects with a clear local/API surface so a human UI and an agent can share the same backend.
- License column is for awareness when evaluating ship/bake decisions; third-party terms stay with each upstream project.
- Tracking: [ISSUES.md](../ISSUES.md) **ISS-022**. Roadmap checkboxes: [FEATURES.md](../FEATURES.md).
