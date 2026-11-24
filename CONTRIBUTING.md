# Contributing

## End users

Download, verify, flash: [README.md](README.md) → [docs/FLASH.md](docs/FLASH.md) → [docs/BOOT.md](docs/BOOT.md).

## Build from source

Cold-start steps and disk/Docker requirements: [docs/BUILD.md](docs/BUILD.md).

## Maintainers

- Dev loop / SSH iterate / release bake: [docs/DEV-WORKFLOW.md](docs/DEV-WORKFLOW.md)
- Lab flash tools, ISO-READY gates, local restore paths: [docs/MAINTAINER.md](docs/MAINTAINER.md)
- N / N-1 restore policy: [docs/RESTORE.md](docs/RESTORE.md) (current **N** = v0.8.8, **N-1** = v0.8.7)
- Next bake list: [docs/NEXT-0.8.9.md](docs/NEXT-0.8.9.md)

Do not overwrite shipping tags or published checksums. New work → new version /
`StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/`.
