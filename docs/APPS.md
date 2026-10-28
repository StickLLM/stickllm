# Companion apps (potential catalog)

**First-pass list. Not shipping. Subject to change.**

Optional companion apps for StickLLM — usable by a human in the browser/UI and by an
agent via each app’s API or tool layer. Installs go to a durable disk, not the live
overlay. `persistent_install_root()` in `overlay/usr/local/lib/stickllm_apps.py` chooses,
in order, the host SSD apps folder beside the models directory, the USB DATA partition
(`/mnt/stickllm-data/apps`, record `/mnt/stickllm-data/apps-installed.json`), then the
unlocked vault (`/var/lib/stickllm/vault/apps`). `/var/lib/stickllm/apps` is RAM on the
live OS and is not used. Nothing here is baked into the current ISO unless noted below.

**Chat voice** is part of the StickLLM UI, not a companion download: whisper.cpp
tiny.en for the mic, KittenTTS mini 0.8 for read-aloud. Pins live in
`overlay/usr/local/lib/stickllm-speech.pin`. Piper is not the on-stick voice.

This catalog is a planning surface for humans and agents, not a commitment to ship any
specific app.

## Installable from the Apps page (0.5.0)

ONLYOFFICE Docs (0.4) plus five starter add-ons have a working **Install / Open / Remove**
on the Apps page. Each needs the vault unlocked and the host drive used for Agent Zero
(the image is stored there, pulled by digest). Pins: `overlay/usr/local/share/stickllm/addons/<id>.pin`.

- Radicale 3.9.0 (`tomsquest/docker-radicale`), port 5451. Calendar and contacts web UI.
- Vikunja 2.7.1 (`vikunja/vikunja`), port 5452. Tasks; create the first account in the app.
- Actual Budget 26.10.0 (`actualbudget/actual-server`), port 5453. Set a server password on first open.
- Trilium Notes v0.106.1 (`triliumnext/trilium`), port 5454. Set a password on first open.
- Node-RED 5.0.9 (`nodered/node-red`), port 5455. See the risk note below.

The same rules hold for all five (`overlay/usr/local/lib/stickllm_addons.py`, `stickllm-addon`):

- Data lives only in `vault/addons/<id>`. A locked vault means the app is stopped and its
  data is unreadable; locking stops the apps after Docs and before Agent Zero.
- Container: non-root, `--read-only` with small tmpfs, `--cap-drop ALL`, `no-new-privileges`,
  `--log-driver none`, no GPU, no docker socket. Not started at boot (units are not enabled);
  installed apps start when the vault unlocks.
- Network: the app listens on `127.0.0.1` only. Its bridge drops every packet the container
  starts (no internet, no LAN, no host, no other app). A LAN browser reaches it only through
  the gateway on the app's own TLS port, after pairing; **Open** mints a one-time 60 s link
  that sets an HttpOnly cookie for that app only. StickLLM cookies are never forwarded to apps.
- Each app has its own origin (own port), so its pages cannot read StickLLM or another app.
  The browser shows the self-signed certificate warning once per port.
- Open goes to a named tab (`stickllm-<id>`), never a pop-up window.
- Remove deletes the image and keeps `vault/addons/<id>`; delete that folder yourself to erase the data.

Checked on the desktop's Docker (2026-10-27) with the exact flags above (read-only, non-root,
cap-drop ALL, `--log-driver none`, tmpfs, vault binds): all five images pulled by their pinned
digests and answered HTTP 200 on their local port, writing only under `vault/addons/<id>`.
Not yet checked on a stick (ext4 ownership, nft bridge rules, gateway TLS ports).

**Node-RED risk.** Node-RED flows are programs: function and exec nodes run arbitrary code
inside the container, and `http in` nodes serve pages on the Node-RED origin. StickLLM
limits that to the container: no network at all, read-only image, non-root, palette and
npm installs disabled (`node-red-settings.js`), no editor login of its own (the gateway
pairing is the login). Do not import flows you have not read.

**Radicale.** 0.5.0 serves the web UI through the paired gateway. Phone or desktop
CalDAV/CardDAV sync is not offered: those clients cannot do the pairing handoff.

Skipped for now (fiddly): Paperless-ngx (needs Redis plus OCR workers), SnappyMail
(needs outbound IMAP/SMTP, which the no-network rule forbids), Immich, Matrix, Jitsi
and the rest need several containers, a GPU, or LAN/internet access.

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
| **Node-RED** | Apache | Flow-based automation. Flows can run code; no palette installs, no internet. |

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

- Apps install onto the host SSD apps folder, USB DATA (`/mnt/stickllm-data/apps`), or the unlocked vault. Not `/var/lib/stickllm/apps`.
- Prefer projects with a clear local/API surface so a human UI and an agent can share the same backend.
- License column is for awareness when evaluating ship/bake decisions; third-party terms stay with each upstream project.
- Tracking: [ISSUES.md](../ISSUES.md) **ISS-022**. Roadmap checkboxes: [FEATURES.md](../FEATURES.md).

## 0.5.2 behaviour

- **Agent Zero tools:** `install_app` sends a confirm dialog to the screen that is driving the agent (kiosk or a paired LAN browser). Nothing installs until someone clicks Install. `create_spreadsheet` / `open_document` save to and open from `vault/Documents` in ONLYOFFICE; bad paths return `bad_path` and missing files `not_found`. The bridge answers HTTP 409 for every error and the message says why. A loop guard stops after 2 tries.
- **Agent needs USB settings:** Agent Zero starts only when the USB settings partition is mounted. A stick written with no free space (raw ISO size) has no settings partition and no agent.
- **Download policy:** while the vault is unlocked, Chromium downloads go to `vault/Downloads`. When it's locked, downloads are blocked (`DownloadRestrictions=3`). The kiosk applies the policy at start.
- **Context menu:** StickLLM pages have their own right-click menu (cut/copy/paste/select all/link/reload; Shift+right-click gives the native menu). Other pages keep Chromium's native menu.
- **Container DNS:** the Agent Zero container uses the host's resolvers plus 1.1.1.1/9.9.9.9 as fallback. nftables allows port 53 only to those; LAN and the stick's own IP stay blocked from the container.
- **Add-on handoff on LAN:** add-ons open on their own gateway TLS port (5451-5455), so a LAN browser must be able to reach those ports.
