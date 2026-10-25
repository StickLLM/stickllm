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

## Notes

- Apps would be **downloadable** to USB DATA or vault — not required for StickLLM chat.
- Prefer projects with a clear local/API surface so a human UI and an agent can share the same backend.
- License column is for awareness when evaluating ship/bake decisions; third-party terms stay with each upstream project.
- Tracking: [ISSUES.md](../ISSUES.md) **ISS-022**. Roadmap checkboxes: [FEATURES.md](../FEATURES.md).
