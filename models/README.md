# StickLLM model assets (build host)

These files are fetched by `scripts/build.sh` and baked into the ISO. They are
gitignored; do not commit GGUF weights.

## Baked default (0.6.7+)

| File | Role |
|------|------|
| `appagent/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf` | Base chat / app-agent model (part 1) |
| `appagent/qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf` | Base chat / app-agent model (part 2) |

Catalog id: `qwen25-7b-q4km` (`Qwen/Qwen2.5-7B-Instruct-GGUF`). Approx **4.4 GB**
on the stick. Prefer this over Q5_K_M on an **8 GB** GPU at the **32K** context floor.

Qwen3.5-4B is no longer baked; it remains an optional catalog download only
(not Open default). Larger VRAM tier recommends (12 / 16 / 24 / 32 / dual-24 GB)
are download-only pins in `config/models/catalog.toml` — see `docs/MODELS.md`.
