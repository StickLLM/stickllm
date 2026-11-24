# Restore policy (N-2)

Keep the **last two recoverable product ships** plus the immutable Drive golden.
Be honest about what a stranger can download vs what only maintainers have locally.

## Public artifacts

| Slot | Tag | What strangers can get | Checksum |
|------|-----|------------------------|----------|
| **N** (current) | `v0.8.8` | Google Drive `StickLLM-v0.8.8.iso` / `out/v0.8.8/` | `checksums/v0.8.8.sha256` → `c5aa2305…` |
| **N-1** | `v0.8.7` | Google Drive `StickLLM-v0.8.7.iso` / `out/v0.8.7/` | `checksums/v0.8.7.sha256` → `5e554919…` |
| Older public | `v0.8.6` / `v0.8.5` / `v0.8.4` / … | Drive ISOs under their original names (optional retention) | matching `checksums/v0.*.sha256` |
| Golden | `v0.2.0` | [GitHub Release v0.2.0](https://github.com/StickLLM/stickllm/releases/tag/v0.2.0) (split `.7z` and/or Drive link in release notes) | `checksums/v0.2.sha256` → `4914087d…` |

Drive folder (ISOs over GitHub’s 2 GB limit):  
https://drive.google.com/drive/folders/1sTgvoyQi3aU-sauolWd35bKTLGynNEd-?usp=sharing  

**Public current ship on that folder: `StickLLM-v0.8.8.iso`.** Older filenames may still be listed — leave golden **v0.2** alone. Ships older than N-1 may leave the rolling window.

**Do not flash `v0.3.5`** — truncated/broken. Prefer **v0.8.8** (or **v0.8.7** as restore).

**Hash of record is on GitHub** (`checksums/v0.8.8.sha256`). After Drive upload, verify the ISO against that digest — do not treat a hash only on Drive as authoritative.

## Maintainer / local-only

| Slot | Tag | Typical local path | Checksum in git |
|------|-----|--------------------|-----------------|
| N local | `v0.8.8` | `out/v0.8.8/StickLLM-v0.8.8.iso` / `E:\stickllm-build\out\v0.8.8\` | `checksums/v0.8.8.sha256` |
| N-1 local | `v0.8.7` | `out/v0.8.7/StickLLM-v0.8.7.iso` | `checksums/v0.8.7.sha256` |
| Older local | `v0.8.6` / `v0.8.5` / … | `out/v0.8.x/` / `E:\stickllm-isos\` | matching `checksums/v0.*.sha256` |

Older tags and `out/` dirs remain recoverable locally when kept; they are outside the rolling N/N-1 window. Never delete golden **v0.2.0** when cutting the next ship. Local cleanup of slots older than N-1 is allowed after N advances.

## ISO naming (future N)

- **Through v0.3.6:** historical filenames (`stickllm-amd-rtx3090-v….hybrid.iso`) — do not rename.
- **v0.3.7 and later:** exactly `StickLLM-vX.Y.Z.iso` under `out/vX.Y.Z/` (see [BUILD.md](BUILD.md)).

## Rules

- When cutting the next ship: keep **N** and **N-1** tags and local `out/` ISO dirs; do not delete or overwrite them.
- Drive / Release **v0.2.0** is outside the rolling window — never retag, rewrite checksum, or replace under the same name.
- Current **v0.8.8** / prior **v0.8.7** on Drive — never overwrite under the same name with a different digest.
- Prior **v0.8.6** / **v0.8.5** / **v0.8.4** / … on Drive — do not overwrite under the same name with a different digest if still published.
- Ships older than N-1 may leave the rolling window — removable from Drive/local; do not reuse the name for different contents.
- New ships get new tag names, new `out/<version>/` dirs, new `StickLLM-vX.Y.Z.iso` filenames, and new `checksums/<version>.sha256` files.

## Restore N (v0.8.8) — public

```text
ISO:      Google Drive / local out/v0.8.8/StickLLM-v0.8.8.iso
Checksum: checksums/v0.8.8.sha256 → c5aa2305…
```

Flash with Rufus DD or `dd`, then **full readback** — [FLASH.md](FLASH.md).

## Restore N-1 (v0.8.7) — public

```text
ISO:      Google Drive StickLLM-v0.8.7.iso / out/v0.8.7/StickLLM-v0.8.7.iso
Checksum: checksums/v0.8.7.sha256 → 5e554919…
```

## Restore older public (v0.8.3)

```text
ISO:      out/v0.8.3/StickLLM-v0.8.3.iso (or Drive if published)
Checksum: checksums/v0.8.3.sha256 → 26ceba9f…
```

## Restore golden v0.2.0

```text
git checkout v0.2.0
ISO:      GitHub Release assets and/or Drive (see release notes)
Checksum: checksums/v0.2.sha256
Expect:   4914087D502D13327DBBD9196C9A4A7DF46EE079D423FF4B0BC6280E1C7B1A48
```
