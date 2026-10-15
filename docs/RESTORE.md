# Restore policy (N-2)

Keep the **last two recoverable product ships** plus the immutable Drive golden.
Be honest about what a stranger can download vs what only maintainers have locally.

## Public artifacts

| Slot | Tag | What strangers can get | Checksum |
|------|-----|------------------------|----------|
| **N** (current) | `v0.3.8` | Google Drive ISO + [GitHub Release](https://github.com/StickLLM/stickllm/releases/tag/v0.3.8) notes | `checksums/v0.3.8.sha256` → `88f78154…` |
| Golden | `v0.2.0` | [GitHub Release v0.2.0](https://github.com/StickLLM/stickllm/releases/tag/v0.2.0) (split `.7z` and/or Drive link in release notes) | `checksums/v0.2.sha256` → `4914087d…` |

Drive folder (ISOs over GitHub’s 2 GB limit):  
https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing  

**Public current ship on that folder: `StickLLM-v0.3.8.iso`.** Do not assume older filenames are still listed there.

**Do not flash `v0.3.5`** — truncated/broken. Prefer **v0.3.8** (or **v0.3.6** as N-1).

**Hash of record is on GitHub** (`checksums/v0.3.8.sha256` + Release notes). After Drive upload, verify the ISO against that digest — do not treat a hash only on Drive as authoritative.

## Maintainer / local-only

| Slot | Tag | Typical local path | Checksum in git |
|------|-----|--------------------|-----------------|
| **N-1** | `v0.3.6` | `out/v0.3.6/stickllm-amd-rtx3090-v0.3.6.hybrid.iso` | `checksums/v0.3.6.sha256` → `fb559d9f…` |
| N local copy | `v0.3.8` | `out/v0.3.8/StickLLM-v0.3.8.iso` | `checksums/v0.3.8.sha256` |
| Older local | `v0.3.0` | `out/v0.3.0/stickllm-amd-rtx3090-v0.3-apiready.hybrid.iso` | `checksums/v0.3.sha256` → `f3db9113…` |

The **v0.3.0** apiready ISO is **not** published on Drive or GitHub Releases. Tags + checksums stay in git for maintainers who still have the file.

Older tags (`v0.2.1-local-nvidia-kbd`, `v0.3.1`–`v0.3.4`, `v0.3.7`, …) and their `out/` dirs remain recoverable locally; they are outside the rolling N/N-1 window. Never delete them when cutting the next ship.

## ISO naming (future N)

- **Through v0.3.6:** historical filenames (`stickllm-amd-rtx3090-v….hybrid.iso`) — do not rename.
- **v0.3.7 and later:** exactly `StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/` (see [BUILD.md](BUILD.md)).

## Rules

- When cutting the next ship: keep **N** and **N-1** tags and local `out/` ISO dirs; do not delete or overwrite them.
- Drive / Release **v0.2.0** is outside the rolling window — never retag, rewrite checksum, or replace under the same name.
- Prior **v0.3.6** on Drive — never overwrite under the same name with a different digest.
- Current **v0.3.8** on Drive — never overwrite under the same name with a different digest.
- New ships get new tag names, new `out/<version>/` dirs, new `StickLLM-vX.Y.Z.iso` filenames, and new `checksums/<version>.sha256` files.

## Restore N (v0.3.8) — public

```text
git checkout v0.3.8
ISO:      Google Drive StickLLM-v0.3.8.iso
Checksum: checksums/v0.3.8.sha256
Expect:   88F781545762A986BB3A1DCE9183601B7BBE173D0D56A20CA03BEF7A533201CB
```

Flash with Rufus DD or `dd` — [FLASH.md](FLASH.md).

## Restore N-1 (v0.3.6) — public

```text
git checkout v0.3.6
ISO:      Google Drive stickllm-amd-rtx3090-v0.3.6.hybrid.iso
Checksum: checksums/v0.3.6.sha256
Expect:   FB559D9F0CC5182406F0851F09C1E28C302F911C01B46CAC545EF4D920E1A43D
```

## Restore golden v0.2.0

```text
git checkout v0.2.0
ISO:      GitHub Release assets and/or Drive (see release notes)
Checksum: checksums/v0.2.sha256
Expect:   4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48
```
