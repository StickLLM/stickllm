# Release cut checklist

Maintainer-only. Never overwrite a published tag, Drive ISO name, or checksum file with different contents. Rolling window: [RESTORE.md](RESTORE.md). Bake loop: [DEV-WORKFLOW.md](DEV-WORKFLOW.md) · [BUILD.md](BUILD.md).

Current **N** = **v0.8.8** · **N-1** = **v0.8.7** · next cut = **v0.8.9** ([NEXT-0.8.9.md](NEXT-0.8.9.md)).

## Before bake

- [ ] Must-bake rows in `docs/NEXT-<next>.md` are **In tree → bake** (or honestly deferred).
- [ ] `ISSUES.md` open items for this ship have Fix lines; no “agreed” fix only in chat.
- [ ] `CHANGELOG.md` `## Unreleased (→ vX.Y.Z)` lists those ISS ids.
- [ ] Worktree on local disk (not OneDrive). `main` (or release branch) contains the tree you will tag.
- [ ] Version string in tree (`stickllm.json` / About) matches the new `STICKLLM_VERSION`.

## Bake

```bash
./scripts/verify-host.sh
./scripts/download-model.sh
./scripts/build-llama-server.sh   # only if binaries missing / forced
STICKLLM_VERSION=X.Y.Z ./scripts/build.sh
# → out/vX.Y.Z/StickLLM-vX.Y.Z.iso (+ SHA256SUMS; integrity-checked in-build)
```

- [ ] ISO path is **new**: `out/vX.Y.Z/StickLLM-vX.Y.Z.iso` — never reuse an existing shipping name.
- [ ] Record SHA-256 into `checksums/vX.Y.Z.sha256` (new file).
- [ ] Spot-check size / integrity (do not flash truncated hybrids).

## Hardware gate

- [ ] Flash a lab stick (Rufus DD or maintainer safe-flash + **full readback**) — [FLASH.md](FLASH.md).
- [ ] Smoke: boot menu, kiosk, baked model or NInfer path, vault unlock, Agent Zero if in scope.
- [ ] Only after confirm: publish.

## Publish (immutable once done)

- [ ] `git tag vX.Y.Z` on the bake commit; push tag + `main`.
- [ ] GitHub Release for `vX.Y.Z` (notes; ISO stays on Drive — GitHub 2 GB limit).
- [ ] Upload Drive `StickLLM-vX.Y.Z.iso` under that **exact** name; verify Drive file against `checksums/vX.Y.Z.sha256`.
- [ ] Do **not** replace Drive `StickLLM-vN.iso` / `StickLLM-vN-1.iso` with a different digest.

## Docs / tracking after ship

- [ ] Mark `docs/NEXT-X.Y.Z.md` **SHIPPED** (ISO name + full checksum); point new work at `docs/NEXT-<X.Y.Z+1>.md`.
- [ ] Move shipped ISS ids to **Closed — shipped in vX.Y.Z ISO** in `ISSUES.md`.
- [ ] Move CHANGELOG Unreleased bullets under `## X.Y.Z`.
- [ ] Bump front-door stamps: README, FEATURES, FLASH, RESTORE, BOOT, docs/README, preserve-shipping / stickllm-context rules → **N** = new, **N-1** = previous N.
- [ ] Create empty `docs/NEXT-<next>.md` for the following bake.

## Rolling window

Keep recoverable **N** and **N-1** only. Older Drive/local ISOs may be removed after N advances; never reuse their names for different bits. See [RESTORE.md](RESTORE.md).

## Lab hotfix ≠ shipped

A fix copied onto one running stick is **not** in the named ISO until a new bake contains it. Say so in NEXT Truth table. Do not tell anyone a fix is “in this build” unless the flashed ISO checksum matches.
