# Pending for v0.8.7

Post-**v0.8.6** punch list. Shipping tag/ISO must be a **new** name
(`v0.8.7` / `StickLLM-v0.8.7.iso`) — never overwrite `v0.8.6`
(`17d096c0…`).

## Must bake

| # | Item | Status | Notes |
|---|------|--------|-------|
| **NI4** | NInfer downloads in Models Downloads queue (ISS-044) | In tree → bake | Merge `ninfer_download_progress` into `status.download` + `download_queue`; UI poll keeps NInfer catalog; toast points at Downloads. |
| **NI5** | NInfer Load wording + status parity (ISS-045) | In tree → bake | Use **Load** (not Activate). Card Running only when `:8080` healthy; write `model.env` + A0 `sync-model`; tray **Loading %** like GGUF (USB can take minutes); exp-engine unit drives busy state. |
| **NI6** | Engine UX parity with llama.cpp (ISS-046) | In tree → bake | Same Download / Load / Unload / tray / A0 follow for NInfer (Strata later). |
| **SL1** | StickLink QR flash “unavailable” while pairing | In tree → bake | Brief join-URL gap before `connected` showed “StickLink unavailable”; show **Pairing phone…** instead. |
| **CLK1** | Sync clock from internet when Wi‑Fi is up (ISS-047) | In tree → bake | Wrong RTC → TLS fail (“could not connect”). NTP kick on Wi‑Fi apply + NM up; timesyncd no longer waits on masked wait-online. |
| **PWR1** | Power off confirm hidden behind Browser (ISS-048) | In tree → bake | Minimise native Browser/Terminal first; use in-desk confirmBox instead of window.confirm. |
| **SU1** | Setup Open now → Loading… feedback (ISS-049) | In tree → bake | Button + status line while starter model activate runs. |
| **EX1** | Experimental settings survive reboot on same PC (ISS-050) | In tree → bake | DATA bind-mount + machine-id: same host keep NInfer/unlock; other host → defaults. |
| **DL1** | Warn-but-allow downloads under NInfer (ISS-051) | In tree → bake | No more hard `unknown NInfer model`; GGUF (Inkling) warns then queues; unlisted NInfer ids warn then try. |
| **SR1** | HF search / pills under NInfer must not show GGUF as NInfer (ISS-052) | In tree → bake | Engine-filtered catalog + search; trust filters same as GGUF path. |
| **ST1** | USB→RAM stage before Load / after Download (ISS-053) | In tree → bake (lab-hotfixed) | `stickllm_stage.py`: copy to `/tmp` or `/dev/shm` (not `/run`); status bar %; free on Unload/switch/low MemAvailable; never mlock. GGUF + NInfer. **Reuse complete staged file across mounts** (do not re-copy USB→`/tmp` when `/dev/shm` already has it). Gateway activate timeout **7200s** (was 180s — wiped Loading UI mid-copy). Status chip keeps **Copying from USB to RAM…** from `health.stage` even if activate returns/times out. |
| **CTX1** | NInfer hard 32K context floor (ISS-054) | In tree → bake | `ninfer-serve --max-context/--kv-capacity ≥32768`; A0 presets `ctx_length`/`context_length` 32768. Bare NInfer default 8192 caused LiteLLM `context_length_exceeded`. |
| **A01** | A0 model id match NInfer (ISS-055) | In tree → bake | Normalize `qwen36-27b` ↔ `qwen3.6-27b`; sync util/chat to `/v1/models` id (not leftover `stickllm`). |
| **A02** | A0 LiteLLM host.docker.internal broken on bridge (ISS-056) | In tree → bake | Patch providers → `172.30.0.1`; docker `--add-host host.docker.internal:host-gateway`. |
| **A03** | A0 vision from `/v1/models` modalities (ISS-057) | In tree → bake | Do not force vision=true for every NInfer; read modalities. |
| **TU1** | Same Models Context + Advanced for every engine that supports them (ISS-058) | In tree → bake (lab-hotfixed) | Show `#localTune` under NInfer. Context → `--max-context`/`--kv-capacity` via model.env + active-engine (≥32K). KV type greyed (llama-only). Chat sampling knobs still apply. A0 ctx follows live engine (≥32K). |
| **HF1** | NInfer HF search finds real `.ninfer` models, not only 3 pins (ISS-059) | In tree → bake (lab-hotfixed) | HF search `format=ninfer`; Download via shared queue (`.ninfer` allowed); keep 3 official pins; disk-discovered `.ninfer` listed; Load via find_ninfer_artifact. |
| **LD1** | Sticky Load under NInfer → experimental activate (ISS-060) | In tree → bake (lab-hotfixed) | Card Load + `#activate` under `ninfer-all` call `loadNinferModel` → `experimental_ninfer_model_activate`. Never llama `model_activate` for `.ninfer` / `hf:` ids (“unknown model”). |
| **SL2** | StickLink keepalive under load (ISS-061) | In tree → bake | Phone `sess lost: no pong path for 90s` under load. Ingest-path answers ping/pong immediately so heavy `http_req` cannot starve the phone watchdog. |
| **A04** | A0 syncStore `NO_HANDLERS` over link (ISS-062) | In tree → bake | Gateway rewrites served A0 sync/websocket JS: force `ws_webui` handlers, 20s handshake timeout, process pushes while DEGRADED. Not A0 fork. |
| **VI1** | Shrink oversized images before A0 vision (ISS-063) | In tree → bake | StickLLM attach-images extension downscales to JPEG ≤1280px before history inject; profile prompt: fail once, no OCR loop. |
| **AZF1** | A0 work files downloadable on phone (ISS-064) | In tree → bake | Mux: 32 MiB body, no gzip on Content-Disposition attachment / `download_work_dir_file`, 300s bridge timeout, `x-sticklink-download`. |

## Product rules

**Engine UX parity with llama.cpp.** Whatever engine is default on `:8080` (llama.cpp, NInfer, Strata), Models should feel the same: Download → queue, **Load** / **Unload**, tray Loading % → model name, A0 follows the loaded id. Internals differ (GGUF vs `.ninfer`, mmproj vs built-in vision); the words and status chrome do not.

**Hard 32K context floor** for StickLLM chat + A0 + experimental serve (unless a smaller model truly cannot fit — refuse, do not silently drop to 8K).

**Agreed fixes are recorded** in ISSUES + this file + CHANGELOG Unreleased in the same turn — see `.cursor/rules/record-agreed-fixes.mdc`.

## Notes

- Vision **mmproj chip** is llama.cpp GGUF-only. NInfer Qwen3.8 vision is built into the `.ninfer` artifact (`--vision`) — no separate download chip.
