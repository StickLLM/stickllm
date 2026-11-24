# NInfer / Models how-to (v0.8.8+)

Short path for chat on Experimental **NInfer** (or back on **llama.cpp**). Engine wiring details: [DEBIAN13-EXPERIMENTAL.md](DEBIAN13-EXPERIMENTAL.md). Catalog / baked GGUF: [MODELS.md](MODELS.md).

**Default after a clean flash** is still **llama.cpp** with baked **Qwen2.5-7B Q4_K_M**. NInfer is opt-in.

## Switch chat to NInfer

1. **Settings → Experimental → Engine downloads** — download **NInfer-all** if not Installed (Confirm).
2. On that row, **Set default** → Confirm. Chat / health / Agent Zero now use NInfer on `:8080`.
3. Open **Models**. Catalog filters to NInfer-compatible profiles (not GGUF).
4. Optional but recommended: paste a **Hugging Face token** in Models (saves to USB settings when unlocked) → **Test**. Needed for speed and gated repos.
5. **Download** a listed NInfer profile (e.g. Qwen3.6 27B). Prefer a stick with free space on `STICKLLM-DATA`.
6. Wait until Models shows the profile as installed / **Load** — not stuck on Download.
   - While a durable USB copy finishes you may see **Saving to USB**. That is not a second download.
   - Stop / Resume / Delete work on the Downloads queue for NInfer jobs.
7. Set **Context** (Advanced) if you want more than the default floor, then **Load**.
   - Load refuses when USB persist is still busy or host RAM cannot cover KV + headroom.
   - Very high context can still fail on **GPU VRAM** even when host RAM looks fine (3090 / 27B lab: ~96K OK, 128K often not). Prefer stepping down if Load fails after a VRAM spike.

NInfer does **not** use StickLLM GGUF weights. After Set default you must download/Load a `.ninfer` profile before chat works.

## Back to llama.cpp

**Settings → Experimental** → **Use llama.cpp** → Confirm. Then **Models** shows GGUF again; Activate a GGUF (baked or downloaded) as usual.

## StickLink / Agent Zero

Same `:8080` OpenAI-compatible port. After engine or model change, wait until health is good before expecting Agent Zero / phone chat to use the new weights.

## Common mistakes

| Symptom | Likely cause |
|---------|----------------|
| Set default done but chat empty / “no model” | No `.ninfer` downloaded/Loaded yet |
| “Downloading Qwen2.5…” while pulling NInfer | Fixed in v0.8.8; reflash if on older ISO |
| Load says not enough RAM at mid context | Wait for Saving to USB to finish; try lower context; ensure stage is not double-counted (v0.8.8 guard) |
| HF download slow or 401 | Add/Test HF token under Models; unlock vault/settings so it can persist |
| Dual USB, vault unlocked, Agent still dead | Settings/DATA layout — [USB-LAYOUT.md](USB-LAYOUT.md) |
