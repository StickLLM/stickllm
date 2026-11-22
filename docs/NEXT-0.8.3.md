# Pending for v0.8.3

Post-**v0.8.2** punch list. Do not cut/flash until bake confirms these. Shipping tag/ISO must be a **new** name (`v0.8.3` / `StickLLM-v0.8.3.iso`) — never overwrite `v0.8.2`.

## Must bake (in tree / lab-hotfixed)

| Item | Status | Notes |
|------|--------|-------|
| **`find_mmproj` family-name match** | In tree on `release/v0.8.3`; lab-hotfixed | When several mmproj files share a models dir, match by family name (e.g. Qwen3VL-8B ↔ `mmproj-Qwen3VL-8B-…`). Do **not** pick largest leftover (e.g. VL-3B mmproj for Qwen3-VL-8B). Also adds Qwen3-VL mmproj fallback repos. Unit: `tests/test_v053.py::test_c_find_mmproj_prefers_matching_family`. |
| **Agent Zero `vision` follows active mmproj** | In tree; lab-hotfixed | `stickllm_agent` was hardcoding `chat_model_vision: false` / preset `vision: false`, so A0 never sent images even when StickLLM chat + llama-server multimodal worked. Now `_model_vision()` / `_mmproj_path()` drive `model_settings`, `preset_text`, and plugin `config.json` on sync. Unit: `tests/test_agent_zero.py` vision asserts. |

## Already in v0.8.2 — confirm on next clean flash

| Item | Notes |
|------|-------|
| **CUDA / llama `.so.1` soname links** | Baked via `scripts/lib/docker-build-llama.sh` (`link_soname` for libllama/libggml/libmtmd). Listed in CHANGELOG 0.8.2 “Prior hotfixes in bake.” Re-check after a clean flash that CUDA llama-server loads without missing `.so.1`; not a new bake task unless verify fails. |

## How to use vision (lab / user)

1. **Load a VL model with mmproj.** Models → pick Qwen2.5-VL-7B / Qwen3-VL-8B (or similar). If the **vision** pill is grey, tap it to download mmproj, then **Load**. Header chip should show `cuda · vision` (or backend · vision).
2. **Prefer StickLLM chat for images.** Paperclip / drag / paste into the message box (placeholder says “paste an image”). Send. The model must already be vision-loaded — text-only loads skip image bytes.
3. **Agent Zero.** After a VL model is loaded, `stickllm-agent sync-model` sets preset `vision: true` from the active mmproj. Attach/paste images in the Agent Zero window (not only StickLLM chat). If A0 was open with an old `vision: false` preset, sync (or reload the model) so settings refresh.
4. **Quick check.** Health `connect.vision` true + a 1×1 image `/api/chat` completion should answer a color word. Wrong mmproj pairing (e.g. VL-3B projector on Qwen3-VL-8B) is fixed by the `find_mmproj` family match above.

## Out of scope here

- StickLink Method C / Always-On WIP on this worktree (separate track; not a post-0.8.2 vision hotfix).
- ISO cut / flash — only when explicitly requested.
