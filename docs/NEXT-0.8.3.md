# Pending for v0.8.3

Post-**v0.8.2** punch list. Do not cut/flash until bake confirms these. Shipping tag/ISO must be a **new** name (`v0.8.3` / `StickLLM-v0.8.3.iso`) — never overwrite `v0.8.2`.

## Must bake (in tree / lab-hotfixed)

| Item | Status | Notes |
|------|--------|-------|
| **`find_mmproj` family-name match** | In tree on `release/v0.8.3`; lab-hotfixed | When several mmproj files share a models dir, match by family name (e.g. Qwen3VL-8B ↔ `mmproj-Qwen3VL-8B-…`). Do **not** pick largest leftover (e.g. VL-3B mmproj for Qwen3-VL-8B). Also adds Qwen3-VL mmproj fallback repos. Unit: `tests/test_v053.py::test_c_find_mmproj_prefers_matching_family`. |

## Already in v0.8.2 — confirm on next clean flash

| Item | Notes |
|------|-------|
| **CUDA / llama `.so.1` soname links** | Baked via `scripts/lib/docker-build-llama.sh` (`link_soname` for libllama/libggml/libmtmd). Listed in CHANGELOG 0.8.2 “Prior hotfixes in bake.” Re-check after a clean flash that CUDA llama-server loads without missing `.so.1`; not a new bake task unless verify fails. |

## Out of scope here

- StickLink Method C / Always-On WIP on this worktree (separate track; not a post-0.8.2 vision hotfix).
- ISO cut / flash — only when explicitly requested.
