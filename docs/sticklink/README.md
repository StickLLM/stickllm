# StickLink (commercial / closed source)

StickLink is Nink Inc.’s hosted rendezvous and remote-join service. It is **not open source** and is the paid connectivity layer for StickLLM.

- Server + protocol docs + USB Method C client sources: private **StickLLM/sticklink**
- Prior monorepo history: private **StickLLM/stickllm-archive**
- Architecture (resume, rate limits, repo split): private **ARCHITECTURE-METHODC-RESUME.md** (v0.7.6)

## Product rule (v0.7.6+)

After one QR scan, the phone stays paired until **Disconnect** (phone) or **Generate** (stick). Network drops and backgrounding trigger **auto-resume** via `GET /v1/resume` — not a new scan.

This public repo is the StickLLM USB product only. Method C ISOs are baked with private StickLink overlays; do not commit those sources to public `main`.
