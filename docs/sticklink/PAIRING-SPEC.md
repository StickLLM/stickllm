# StickLLM / sticklink: Universal Device Pairing Specification

Status: **Proposed design, v0.9, for Nink's decisions and final sign-off by AI KVM and StickLLM** (2026-10-29). Design only. Nothing gets built, deployed or flashed until Nink approves.
Owner: Nink Inc. Private, no licence.
Purpose: implementation instructions for the StickLLM and AI KVM development work, and for the sticklink signalling server.

Change log:
- v0.1 (2026-10-29): Nink's draft. Four pairing methods: USB to USB, ESP32-P4 AI KVM over USB, mobile by QR, desktop by six-digit SPAKE2.
- v0.2 (2026-10-29): adds Nink's decisions from 10:43 AM ET:
  - Noise IKpsk2 only.
  - Routing ID kept separate from the secret.
  - One attempt per code, a 60 s expiry and rate limits.
  - X25519 identities.
  - Adds the SPAKE2 to Noise bootstrap correction, the KVM USB approach and lifecycle functions from day one. Replaces the QR-only draft in SIGNALLING-PLAN.md §3.
- v0.3 (2026-10-29): Nink's review, 11:23 AM ET.
  - Fixes the long-term PSK derivation, which used to use the non-secret handshake hash (§4.5).
  - KVM USB pairing now uses a six-digit check code on an independent display, with documented limits (§4.B).
  - A mailbox connection no longer uses up an invitation (§5).
  - A revoked or compromised key is cut off at once (§6).
  - All five open decisions are settled (§8).
- v0.4 (2026-10-29): applies StickLLM's review of v0.3 (8 required changes) and AI KVM's review (R1–R9).
  - SPAKE2 pinned to `SPAKE2-P256-SHA256-HKDF-HMAC` (RFC 9382) with exact identities, PIN encoding and confirmation data. ristretto255 and edwards25519 dropped. One shared code core proposed; library and audit are open decisions (§2, §4.D, §8b).
  - One `boot_psk` formula and one `pair_psk` formula for every method, with byte encodings (§4.5).
  - Routing IDs are assigned by the server and unique while live. Mailboxes, slots, join keys and pairing envelopes are defined (§4.6). The stale one-joiner rule is gone from §7.
  - The stick's registry and identity key move into the encrypted settings partition. A locked vault means sticklinkd answers nothing (§3).
  - New prerequisites section: combined key file + PIN unlock slot, and retirement of the legacy LAN pairing (§0).
  - §4.A is deferred, with the blockers listed (§4.A).
  - Approval is only a button on the stick's kiosk screen (§4).
  - Failed-attempt rules for QR and USB, and the accepted cancellation risk (§5).
  - KVM: commit-then-reveal check code (R1), exact handshake (R2), trigger and display hardware as an open decision (R3), vendor-defined HID collection (R4), where the code may be shown (R5), LAN wording and the no-second-device case (R6), staged security plan (R7), atomic records and rotation rules (R8).
  - Ed25519 rationale corrected (§2). Open hardware notes (§10) and optional additions (§11) added. New §8b lists open decisions for Nink.
- v0.5 (2026-10-29): applies StickLLM's re-review of v0.4 (N1, N2, HKDF conditions, X1–X5) and AI KVM's re-review (items 1–5 and notes).
  - Approval moves out of the kiosk browser into a native approval overlay owned by sticklinkd, which reads input devices directly. Defines how AI KVM input is recognised and ignored, including a pinned USB port (§4.7; StickLLM N1, AI KVM 4).
  - The stick's registry key is a random key kept on the stick, wrapped by the combined unlock secret. Minimum PIN strength, fixed Argon2id parameters and the accepted offline-guessing risk (§0 P1, §3; N2).
  - The conditions for plain HKDF in `pw → w` are written in (§4.D).
  - KVM: per-device USB serial `AIKVM-` + factory MAC (§4.B.4); exact HID framing (§4.B.3); exact inner messages and a strict state machine (§4.B.5); `extra` encoded once in `TH` (§4.5); authoritative KVM vectors in `vectors/` (§4.5); atomic rotation of the KVM's own key (§6).
  - QR pairing uses the full mailbox id instead of `RRRR` (§4.C, §4.6; X2). The QR `TH` no longer needs the phone's static key before the PSK is set (§4.5; X1). Narrow hidraw udev rule (§4.B.3; X3). "Possible interception" message (§5; X4). SIGNALLING-PLAN.md updated to the new key schedule (X5).
  - AI KVM notes added: NVS migration, cable flash for the new bootloader, pairing in "HID + gamepad added" mode, certificate fingerprint display, RTC findings, unverified items. AI KVM's views on §8b are added as advice; decisions in §8 and §8b are unchanged.
- v0.6 (2026-10-29): applies StickLLM's re-review of v0.5 (R1–R4 and notes) and AI KVM's re-review (required changes 1–3 and notes).
  - The approval overlay is a root-owned helper on its own virtual terminal. It draws with DRM/KMS and reads evdev, and is never a client of cage. Switching cleanly between the VTs is a required hardware test (§4.7; StickLLM R1).
  - The udev rule uses the `usb_id` builtin's values and no longer matches on VID. Access is for the sticklinkd group only (§4.B.3; StickLLM R2, AI KVM 2).
  - The recovery wrap is defined. It is derived only from the typed recovery phrase, with Argon2id. `recovery.sha256` is deleted. The phrase comes from a pinned format worth at least 128 bits (§0 P1, §3; StickLLM R3).
  - KVM detection no longer fails open in BIOS and gamepad modes. The `AIKVM-` serial is the main rule, on any port. XID mode has no strings and is an accepted risk. A device that appears after pairing starts can't approve, and a new XID-class or unknown HID device blocks approval while it's connected (§4.7, §8b (g) note; StickLLM R4, AI KVM 2).
  - HID framing is stop-and-wait in each direction, with an ack-only frame (0x02) and an unauthenticated ABORT frame (0x03). Reassembly is capped at 128 B. BUSY is dropped (§4.B.3; AI KVM 1).
  - Rotation of the KVM's own key falls back to the old key after a failed handshake under the new one, and a repeated `rekey` replaces the pending entry (§6; AI KVM 3).
  - AI KVM's other notes are applied in §4.B.3–§4.B.7 and §6: abort reason 0x07, timeouts, early 0x04, replacing the record on re-pair, the top-level collection, the device-level port path, the MAC exposure, the console retest, and `components/kvm_rtc`. StickLLM's notes are applied in §0 and §4.5: the 4-word passphrase as the default, and rejecting low-order keys.
  - Vectors: `kvm-usb-v1.json` is unchanged. Two new files, `kvm-usb-v1-extra.json` and `qr-v1.json` (§4.5).
- v0.7 (2026-10-29): applies the final items from StickLLM's and AI KVM's re-reviews of v0.6.
  - The settings recovery keyslot has pinned Argon2id costs. The phrase is fed from memory, the slot is read back and test-opened, and any failure stops setup (§0 P1; StickLLM Q1).
  - There is one **stick recovery phrase**, made once at first format, for the settings partition and the registry. Per-computer vault phrases stay separate and never touch the settings slot (§0 P1, §3; StickLLM Q2).
  - After aborting, the KVM serves its ABORT frame for a fixed 5 s and then closes. A host that sees `ack` fall back to 0xFF mid-attempt treats the attempt as ended (§4.B.3, §4.B.5; AI KVM 1).
  - Every rotating side must save its new key durably before sending `rekey`. The stick's own rotation steps are written out. A same-epoch `rekey` with a different key now replaces the pending entry (§6; AI KVM 2).
  - Notes applied: the overlay is a small native binary, and a new KVM port is pinned only after the KVM proves its key (§4.7). There is one device snapshot moment, T0, with a stable device identity, and reconnecting devices count as new (§4.7). The pairing trigger must not re-enumerate the KVM (§4.B.2). The `kvm_rtc` findings are in, and the KVM's overlap is counted only by its online-time counter (§6). Diverged peers that stay offline past the overlap must re-pair (§6). The udev glob is tightened to the exact serial length (§4.B.3).
  - Vectors: only the `out_of_sequence` note and a new `abort_lifetime` entry in `kvm-usb-v1-extra.json` change. No `rekey` vector exists, so the rotation change touches none.
- v0.8 (2026-10-29): applies StickLLM's review of v0.7 (R1–R3) and AI KVM's optional v0.7 nits.
  - The P1 Argon2id parameters are **4 passes**, 256 MiB (262144 KiB), 1 lane everywhere. cryptsetup 2.6.1 rejects 3 (minimum 4, `pbkdf_check.c` line 57). The exact `luksAddKey` command is pinned, fd 3 is a pipe and never a file, and the readback checks time cost 4 via `luksDump --dump-json-metadata`. StickLLM's findings are recorded: no trailing newline, both keys can't come from stdin, the silent memory cap below 512 MiB RAM (§0 P1; StickLLM R1).
  - Changing the stick recovery phrase now runs: add the slot, read it back and test-open it, replace the recovery wrap file, then remove the old slot. The old order could leave the old phrase opening the partition but not the registry (§0 P1; StickLLM R2).
  - `salt_rec` lives in the same file as its wrap. Every sealed file on the stick has a pinned byte format and pinned AEAD associated data. Writes use a 0600 `O_EXCL` temp file, fsync, rename and a directory fsync; the directory is 0700; writers hold a file lock (§3; StickLLM R3).
  - AI KVM's nits: the receive side of `rekey` (§6 rule (d)); the "ABORT lifetime" bullet split out (§4.B.3); the KVM serves its ABORT for 5 s whichever side aborted (§4.B.5); a KVM abort before any ack that the host misses ends only when the 60 s window closes (§4.B.3). Where a browser sign-in sets the KVM clock stays **unverified** (§4.B.7, §6).
  - Vectors: none depend on the Argon2id parameters or the stick's file formats, so none change. SIGNALLING-PLAN.md has no Argon2id iteration count, so it is unchanged.
- v0.9 (2026-10-29): applies StickLLM's review of v0.8 (R4–R6), using its text as written.
  - Both wrap files get a 1-byte `luks_slot` after the version byte (62 B and 78 B). The AEAD associated data is the label plus every header byte before the nonce. The LUKS slot map is pinned: combined secret A/B slots 0 and 1, stick recovery phrase A/B slots 2 and 3, no others. The lock file and temp files are named, and record writes and deletes fsync `records/`. 0x01, ChaCha20-Poly1305 and the 12-byte random nonce stay; the LUKS UUID is not added (§3; StickLLM R4).
  - The proposed crash-recovery step is replaced by StickLLM's procedure, which runs at every unlock under the exclusive lock (superseded by the v0.9 final procedure below). A PIN change uses the identical order and recovery, with slots 0 and 1 (§0 P1; StickLLM R5).
  - Flash rollback is an accepted risk. The defence for revocations is the server: on every unlock, before serving, the stick fetches its home's revoked-peer set and deletes matching local records; the server can remove records, never add them. The offline gap and the copied-stick gap are documented (§3, §6; StickLLM R6).
  - §7 updated. No vector depends on these changes.
- v0.9 final (2026-10-29 12:43 PM ET, this version): the §0 P1 crash recovery is replaced by the final five-step R5 procedure (find the slot S the entered secret opens, compare it with the wrap's slot byte W, and only then unwrap or kill the partner slot). The revoked-peer fetch uses the stick's authenticated session, acts only on peers already in its registry, and a failed fetch never blocks a local unlock (§3, §6, §7). StickLLM signed off v0.9 as final (§9). Step 3 then got a neutral message for a change interrupted before or after it was committed, and a valid-slot secret no longer counts as a failed attempt (StickLLM, 12:44 PM ET). No vector depends on these changes.

Architecture in one line: **one identity per device, one trusted-device registry, several pairing methods, one encrypted protocol.**

Review baselines. StickLLM reviewed `release/v0.5.3` @ d124b3b and `feature/encrypted-ssd-vault` @ 1a57a1f, because `release/v0.5.4` did not exist at review time. AI KVM reviewed `nink/aikvm`, branch `cursor/aikvm-rebrand-agent-api-a1c1` (aikvm 0.3.1). Stick-side facts in this spec come from that review and must be re-checked against v0.5.4 once it exists.

---

## 0. Prerequisites (before sticklink ships)

Owner: StickLLM. These aren't sticklink features, but sticklink depends on them.

**P1. One combined unlock slot for key file plus PIN.**

Today, per StickLLM's review:
- `vault.key` is stored in plaintext on the DATA partition. `stickllm-vault` adds it as its own keyslot.
- `stickllm-usb-settings` adds `vault.key`, and the contents of `recovery.sha256` (also plaintext on DATA), as separate keyslots.
- So whoever holds the stick can open the settings partition and the vault. No PIN is needed. "Stick key + PIN" is still unchecked in FEATURES.md.

Required before sticklink ships:
- Key file plus PIN become **one combined slot**. StickLLM's example is `HKDF(vault.key || Argon2id(PIN, salt))`. Call its output the **combined unlock secret**. StickLLM designs and reviews the exact construction.
- The standalone `vault.key` and `recovery.sha256` slots are removed.
- Recovery stays as a separate slot, keyed only from the recovery phrase **as the user types it** (below and §3). No file derived from the phrase is kept.

**PIN strength and Argon2id parameters (new in v0.5, StickLLM N2).** The LUKS header and `vault.key` are both on the stick. So a stolen stick allows **offline** PIN guessing, at the attacker's pace. Argon2id only slows that down. A 4–6 digit PIN (10^4–10^6 values) is brute-forceable at any practical Argon2id cost. So:
- **Minimum strength (proposal, StickLLM to confirm):** about 40 bits. In practice, one of:
  - **default (v0.6, StickLLM's note):** a generated passphrase of 4 words from a fixed word list (about 51 bits with a 7,776-word list). The setup screen offers this first;
  - a user-chosen passphrase of at least 8 characters, not all digits, checked against a common-password list. StickLLM notes that a human-chosen 8-character passphrase isn't really about 40 bits, so the UI recommends the generated one;
  - digits only: at least 12 digits.
  The PIN setup refuses anything weaker. A 4–6 digit PIN is not allowed.
- **Argon2id parameters are fixed** and stored in the slot format, so an attacker can't make the stick accept lower ones. Proposal: memory 256 MiB (262144 KiB), **4 passes**, 1 lane, 16-byte random salt, 32-byte output (v0.8: 4, not 3, because cryptsetup 2.6.1 rejects fewer than 4 Argon2id iterations, StickLLM R1). The same single parameter set is used for the combined-secret Argon2id, `recovery_secret` and every LUKS2 keyslot this spec adds. StickLLM measured adding a slot at about 1.4 s on the box (not the slowest PC). StickLLM measures the unlock time on the slowest supported PC and adjusts once, before release (target about 2 s or less; **unverified**). After release, raising them needs a re-wrap; lowering them is not allowed.
- **Accepted residual risk:** whoever steals the stick can guess offline for as long as they like. With the minimum above and these parameters, that takes a long time, but it is not impossible against a weak passphrase. This is accepted and goes into the user documentation. Revoking the stick's pairings from another admin device (§6) is the response to a lost stick.

**Recovery phrase (new in v0.6, StickLLM R3).** Today (`release/v0.5.3`, per StickLLM's review):
- `gen_recovery` (`stickllm-vault` lines 2024–2034) makes 12 words chosen with `SystemRandom` from `/usr/share/dict/words`, or, if that file is missing, `openssl rand -hex 24` (192 bits). No dictionary package is in `live-build/package-lists`, so the image probably uses the hex fallback. **Unverified on a built image.**
- `recovery.sha256` = SHA-256(phrase + "\n") is stored in plaintext in `$DATA_MNT/vault-meta` on the stick (line 2545), and `stickllm-usb-settings` (lines 231–237) uses its contents as a settings keyslot. So the stick alone opens that slot.

Required:
- **The phrase format is pinned, not taken from whatever `/usr/share/dict` contains.** Either 12 words from a pinned 2,048-word list shipped with StickLLM (132 bits), or the existing 48-hex-digit format (192 bits). At least 128 bits either way. StickLLM picks one and states it.
- **Normalisation:** lower case, words separated by single spaces, no leading or trailing space, no trailing newline.
- `recovery_secret = Argon2id(normalised phrase, salt_rec, the fixed P1 parameters above)`. `salt_rec` is 16 random bytes stored **in the same file** as the recovery wrap (§3, v0.8). HKDF would be enough at 128 bits or more; Argon2id keeps one code path.
- It is computed **only from a phrase the user types.** Nothing derived from the phrase is stored on the stick or on any SSD.
- `recovery.sha256` and the `.rec.key` temporary files are deleted. No keyslot or wrap is ever keyed from them again. The settings partition's recovery keyslot takes the typed, normalised phrase as its LUKS2 passphrase, so LUKS2's own Argon2id applies. StickLLM's v0.6 review confirms this is sound at 128 bits or more, provided nothing derived from the phrase is stored on the stick.
- Changing the phrase re-wraps `registry_key` (§3).
- Recovery opens the stick's full identity and registry. The user documentation says so.

**One stick recovery phrase (v0.7, StickLLM Q2).** Today (`release/v0.5.3`, per StickLLM): each per-computer SSD vault gets a new phrase from `gen_recovery` (`stickllm-vault` line 2492). Each new vault overwrites the single `recovery.sha256` in `vault-meta` on the stick. But the settings slot is added only once, at first format. So the phrase the user saw most recently may not open the settings partition or the registry. Rule:

| Phrase | Made | Opens | Never |
|---|---|---|---|
| **Stick recovery phrase** | **Once**, when the settings partition is first formatted. Shown once, to write down. | The settings partition's recovery keyslot, and `wrap_rec` for the registry (§3). It is the **only** phrase for these. | Opens an SSD vault. Is stored, in any form, on the stick or an SSD. |
| **Vault recovery phrase** (one per computer's SSD vault) | When that vault is created, as today. | That SSD vault only. | Touches the settings keyslot, `wrap_rec` or `vault-meta`. |

- The UI labels them clearly and differently: "Stick recovery phrase (opens this StickLLM stick)" and "Recovery phrase for the SSD vault on <computer name>". Both use the pinned format above.
- **Changing the stick phrase (order changed in v0.8, StickLLM R2):** the user types the old phrase, or unlocks with the PIN. The new phrase is generated and shown. Then, in this order, holding the §3 writer lock throughout:
  1. **Add** a new keyslot for it (below).
  2. **Read it back and test-open it:** `luksDump --dump-json-metadata` shows the P1 parameters for the new slot, and `cryptsetup open --test-passphrase --key-slot N --key-file=-` with the new phrase returns 0. Any failure removes the new slot and stops; nothing else has changed.
  3. **Replace the recovery wrap file** (§3: `luks_slot` = the new slot, new `salt_rec`, new nonce, `wrap_rec` from the new phrase) by one atomic replace, then verify it by unwrapping `registry_key` with the new phrase.
  4. Only then **remove the old keyslot** (`luksKillSlot`).
  - **Why this order:** in v0.7 the wrap was replaced at step 2, before the new slot was checked. A crash before the slot check left `wrap_rec` under the new phrase while the old phrase was still the one known to work, so the old phrase could open the partition but **not** the registry. A bad slot could also be found only after the wrap had been replaced.
  - **Claim:** at every point one phrase opens both the partition and the registry: the **old phrase until step 3, the new phrase from step 3**. Between steps 3 and 4 the old phrase still opens the partition but not the registry.
  - **A PIN change** uses the identical order and recovery, with A/B slots 0 and 1 and `regkey-pin.wrap` (v0.9, StickLLM R5).
  - **R5 crash recovery.** At every unlock, before serving, hold the writer lock and run these steps in order:
    1. Delete leftover `.<target>.tmp.<hex>` files.
    2. Find which LUKS slot S the entered secret opens (`open --test-passphrase --key-slot` for each slot in that method's pair). Read that method's wrap file and its slot byte W.
    3. If S != W, the entered secret opens a slot but isn't the one the registry is wrapped under. This happens when a PIN or phrase change was interrupted, either before or after it was committed. Change nothing and keep the registry locked. Tell the user: "A PIN or phrase change didn't finish. Unlock with the other one, your new or your previous." Then rerun from step 2 with the secret they enter. Don't count this as a failed attempt for rate limiting, since the secret was valid for a slot.
    4. If S == W, unwrap registry_key. If the wrap won't decrypt or W isn't an active slot, treat it as corruption: make no automatic change, and offer to re-create the wrap from the other unlock method.
    5. If the unwrap succeeds and the other slot in the same pair is also active, kill that slot using the secret in hand. Tell the user: "The last change didn't finish. Your current PIN or phrase still works." Otherwise do nothing.

    Every step is idempotent, and PIN changes follow the same procedure.
- **Why not one shared phrase for everything:** the user would have to be shown the same phrase again for each new vault, so it would have to be stored. And a phrase written down for one computer's SSD would then also open the stick and every pairing. Keeping them separate costs the user one extra phrase to keep.

**Adding a recovery or combined keyslot (v0.7, StickLLM Q1).** Today `add_existing_key_slots` (`stickllm-usb-settings` lines 224–239) runs once, at first format (line 282). It strips the newline from `recovery.sha256`, writes a temporary file and calls `luksAddKey --batch-mode` with **no PBKDF options** and `|| true`. So failures are ignored and the costs come from cryptsetup's benchmark. Required, for the recovery slot and for the combined P1 slot:
- **Pinned command (v0.8, StickLLM R1, tested on bookworm's cryptsetup 2.6.1).** `$EXISTING` is the secret of an existing slot `$OLD` (the current phrase, or the combined unlock secret), `$NEW` is the free target slot (the free partner of the pair in the §3 slot map, v0.9) and `$SECRET` is the new secret:
  ```
  printf '%s' "$EXISTING" | cryptsetup luksAddKey --batch-mode --key-file=- --key-slot "$OLD" --new-key-slot "$NEW" --new-keyfile=/dev/fd/3 --pbkdf argon2id --pbkdf-force-iterations 4 --pbkdf-memory 262144 --pbkdf-parallel 1 "$part" 3< <(printf '%s' "$SECRET")
  ```
  That is 4 iterations, 256 MiB (in KiB) and 1 thread, the P1 parameters.
  - **Fd 3 is a pipe, never a file.** It comes from bash process substitution. Don't use a here-string or here-doc, which bash may back with a temporary file. The libcryptsetup API, or `subprocess` with `pass_fds`, is preferred over a shell.
  - **No trailing newline.** With `-` and with a key file, cryptsetup reads byte-exact and doesn't stop at a newline. A phrase with a trailing `\n` fails to open a slot made without one (rc 2, tested). So the binary combined secret is safe here. Never use the interactive prompt for it.
  - **The two keys can't both come from stdin:** `--key-file=- --new-keyfile=-` fails with "Nothing to read on input." (rc 1). Hence the separate fd 3.
  - **Keep `--new-key-slot`.** Without it, `--key-slot` selects the *new* slot (backward compatibility, per the man page).
  - 3 iterations is refused: "Forced iteration count is too low for argon2id (minimum is 4)" (`lib/crypto_backend/pbkdf_check.c` line 57).
- Feed every secret **from memory** as above, or through the libcryptsetup API. **Never through a file.**
- **No `|| true`.** Any non-zero exit stops setup with an error. A wrong existing key gives rc 2 and an occupied target slot rc 1, so this catches both.
- **Read the slot back** with `cryptsetup luksDump --dump-json-metadata "$part"`. Refuse, remove the new slot and stop, unless `keyslots["$NEW"].kdf` is `{type: argon2id, time: 4, memory: 262144, cpus: 1}`. (The text `luksDump` shows `Time cost: 4`, `Memory: 262144`, `Threads: 1`; parse the JSON.) cryptsetup caps memory **silently** at half the physical RAM (`utils_pbkdf.c` lines 63–78 and 251–258), so it only bites on a host with less than 512 MiB of RAM, and threads at the number of online CPUs (lines 241–248). The readback catches both: such a PC fails setup rather than getting a weaker slot.
- **Test-open it:** `printf '%s' "$SECRET" | cryptsetup open --test-passphrase --key-slot "$NEW" --key-file=- "$part"` returns 0. (The same secret against another slot gives rc 2, tested.)
- **Rollback, and step 4 of a phrase change:** `printf '%s' "$SECRET" | cryptsetup luksKillSlot --key-file=- "$part" "$OLD"` at step 4, where `$SECRET` opens the slot that stays. For a rollback, kill `$NEW` instead, fed the secret of a slot that stays.
- **StickLLM to-dos (repo, not spec items):**
  - replace `add_existing_key_slots` as above;
  - delete `stickllm-vault` lines 2520–2525 and 2545–2546, and `stickllm-usb-settings` lines 231–238;
  - pin `gen_recovery`'s output format;
  - stop vault creation from writing `vault-meta/recovery.sha256`.

**StickLLM to-do (repo bug, not a spec item, from v0.6).** The vault's own recovery slot uses SHA-256(phrase) **without** the newline (`stickllm-vault` line 2521), while the settings slot uses `recovery.sha256`, **with** it. So the two "recovery" keys differ, despite the comment at `stickllm-usb-settings` line 231. Deleting `recovery.sha256` removes the settings side; the vault side should move to the same normalised, typed phrase.

Why: §3 puts the stick's identity key and registry behind the vault. That protects nothing while the stick alone unlocks it. See §8b (d).

**P2. Retire the legacy LAN pairing.**
- The existing `stickllm-pair` stores an unsalted SHA-256 of a 6-digit code. Anyone who reads that hash finds the code in at most 10^6 tries.
- sticklink replaces it. Retire `stickllm-pair` before sticklink ships.
- Until then, it must not create, read or change sticklink registry records, and it is not a sticklink pairing method. See §8b (f).

**P3. Re-check on the release branch.** Re-check every stick-side fact in §0, §3 and §4.A against `release/v0.5.4` when it exists.

## 1. Objective

Pair these with one mechanism underneath:
- StickLLM USB ↔ StickLLM USB (deferred, §4.A)
- StickLLM USB ↔ ESP32-P4 AI KVM
- StickLLM server ↔ mobile client
- StickLLM server ↔ desktop client (Windows, Linux, macOS)

Requirements:
- No manual entry of long keys.
- End-to-end encryption.
- A unique cryptographic identity per device.
- Pairing persists across reboots.
- No private key ever leaves the device that generated it.
- The rendezvous (signalling) server never learns application data, session keys or pairing secrets.
- Minimal user interaction.

## 2. Cryptography

| Purpose | Choice |
|---|---|
| Device identity | **X25519 static key pair**, generated on the device and never exported. The same key is the Noise static key. No separate Ed25519 identity (reason below). |
| Ongoing transport | **Noise_IKpsk2_25519_ChaChaPoly_SHA256**, unchanged from SIGNALLING-PLAN.md, over direct UDP and the DERP relay. **No TLS 1.3 between devices.** TLS stays only where it already is: device to the signalling server (WSS) and device to the DERP relay. Those are outer layers, and Noise runs inside them end to end. |
| KVM USB pairing (Method B) | **Noise_XX_25519_ChaChaPoly_SHA256** over a vendor-defined HID collection, with a commit-then-reveal check code (§4.B). |
| Short-code pairing (Method D) | **`SPAKE2-P256-SHA256-HKDF-HMAC`, RFC 9382**, with every parameter pinned in §4.D. No edwards25519, no ristretto255. |
| Derivation | HKDF-SHA256 (RFC 5869). Every label starts with `sl1/` and is used for one purpose only. Encodings in §4.5. |
| Server-side only | The Worker's allowlist signatures stay Ed25519. Only the Go sidecar verifies them, never the ESP32. |

**Why no Ed25519 identity (corrected in v0.4).** v0.3 said mbedTLS on the ESP32-P4 has no Ed25519. That is true of mbedTLS only. Ed25519 is available on ESP-IDF through `espressif/libsodium`. The device doesn't need Ed25519: allowlist signatures are checked by the sidecar, and OTA signing uses RSA. We choose X25519 alone so the KVM needs no extra crypto dependency. A future relay that accepts permits directly, or Tailscale Tailnet Lock, would need Ed25519 on the device. Whether that will ever be needed is unverified.

**Why P-256 for SPAKE2.**
- RFC 9382's Appendix B test vectors cover only `SPAKE2-P256-SHA256-HKDF-HMAC`.
- edwards25519 has RFC M and N constants but no official vectors. ristretto255 isn't an RFC 9382 suite at all. So v0.3's "edwards25519 (ristretto255 if the library offers it)" left interoperability to chance.
- Several SPAKE2 libraries (warner's Python `spake2`, RustCrypto `spake2`, BoringSSL's curve25519 SPAKE2) follow older drafts. They interoperate with each other, not with RFC 9382.
- P-256 is used only inside the SPAKE2 exchange. Device identities stay X25519.

**SPAKE2 library: OPEN DECISION, §8b (a).** StickLLM's survey (29 Oct 2026) found no SPAKE2 library on any platform that claims an independent audit, and no RFC 9382 package for Python. iOS CryptoKit has no PAKE API. Proposal, not settled:
- **One shared code core on every platform:** wrap the Rust crate `pakery-spake2` **0.6.2** (Apache-2.0). It implements RFC 9382 for P-256 and passes the Appendix B vectors. It is **unaudited** and young (repo created 2026-03, 2 stars). Its ristretto255 suite is the crate's own; we don't use it. Pin the exact version.
- Bindings: PyO3 for the stick, uniffi for iOS and Android, WASM for the PWA. The desktop app uses the crate directly or through one of these bindings, depending on its stack (not yet decided).
- Ship the RFC 9382 Appendix B vectors and our own `sl1` vectors (§4.5) in the repo, and run them on every platform.
- **Budget an external audit** of the core and our wrapper before release. Auditor and cost not chosen.
- CPace (`pakery-cpace`) is equally unaudited and still a draft, so it gives no advantage. Decision 4 (§8) stands.
- The KVM doesn't use SPAKE2. Leave it out of the firmware.

Other libraries: libsodium or monocypher on Linux, desktop and mobile. On ESP-IDF, the X25519 and ChaCha20-Poly1305 already in the firmware (`third_party/microlink`, and mbedTLS ChaChaPoly), with SHA-256 and HMAC from mbedTLS. HKDF on the KVM is a thin wrapper over mbedTLS HMAC, checked against the RFC 5869 vectors. Don't write any of our own primitives.

**Rule:** a public-key exchange is never trusted by itself. Each method below says what authenticates it.

## 3. Trusted-device registry

Every device keeps a local registry with one record per paired peer:

```
peer_id        16 B random, assigned at pairing
peer_static    32 B X25519 public key (the pin)
peer_class     stick | kvm | mobile | desktop
role           server | client
psk            32 B pair-specific Noise PSK (§4.5)
slot           8 B signalling slot id (§4.6)
display_name   user-chosen label, local only
paired_at, last_seen, key_epoch, status (active | revoked)
During a rotation only: {old, new} pin and psk, keyed by key_epoch (§6)
```

**Stick:**
- Location: `/mnt/stickllm-settings/sticklink/`, on the LUKS2 (Argon2id) settings partition labelled `STICKLLM-SETTINGS`. Files are mode 0600 and owned by the sticklinkd user.
- The stick's X25519 identity private key lives there too.
- **Registry key (changed in v0.5, StickLLM N2).** v0.4 derived the inner seal from the vault master. The vault is a LUKS blob on each computer's SSD (`stickllm-usb-settings` line 146, `computers/`), so that would tie the registry to one computer. Instead:
  - `registry_key` is **32 random bytes generated on the stick** at first setup, and kept on the stick in `/mnt/stickllm-settings/sticklink/`.
  - It is stored only **wrapped** (ChaCha20-Poly1305, random 12-byte nonce) under `wrap = HKDF(ikm = combined unlock secret, salt = empty, info = "sl1/registry-wrap")`, the P1 secret, in the file `regkey-pin.wrap` (format below).
  - **A second wrap for recovery (defined in v0.6, StickLLM R3):** `registry_key` wrapped (ChaCha20-Poly1305, random 12-byte nonce) under `wrap_rec = HKDF(ikm = recovery_secret, salt = empty, info = "sl1/registry-wrap-recovery")`, with `recovery_secret` from the **stick recovery phrase** (§0 P1; never a vault phrase). It has its own label, separate from the PIN wrap. **`salt_rec` is in the same file, `regkey-rec.wrap`, so one rename replaces both** (v0.8, StickLLM R3). Nothing else derived from the phrase is stored.
  - Records are sealed under `HKDF(registry_key, salt = empty, info = "sl1/registry")`, the identity key under `HKDF(registry_key, salt = empty, info = "sl1/identity")`.
  - A PIN change re-wraps `registry_key` under the PIN wrap; a recovery-phrase change re-wraps it under `wrap_rec`. Records are not re-sealed.
  - The registry works on any computer the stick is used with, because nothing comes from a computer's SSD.
- The live system boots with `boot=live` and no persistence, so the root is ephemeral. Nothing sticklink needs may live outside this partition.
- This storage only protects anything once prerequisite P1 is done (§0).
- **When the settings partition is locked (the combined secret hasn't been entered), sticklinkd has no identity and answers nothing.** No presence on signalling, no sessions, no pairing and no revocation from the stick. Peers see the stick as offline. An unattended mode that runs while locked would need a separately wrapped identity key and a documented threat trade-off. It isn't part of this spec.
- **File formats (pinned in v0.8, StickLLM R3; header and AD changed in v0.9, StickLLM R4).** Every sealed file is `version || [luks_slot] || [salt] || nonce || ct`, with ChaCha20-Poly1305, a fresh random 12-byte nonce on every write, and `ct` = ciphertext plus the 16-byte tag. `version` is one byte, 0x01. A reader refuses a file with any other version, or the wrong length, and never tries other keys or formats.

  | File | Layout (bytes) | Size | Key | AEAD associated data |
  |---|---|---|---|---|
  | `regkey-pin.wrap` | `01 || slot(1) || nonce(12) || ct(48)` | 62 B | `wrap` | `"sl1/registry-wrap" || 01 || slot` |
  | `regkey-rec.wrap` | `01 || slot(1) || salt_rec(16) || nonce(12) || ct(48)` | 78 B | `wrap_rec` | `"sl1/registry-wrap-recovery" || 01 || slot || salt_rec` |
  | `identity.sealed` | `0x01` (1) `||` nonce (12) `||` ct | 13 B + plaintext + 16 | `HKDF(registry_key, salt = empty, info = "sl1/identity")` | `"sl1/identity" || 01` |
  | `records/<peer_id as 32 lower-case hex>.rec` | `0x01` (1) `||` nonce (12) `||` ct | 13 B + plaintext + 16 | `HKDF(registry_key, salt = empty, info = "sl1/registry")` | `"sl1/rec" || 01 || peer_id` (16 raw bytes) |

  - **`luks_slot`** (v0.9, StickLLM R4): a 1-byte field in both wrap files, after the version byte. It names the keyslot that this wrap's secret opens. Crash recovery (§0 P1) needs it: it is the W compared with the slot S that the entered secret opens.
  - **AD rule for all files:** AD = label || every header byte before the nonce. The salt is already bound through the key derivation. Putting it in the AD as well makes the rule uniform ("the whole header is authenticated").
  - **No ambiguity:** every AD is a fixed label followed by fixed-length fields only. `"sl1/registry-wrap"` is a prefix of `"sl1/registry-wrap-recovery"`, but the lengths differ and the keys differ, so there is no collision.
  - **Version byte:** keep 0x01, since nothing has shipped.
  - **Cipher:** keep ChaCha20-Poly1305 with a 12-byte random nonce. Write volume is far below the random-nonce limit, because `registry_key` gets maybe 10^5 writes in its lifetime and the limit is about 2^32. Anyone moving to XChaCha20-Poly1305 (24-byte nonce) needs version 0x02.
  - **Stick identity:** binding it is implicit. Every key comes from that stick's random `registry_key` or from its own LUKS or Argon2id secret, so a blob from another stick can't decrypt. Don't add the LUKS UUID, which changes on reformat and restore.
  - Labels are ASCII with no terminator (§4.5). The plaintext of a wrap is the 32-byte `registry_key`. The plaintext encodings of a record and of the identity file (`{cur_epoch, cur_priv, pending_epoch, pending_priv}`, §6) are for StickLLM to pin; they don't change the outer format.
  - Why the associated data: without it, a sealed blob could be swapped between files (for example one peer's record put under another `peer_id`) and still decrypt. A record whose `peer_id` doesn't match its file name and AD fails.
  - The PIN wrap has no salt field: the combined unlock secret's own Argon2id salt belongs to the P1 construction StickLLM designs (§0).
- **Pinned slot map (v0.9, StickLLM R4)**, applied after the P1 migration removes the legacy slots:
  - combined secret: A/B slots 0 and 1;
  - stick recovery phrase: A/B slots 2 and 3;
  - no other slots.

  A new slot always goes into the free partner of the pair. Any slot outside the map causes unlock to warn the user and refuse writes.
- **Atomic writes (v0.8, StickLLM R3; the same procedure as §6).** Every write creates a temp file **in the target's own directory** with `O_CREAT|O_EXCL`, mode **0600**, writes it, fsyncs the file, renames it over the target, then **fsyncs the directory**. Leftover temp files are deleted at every unlock, under the lock (§0 P1 crash recovery, step 1).
- **Names (v0.9, StickLLM R4):**
  - the lock file is `sticklink/.lock`;
  - temp files are `.<target>.tmp.<8 random hex>`, created in the target's own directory;
  - deleting a record is `unlink`, then an fsync of `records/`;
  - record writes fsync `records/`, not the parent directory.
- **Directory and locking.** `/mnt/stickllm-settings/sticklink/` (and `records/`) is mode **0700**, owned by the sticklinkd user. Writers are serialised by an exclusive `flock` on `sticklink/.lock`, held for the whole read-modify-write, and for the whole multi-step phrase change (§0 P1) and key rotation step (§6). Readers take a shared lock.
- **Flash rollback (accepted risk, v0.9, StickLLM R6).** **Accepted risk, with the server as the real defence for revocations.** Add an optional local counter only to catch accidents.
  - **Why a counter alone is useless.** A counter on the same flash rolls back together with the data. TPM NV doesn't travel with the stick. A copy on the host SSD ties the stick to one computer, which §3 rejects. So a local `registry_gen` in `identity.sealed`, compared with one in each record, only detects accidental restores (an image or partial copy). It is optional.
  - **Revocations.** Rollback could bring back a revoked record locally. The defence is the signalling directory, which already holds the authoritative state through `slot.del`, permit withdrawal and the revocation counter (§6, Revocation). Rule: **on every unlock, before serving, the stick fetches its home's revoked-peer set and deletes any matching local record. Remove-only: the server can delete records, never add them.**
    - A lying server can only cause a denial of service.
    - The revoked peer also can't reach the stick through the relay, because its permit is gone.
    - **Gap (offline):** until that pull succeeds while offline, a direct LAN or USB path could still accept the record.
  - **Phrase change and cloning (gap: copied stick).** A phrase or PIN change does not protect against someone who copied the stick's raw flash beforehand. The old LUKS header and old wrap together still open with the old phrase. Say so in the user documentation, and point to "re-pair or rotate the identity" as the remedy after a suspected copy.

**AI KVM:**
- One NVS blob per record, in its own namespace `sl1reg`, separate from the `kvm` settings namespace. A settings reset then doesn't drop pairings by accident. NVS is 24 KB; a record is about 150 B.
- A record is written only after the pair-confirm in §4.5 succeeds. One blob per record keeps each write atomic. This matters because unplugging the target's USB reboots the KVM, so power loss during a write is normal.
- The KVM's own identity key is one NVS blob `sl1id` in the same namespace. Its rotation is in §6.
- **Encryption at rest is not a current property.** Today's firmware has no secure boot, no flash encryption and no NVS encryption, and no `nvs_keys` partition. The TLS CA and leaf private keys, the password hash and sessions sit in plaintext NVS. Until the staged plan in §4.B.6 is complete, the KVM's identity key and `pair_psk` can be read by anyone who removes and reads the flash chip. The flash is an external chip on the P4-ETH; for the NANO this is unverified.

**Mobile and desktop:** the OS keystore (Keychain, Android Keystore, DPAPI or Credential Manager, libsecret).

**The signalling server's view:** the home id, slot ids, `jk` join tags and relay permits. During pairing it also sees live routing IDs (split code only), mailbox ids, the QR join tag and the public SPAKE2 messages (§4.6). It never holds `peer_static`, `psk`, the six-digit secret, `invite_secret`, `Ke` or any other pairing secret.

## 4. Pairing methods

All methods end the same way. Each side holds the other's `peer_static` plus a shared `psk`, and the pair-confirm in §4.5 succeeds. Only then is the pairing saved.

At launch: **Methods B, C and D.** Method A is deferred.

**Rules for every method:**
- **Approval happens only on the native approval overlay (§4.7), never in the kiosk browser.** The kiosk is Chromium (cage) loading `http://127.0.0.1/` (StickLLM review, `stickllm-kiosk` lines 2 and 11). So a button in the kiosk is itself a loopback HTTP or WebSocket call, and `stickllm-gateway` trusts loopback (`stickllm-gateway:3279`). Any local process could press it. v0.4's "button on the kiosk screen" is replaced. No HTTP, WebSocket, D-Bus or other local API call can approve a pairing, including from a paired browser.
- **While the overlay is open, StickLLM ignores all input from devices it classes as AI KVM** (§4.7). An AI KVM types and clicks on this machine, so its agent API or MCP server could otherwise approve. This applies to every approval. The user needs a directly connected keyboard, mouse or touch screen to approve. See §8b (g).
- Nothing is stored before the pair-confirm (§4.5).
- Failed attempts, expiry and rate limits: §5.
- Wherever this spec says "the stick asks for approval" or "Allow on the stick", it means the overlay in §4.7.

### 4.A USB ↔ USB (StickLLM to StickLLM). DEFERRED, not available at launch.

**Nink's intent, kept for when it resumes:** the primary stick boots the machine from USB slot 1. A second stick goes in USB slot 2. The primary writes pairing material to stick 2, so **the pairing secret never crosses the network**. **No private key is written.** Stick 2 generates its own identity key.

**Why it's deferred.** StickLLM's review found that the stick as built (v0.5.3) can't do this safely:
1. **Wrong DATA mount.** `stickllm-usb-claim` runs `blkid -L STICKLLM-DATA` and mounts the result before it identifies the boot disk (`resolve_boot_disk`). With stick 2 inserted at boot, the primary can mount stick 2's DATA partition as its own.
2. **Destructive repair.** `stickllm-usb.service` runs `stickllm-usb-claim --auto --yes`. In that mode, a DATA partition that won't mount is reformatted with `mkfs.ext4 -F`. A stick 2 that half-mounts could be wiped.
3. **Settings refuse to load.** `stickllm-usb-settings` refuses when two `STICKLLM-SETTINGS` labels are present.
4. **No udev rule and no automount.** Only the boot disk is ever handled.
5. **No safe writer** for stick 2.
6. **No first-boot hook on stick 2** to read and use the invitation.
7. **No encrypted place on stick 2** before its vault is set up. The only writable place is plaintext DATA, so `invite_secret` would be readable by anyone who holds stick 2 during the 1-hour window.
8. **Flash can't be securely deleted.** v0.3's "it then deletes the invitation" doesn't work on flash.
9. v0.3's "same machine, stick 2 already has an identity" variant didn't define the pairing secret or the `pair_psk` derivation.

**What has to exist before §4.A resumes:**
- `stickllm-usb-claim` resolves the boot disk first and mounts DATA and SETTINGS from that disk only, never by label alone.
- No automatic `mkfs` on any disk that isn't the boot disk.
- Settings loading uses the boot disk's partition instead of failing when a second stick is present.
- A udev rule that lets the helper below find the second stick, and that never mounts or repairs it by itself.
- A new root helper, called through sudoers like the existing helpers. It targets only a removable, non-boot disk by serial, mounts it read-write in a private directory, writes one file atomically, shows the drive's model and serial, and requires typed confirmation.
- A first-boot hook on stick 2, in the claim or sticklinkd path, that reads the invitation and runs the §4.C-style bootstrap.
- An encrypted home for stick 2's identity key and registry. So stick 2's vault, with P1 (§0), must be set up before the invitation is used.
- Single use enforced by the signalling server and by the primary's registry, not by deletion. A used or expired invitation is refused even if the file is still on the flash.
- A defined secret and derivation for the same-machine variant, or the variant is dropped.
- A decision on invitation exposure: accept a readable invitation for up to 1 hour, documented, or write it only into stick 2's encrypted storage.

When it resumes: the invitation carries `{mailbox id, primary_static_pub, invite_secret (32 B), expiry, signalling URL}` and uses method label `usb-invite` in §4.5. Nobody types it, so it can carry a full-length mailbox id instead of a 4-digit routing ID; that is settled when §4.A resumes. Decision 5 (§8: 1 hour, manual regeneration) applies. See §8b (c).

### 4.B ESP32-P4 AI KVM over USB. Check code.

In short: StickLLM and the KVM run Noise XX over a vendor-defined HID collection on the USB link that already carries keyboard and mouse. A commit-then-reveal check code, shown somewhere the host PC doesn't control, authenticates the pairing. Later sessions go over the network with IKpsk2, and the KVM is always the initiator, which matches SIGNALLING-PLAN.md.

#### 4.B.1 Hardware facts (from AI KVM's review)

- **Stock ESP32-P4-ETH:** BOOT and RST buttons and a power LED only. No user button and no LED the firmware can drive. BOOT is GPIO 35, which is shared with Ethernet and can't be read at runtime.
- **Stock ESP32-P4-NANO:** BOOT and RESET buttons, and a "USER-LED" that is a power indicator. Which GPIO BOOT uses, and whether it has the same Ethernet conflict, is unverified.
- The firmware has a "Button on the box" setting (`btn_gpio`). It hasn't been tried on real hardware.
- The firmware has **no status-LED output**. `KVM_ATX_LED_GPIO` is an input that senses the target's power LED. A status LED needs new code.
- The firmware supports a **status display** (`kvm_display`: round GC9A01 or I2C OLED). It's an add-on, not part of either stock board. The NANO defaults reserve GC9A01 pins, tested on the NANO by a contributor.
- So v0.3's "press the pairing button", "the LED blinks", "solid green" and "hold the button for 3 s" can't be done on either stock board. v0.4 removes them or makes them depend on added hardware. There is no colour LED, so no colours are specified.

#### 4.B.2 Trigger and display: OPEN DECISION, §8b (b)

| Option | Starts pairing | Shows the code | KVM-side confirmation | Notes |
|---|---|---|---|---|
| 1. Added button and LED on header pins | Button press | Not the LED (it can't show 6 digits). Needs option 2 or the web page. | Button press | Candidate pin GPIO 48: free on every board except the Guition, but only while ATX LED sensing doesn't use it. Exact free pin unverified on hardware. The LED needs new firmware. |
| 2. Status display (**default**, AI KVM's preferred option) | Logged-in config UI, or a button if fitted | On the display | Logged-in config UI, or a button if fitted | The host PC can't touch it, so it's the best independent display. Fits inside the case, adds no cable. |
| 3. Logged-in config UI only | "Pair StickLLM" action, which opens a 60 s window | Config web page on a second device | Same web session | Weaker presence: it shows the user is logged in, not physically there. |

**Which pairing remains possible (R6):**

| Hardware fitted | A second device can reach the KVM's LAN | No second device can reach it |
|---|---|---|
| Display and button | Full pairing | Full pairing: button starts, display shows the code, button confirms |
| Display only | Full pairing: web UI starts and confirms, display shows the code | **Refused** |
| Button and LED only | Full pairing: code on the web page | Presence-only fallback, if the admin allows it. Otherwise refused. |
| Nothing added (stock board) | Full pairing by option 3 | **Refused** |

The KVM's first network setup (setup hotspot, password change) has to be done before pairing in every case.

**Firmware constraint (v0.7, AI KVM's note):** pressing the pairing trigger must **not** make the KVM re-enumerate on USB. The 0xFF00 collection is already in the normal-mode descriptor. Otherwise the KVM would appear as a new device during its own pairing (§4.7).

**Presence-only fallback** (decision 1, §8), only where a button is fitted: StickLLM shows "Ready", and the user holds the KVM's added button for 3 s. If an LED is fitted, it shows that the press registered. **Documented limit:** this proves physical presence only. It doesn't protect against a compromised host PC that relays or swaps the pairing. The UI has to tell the user this, and an admin may turn the fallback off.

#### 4.B.3 USB transport (R4)

- The firmware presents, in normal composite mode:
  - HID keyboard (ITF0, EP 0x81)
  - HID absolute pointer plus consumer control (ITF1, EP 0x82)
  - HID relative mouse (ITF2, EP 0x83)
  - optional gamepad (EP 0x85/0x05)
  - optional virtual media, MSC (EP 0x84/0x04, off by default)
- There is no USB audio and no config interface. v0.3 was wrong about this.
- **Pairing uses a vendor-defined HID collection added to ITF1's report descriptor** (usage page 0xFF00), with feature reports over EP0. It must be a **top-level Application collection** (AI KVM's note), so Windows gives it its own HID device that the mouse stack doesn't open exclusively. That needs no new endpoint, interface or string descriptor, no re-enumeration and no COM port, and it needs no Windows driver. On StickLLM's Linux it is a hidraw device; sticklinkd needs a udev rule for access.
- **udev rule (X3, rewritten in v0.6: StickLLM R2, AI KVM item 2).** The v0.5 rule never matched: udev(7) requires all `ATTRS` matches to be on the same device, but `idVendor` and `serial` sit on the `usb_device` and `bInterfaceNumber` on the `usb_interface`. It also blocked the pad-added modes, which don't enumerate as 303A:4012. The rule is now:
  ```
  # /etc/udev/rules.d/70-sticklink-aikvm.rules (proposal, untested)
  SUBSYSTEM=="hidraw", IMPORT{builtin}="usb_id"
  SUBSYSTEM=="hidraw", ENV{ID_SERIAL_SHORT}=="AIKVM-????????????", ENV{ID_USB_INTERFACE_NUM}=="01", GROUP="sticklinkd", MODE="0660"
  ```
  - `usb_id` sets `ID_VENDOR_ID`, `ID_SERIAL_SHORT` and `ID_USB_INTERFACE_NUM` (StickLLM's review, `udev-builtin-usb_id.c` lines 381, 385, 419). Whether it does so for hidraw nodes on the stick's udev version is **untested**; StickLLM tests it.
  - The glob matches exactly `AIKVM-` plus 12 characters, the §4.B.4 format (v0.7, StickLLM's note).
  - **No VID match.** The VID differs by mode (303A, 0F0D, 045E), so the rule relies on the serial prefix, interface 01 and the descriptor check. StickLLM proposed `ENV{ID_VENDOR_ID}=="303a"` too; it is left out so pairing works in the pad-added modes (AI KVM item 2).
  - Access goes to the `sticklinkd` group only, mode 0660. Never all hidraw devices (security keys are hidraw too) and no `uaccess` tag.
  - Before use, sticklinkd reads the report descriptor and checks it has the top-level 0xFF00 collection with report ID 0x5A. A device that fakes the serial gets only as far as a pairing attempt, which still needs the code.
- Not CDC: CDC-ACM would use all 8 of 8 IN endpoints in the largest configuration (gamepad plus MSC) and shows up as a COM port, which device-control policies often block. A vendor bulk pair would fit (7 of 8) but needs WinUSB descriptors on Windows; it's the second choice.
- **Pairing is available in normal composite mode (303A:4012) and in "HID + gamepad added" mode** (HORI added 0F0D:0092, XInput added 045E:028E; both have ITF1). It isn't available in legacy BIOS mode (keyboard only) or in the gamepad-only modes (XInput/XID, Switch). When StickLLM can't find the pairing collection, it says "Pairing isn't available in this USB mode" and asks the user to switch the KVM to normal mode.
- The vendor collection is visible to every host and so is a fingerprint of the device. The firmware may put it behind a setting ("Allow USB pairing", on by default). AI KVM suggests this; it is optional.
- The `AIKVM-` serial gives the KVM's Ethernet MAC to every USB host. The MAC is already visible on the LAN. **Accepted** (AI KVM's note).

**HID framing (new in v0.5, AI KVM item 2; stop-and-wait in v0.6, AI KVM item 1).** Fixed by the firmware design and covered by the vectors (§4.5):
- One feature report: **report ID 0x5A plus 63 bytes**. 64 bytes is a hard cap (`CFG_TUD_HID_EP_BUFSIZE` = 64).
- The 63 bytes are an 8-byte header and 55 bytes of payload:

| Byte | Field | Values |
|---|---|---|
| 0 | version | 0x01 |
| 1 | type | 0x01 DATA; 0x02 ACK (no data, carries only `ack`); 0x03 ABORT; 0x04 reserved. Any other value is a protocol error. |
| 2 | seq | DATA only: the sender's frame counter, 0x00–0xFE, wraps to 0x00. ACK and ABORT frames carry 0x00 here and it is ignored; they don't use a number. |
| 3 | ack | the last DATA seq accepted from the other side, 0xFF if none |
| 4 | msg_no | DATA: sender's message counter, from 0, mod 256. ACK/ABORT: 0x00 |
| 5 | frag_idx | DATA: 0-based fragment index. ACK/ABORT: 0x00 |
| 6 | frag_cnt | DATA: 1–3. ACK: 0x00. ABORT: 0x01 |
| 7 | len | DATA: payload bytes used, 1–55. ACK: 0. ABORT: 1 |
| 8–62 | payload | zero-padded. ABORT: the reason in payload[0] (§4.B.5 reasons) |

v0.5 had 0x02 as "IDLE/BUSY" and 0x04 as "RESET". BUSY is dropped (AI KVM's note: the host treats it like IDLE anyway). RESET was never defined and is now reserved. The 0x02 frame the KVM returns when it has nothing to send has the same layout as the v0.5 IDLE frame.

- A message is one Noise handshake message or one Noise transport message (below). It is cut into 55-byte fragments. **Reassembly is capped at 128 bytes (3 fragments)** (v0.6, AI KVM's note; it was 1280). The largest real message is XX msg 2, 96 bytes.
- **Reassembly checks.** The receiver rejects the message (protocol error) on any of:
  - `frag_cnt` of 0 or over 3, or `frag_cnt` changing within a message;
  - `frag_idx` out of order;
  - `msg_no` not the expected one;
  - `len` over 55, or `len` not 55 on any fragment except the last;
  - a total over 128 bytes.
- **The host drives everything.** StickLLM sends one frame per `SET_REPORT(Feature, 0x5A)`. It polls with `GET_REPORT(Feature, 0x5A)`. The KVM answers from `tud_hid_get_report_cb`: its current unacknowledged DATA frame, or an ACK frame when it has nothing to send (including while it computes). It never STALLs.
- The KVM does the X25519 and other crypto in a task, never in the USB callback.
- **Stop-and-wait in each direction (v0.6, AI KVM item 1).** Why: TinyUSB calls `tud_hid_get_report_cb` in the SETUP stage and has no completion callback for a control GET (`hid_device.c` line 303), so the KVM can't tell whether the host received a GET reply. One failed `HIDIOCGFEATURE` would otherwise lose a frame for good.
  - **KVM to host:** the KVM returns the **same DATA frame on every GET** until a host SET carries `ack` equal to that frame's seq. Only then does it move to its next frame. The `ack` byte of a repeated frame is filled in at GET time; seq and payload never change.
  - **Host to KVM:** the host sends a DATA frame by SET, then GETs. If the reply's `ack` equals that seq, it may send its next DATA frame. If not, it repeats the same SET.
  - **Ack-only:** when the host has no DATA to send, it acknowledges a KVM frame with a SET of type 0x02 that carries only `ack`.
  - **Receiver rule:** the first DATA frame from each side has seq 0x00. After that, accept only seq = last accepted + 1 mod 255 (0xFE is followed by 0x00). A frame with seq equal to the last accepted one is a repeat: drop it, but still acknowledge it. Any other seq is a protocol error.
  - ACK frames are never acknowledged or repeated by the other side.
- **ABORT frame (0x03, v0.6).** The reason is in payload[0]. It is **unauthenticated**. It is the only way to abort before the XX handshake completes, because 0x7F needs the transport keys. After XX, a side aborts with 0x7F and may also send 0x03 if it can no longer encrypt. Receiving 0x03 may only **end the attempt**: it changes no record, and the stick shows "Pairing failed" whatever the reason byte says.
- **ABORT lifetime (v0.7, AI KVM item 1).** After aborting, the KVM answers **every GET with its ABORT frame for a fixed 5 s**, ignoring every SET. Then it closes the window, and from then on GETs get the outside-window ACK (`ack` 0xFF). The host sends its own ABORT once.
- **The host treats `ack` falling back to 0xFF mid-attempt as the end of the attempt**, the same as an ABORT. "Mid-attempt" means after the KVM has acknowledged at least one host DATA frame. This covers a host that missed the 5 s ABORT period, and a KVM that rebooted.
- **A KVM abort before any ack (v0.8, AI KVM's nit).** If the KVM aborts before it has acknowledged any host DATA frame, and the host misses the 5 s ABORT period, the host never saw an ack other than 0xFF, so the fallback rule above doesn't fire. That attempt ends only when the stick's 60 s window closes (§4.B.5). Nothing has been stored by then, so this costs only time.
- Outside the pairing window, the KVM answers every GET with an ACK frame (`ack` 0xFF) and ignores every SET.
- **Normal end:** the KVM closes its window only after its last DATA frame (0x08) has been acknowledged by a host SET, or after the inactivity timeout (§4.B.5).
- Throughput: each fragment now costs a SET and a GET. Unmeasured. The whole exchange is 16 DATA frames, so 32 control transfers (§4.5 vectors).

**Host APIs (from AI KVM's review):**

| Host | API | Notes |
|---|---|---|
| Linux (StickLLM) | hidraw: `HIDIOCSFEATURE` / `HIDIOCGFEATURE`, `buf[0] = 0x5A` | hidraw is per interface; the udev rule above |
| Windows | `HidD_SetFeature` / `HidD_GetFeature` | No driver needed |
| macOS | `IOHIDDeviceSetReport` / `GetReport`, feature type | Whether this needs Input Monitoring permission is **unverified** |
| Any | hidapi | Covers all three |
- The firmware recognises the target OS from descriptor-request patterns. Retest that on Windows, macOS, Linux and Android after adding the collection.

#### 4.B.4 Handshake (R2)

- **Pattern:** `Noise_XX_25519_ChaChaPoly_SHA256`.
- **Initiator: StickLLM.** It's the USB host, and feature reports are driven by the host: the host sends and polls, and the device only answers. So the host naturally speaks first, and the KVM never has to push. This is separate from the network rule, where the KVM always initiates IKpsk2.
- **Prologue:** `"sl1/kvm-usb/v1" || u16be(VID) || u16be(PID) || enc(serial)`, with `enc` from §4.5. VID and PID are those of the USB mode the KVM is in. StickLLM uses what it read from the device descriptor. The KVM uses its own values. A mismatch fails the handshake.
- **USB serial (firmware requirement, new in v0.5, AI KVM item 1).** Today the serial string (index 3) is the constant `"0"` on every unit (`usb_hid.c` line 223, `usb_descriptors.c` line 62). v0.5 requires a per-device serial:
  - Format: ASCII `AIKVM-` followed by the **12 uppercase hex digits of the 6-byte factory base MAC** read from eFuse (`esp_efuse_mac_get_default`), first byte first, no separators. 18 bytes, for example `AIKVM-0123456789AB`. This is the same MAC the Ethernet driver uses by default.
  - Set as string index 3 in **every** mode that has string descriptors. The gamepad modes swap only indices 1 and 2, and the HORI pad also uses index 3. XID has no strings.
  - Windows sees each unit as a new device instance once, after the change. Retest OS fingerprinting.
  - **Unverified:** that Espressif burns a unique factory MAC into every unit.
  - `serial` in the prologue and `TH` is these 18 ASCII bytes.
- **XX payloads:** all three handshake payloads are **empty**.
- **TH:** method `"kvm-usb"`, no routing ID, empty `home_id`, both statics, and the serial (§4.5). The empty `home_id` is intentional: the KVM learns the home id only after pairing (step 8 below), and the pairing doesn't depend on it.

#### 4.B.5 Flow

1. The user starts pairing on the KVM (by the trigger chosen in §4.B.2) and picks "Pair an AI KVM" on the StickLLM kiosk. The KVM opens a **60 s** window. Outside that window it ignores pairing reports.
   - **The window covers the whole flow, up to step 14** (v0.6). The "unconfirmed" rule below covers a window that expires during steps 9–13.
   - **Inactivity timeout: 15 s** (v0.6 proposal; AI KVM suggested 5 s). After XX msg 1, if the KVM sees no host SET or GET for 15 s, or the stick gets no reply to its GETs for 15 s, that side aborts with reason 0x02. The stick keeps polling while the users compare the code, so a slow confirmation doesn't trip it.
   - **Required test (UX, unverified):** whether 60 s is enough when the KVM side is confirmed from a second device's web UI, including opening the page and checking the certificate fingerprint.
2. StickLLM finds the pairing collection and runs XX as initiator. **The USB cable, the trigger and a logged-in session don't authenticate the computer.** Only the check code does.
3. **Commit-then-reveal**, inside the XX transport after the handshake completes, as in Bluetooth LE numeric comparison (R1):
   1. The KVM (responder) picks a 32-byte random `Nb` and sends `Cb = SHA-256(enc("sl1/kvm-commit") || h || Nb)`, where `h` is the XX handshake hash.
   2. StickLLM picks a 32-byte random `Na` and sends it.
   3. The KVM sends `Nb`.
   4. StickLLM checks `Cb`. A mismatch aborts the attempt.
   5. Both compute the code (step 4).

   Why: the KVM fixes `Nb` before it sees `Na`, and StickLLM reveals `Na` before it sees `Nb`. A man in the middle running two sessions can't steer both codes to the same value. It gets one chance in 10^6 per attempt. v0.3's code was a function of the handshake hash alone, which malware on the host could grind in about 10^6 tries, a few seconds on a PC.

   `Na`, `Nb`, `r_i` and `r_r` come from a CSPRNG (`esp_fill_random` on the KVM). `Na` and `Nb` are used only for the code. They are never reused as `r_i` or `r_r` in §4.5.
4. **Code:**
   ```
   sas  = HKDF(ikm = Na || Nb, salt = h, info = "sl1/kvm-sas", L = 8)
   code = uint64_be(sas) mod 1,000,000, written as 6 decimal digits with leading zeros
   ```
   Using 8 bytes keeps the bias from the reduction below 10^-13.
5. **Show and confirm.** StickLLM shows the code on its approval overlay (§4.7), never in the kiosk browser. The KVM shows it as §4.B.2 allows. The user confirms the match on **both** sides: Allow on the stick's approval overlay (§4.7), and on the KVM side by the logged-in config UI or a fitted button. If either side rejects, or 60 s pass, the pairing is thrown away and the window closes.
6. **Where the KVM may show the code (R5).** Only on:
   - the status display, or
   - the config web page, to a **logged-in console session over HTTPS whose password has been changed from the default**. Not to a `must_change` session, not to a viewer bearer token, and never through the HID or agent REST API or the MCP server.

   Also:
   - The user checks the page's certificate fingerprint, or has imported the device CA. The certificate is self-signed, so otherwise a LAN attacker could serve a look-alike page. How the user gets the fingerprint is below.
   - Pairing is refused while the password is the default, and when the page is reached over the setup hotspot without HTTPS.
   - The page is opened from a **second device over the KVM's LAN (Ethernet or Wi-Fi)**, not from the PC the KVM is plugged into. The UI says plainly that **confirming from the plugged-in PC defeats the check**. The KVM can't fully enforce it.
   - While the confirmation is pending, StickLLM ignores the KVM's input (§4.7).
7. Both sides derive `pair_psk` inside the XX session (§4.5) and run the pair-confirm. The KVM stores the stick's static key and `pair_psk` as one NVS blob in `sl1reg` (§3). If an LED is fitted, it shows the paired state.
8. StickLLM sends the home id and slot id to the KVM inside the XX session (§4.6). The KVM sends its TLS certificate fingerprint, and StickLLM pins it.
9. StickLLM pins the KVM's USB port for this computer (§4.7).
10. Later sessions go over the network with IKpsk2. The KVM is the initiator.

Limits: one XX attempt per trigger. A failed commitment check, a failed handshake, a rejected code, a failed pair-confirm or any protocol error ends the attempt and closes the window (§5). On the KVM, the window closes after the 5 s ABORT period (§4.B.3).

**Inner messages (new in v0.5, AI KVM item 2).** After XX, every message is one Noise transport message. Its plaintext is `type (1 byte) || body`. The Noise AD is empty.

| Type | Name | Body | Sent by |
|---|---|---|---|
| 0x01 | `Cb` | 32 B commitment | KVM |
| 0x02 | `Na` | 32 B | Stick |
| 0x03 | `Nb` | 32 B | KVM |
| 0x04 | user confirmed | empty | Both, each once its user confirmed |
| 0x05 | `r` | 32 B (`r_i` from the stick, `r_r` from the KVM) | Both |
| 0x06 | pair-confirm | 32 B HMAC (§4.5) | Both |
| 0x07 | home and slot | `home_id` (16 B) `||` `slot_id` (8 B) | Stick |
| 0x08 | TLS fingerprint | 32 B SHA-256 of the KVM's leaf certificate (DER) | KVM |
| 0x7F | abort | reason, 1 byte | Either, at any time |

Abort reasons (proposal), used both in 0x7F and in the ABORT frame: 0x01 user rejected, 0x02 timeout, 0x03 commitment failed, 0x04 confirm failed, 0x05 protocol error, 0x06 busy, **0x07 internal or storage error** (v0.6, for example the KVM's NVS write at step 13 failing). An unknown reason value is treated as 0x05.

What the stick shows: for 0x03 and 0x04, "Pairing failed: possible interception" (as in §5); for every other reason, and for any ABORT frame, "Pairing failed".

**State machine (strict).** Each side runs these steps in order and accepts only the one expected next message:

| Step | Stick (initiator) | KVM (responder) |
|---|---|---|
| 1 | Sends XX msg 1 | Accepts it only inside the 60 s window |
| 2 | Receives XX msg 2 | Sends XX msg 2 |
| 3 | Sends XX msg 3 | Receives XX msg 3. Handshake done. |
| 4 | Waits for `Cb` | Picks `Nb`, sends 0x01 `Cb` |
| 5 | Only after `Cb`: picks `Na`, sends 0x02 | Waits for `Na` |
| 6 | Waits for `Nb` | Only after `Na`: sends 0x03 `Nb`, then shows the code |
| 7 | Checks `Cb` against `Nb`. Only if it matches: shows the code | — |
| 8 | After its user confirms: sends 0x04. Accepts the KVM's 0x04 at any point after step 7, even before its own user confirms. | After its user confirms: sends 0x04. Accepts the stick's 0x04 at any point after sending `Nb`, even before its own user confirms. |
| 9 | After 0x04 is both sent and received: sends 0x05 `r_i` | Waits for `r_i` |
| 10 | Waits for `r_r` | Only after both 0x04 and `r_i`: sends 0x05 `r_r` |
| 11 | Computes `pair_psk`, sends 0x06 `confirm_i` | Computes `pair_psk`, checks `confirm_i`, then sends 0x06 `confirm_r` |
| 12 | Checks `confirm_r`, saves its record, sends 0x07 | Waits for 0x07 |
| 13 | Waits for 0x08 | Saves its record (§3) on 0x07, sends 0x08 |
| 14 | Pins the fingerprint, pins the USB port | Done; closes the window |

Rules:
- `Na` is never sent before `Cb` is received. `Nb` is never sent before `Na` is received. The stick shows the code only after the `Cb` check; the KVM only after sending `Nb`.
- The peer's 0x04 may arrive before the local user confirms. That is expected, not "unexpected": channel order already puts it after `Nb` (AI KVM's note). Each side then waits for its own user.
- A repeated **frame** (same seq) is dropped and re-acknowledged (§4.B.3). A frame-layer protocol error or an ABORT frame ends the attempt the same way. A repeated, unexpected or out-of-order **message**, a message of the wrong length, or a failed decryption **aborts** the attempt. The side that aborts sends 0x7F if it can, wipes the session keys and the nonces, and ends the attempt. The KVM then serves its ABORT frame for 5 s and closes the window (§4.B.3); the stick closes its overlay at once. **The same 5 s period applies when the host is the side that aborted** (v0.8, AI KVM's nit): on receiving the host's 0x7F or ABORT frame, the KVM wipes its session and serves its own ABORT frame, carrying the host's reason (0x05 if it had none), for 5 s, then closes. The host has already ended the attempt and ignores it. The echoed reason is informational only: ABORT frames are unauthenticated, so neither side acts on its value beyond ending the attempt (confirmed by AI KVM, v0.8).
- 0x07 and 0x08 come after both records exist. If the session breaks after step 12, the stick has a record but the KVM may not. The stick then marks the record "unconfirmed" and the user pairs again; the KVM keeps nothing without 0x07. (Proposal.)
- If 0x08 is lost, the KVM has a record and the stick's is "unconfirmed". Re-pairing **replaces** the record keyed by the peer's static key on both sides (an upsert). It never adds a second record for the same `peer_static` (v0.6, AI KVM's note).
- Noise transport nonces count from 0 in each direction. The vectors (§4.5) list every message and frame for one full run, and the full SET/GET sequence with ACK frames.

**Certificate fingerprint for the config page (AI KVM's advice).** In order of preference:
1. The status display shows the fingerprint as grouped hex (the first 64 bits in 4 groups of 4 hex digits, the full value on a second page) and as a QR code. The firmware already depends on `espressif/qrcode` (`dependencies.lock`).
2. The serial console prints `TLS fingerprint: …` at every boot.
3. After the first pairing, StickLLM pins the fingerprint it received in message 0x08 over the authenticated USB session, and can show it for later visits.
- A printed label doesn't work: the certificate is generated on the device.
- A unit with only the config UI (no display, no console access) falls back to trust on first use for the page. The UI says so.

#### 4.B.6 KVM security staging (R7). Timeline: OPEN DECISION, §8b (e)

Network OTA keeps working through every stage. Both OTA paths use `esp_ota_*`. App rollback is already on.

| Stage | What | eFuses | Notes |
|---|---|---|---|
| 0, now | Signed OTA images: `CONFIG_SECURE_SIGNED_APPS_NO_SECURE_BOOT`, **RSA-3072**. OTA then accepts only images we signed. | None | Today anyone with a web login can upload any image, and that image could read `pair_psk`. Undone only by a cable reflash. |
| 0b, before the first shipped pairing build | **Freeze the final partition layout.** Measure the bootloader size with secure boot and flash encryption on. If it doesn't fit the 24 KB between 0x2000 and 0x8000, move the partition table once, now. If the flash-encryption NVS scheme is chosen, reserve a 4 KB `nvs_keys` partition at the same time (it could come from the 56 KB `coredump` partition). | None | Bootloader size is **unverified**. Moving the table shifts `nvs` and `otadata` and can only be done by cable, not OTA, which conflicts with the "offsets unchanged" policy. So do it before devices are in the field. |
| 1, one **spare** board only | Flash encryption in **Development** mode. NVS encryption with the HMAC scheme (one HMAC-key eFuse block, no new partition). Secure Boot v2 with **RSA-3072 only**. Program 2 or 3 key digests and revoke unused slots. | Burned | ECDSA secure boot is broken in ROM on the P4 up to rev 3.2 (errata ECDSA_DS-836/837, advisory AR2026-006), with no software fix. Test on the spare: OTA upload and release fetch with a signed image, rollback after a deliberately bad image, MSC rescue and SPIFFS still working, and that `coredump` is encrypted or core dumps to flash are off in release builds (they're on today). Coredump behaviour is **unverified**. |
| 2, only after Stage 1 passes | Flash encryption **Release** mode. `SPI_BOOT_CRYPT_CNT` write-protected. Secure download mode on, or UART download off. JTAG stays disabled. | Burned | Plan RMA and reflash assuming the board can never take a plaintext cable flash again. |

Other notes:
- eFuse changes are one-way. A mistake can brick the board. Prove each step on a spare board first.
- Secure boot without flash encryption is open to time-of-check/time-of-use attacks on the KVM. Do both.
- Enabling secure boot or flash encryption turns off the ROM's USB-OTG download mode, not the app's TinyUSB. HID and USB pairing aren't affected.
- Errata by revision: the dev P4-ETH is rev v1.3, where only the ECDSA errata applies. The NANO ships as rev 1.x or 3.x under one product code. On rev 3.0, ROM-764 (secure boot verification failure) applies. On rev 3.1, ROM-770 (secure download mode flash power-on failure) applies. Their workarounds haven't been read (**unverified**). Read them before choosing the NANO's revision or download-mode setting.
- **Until Stage 2 ships, the KVM's identity key and `pair_psk` are readable from the flash chip** (§3). Release notes must say so.
- **NVS migration (AI KVM).** Turning on NVS encryption on a unit that already has plaintext settings needs either a migration step (read the plaintext entries, erase, write them encrypted) or a documented reset of the existing settings. Choose one before Stage 1 and test it on the spare board.
- **Bootloader on field units (AI KVM).** Secure boot and flash encryption need a new bootloader. On units already in the field that means a **cable flash**, not OTA. Whether ESP-IDF can update the bootloader over OTA on the P4 is **unverified**. Add the cable step to Stage 1 and to the field plan.
- **Random numbers (AI KVM).** The KVM uses `esp_fill_random`. Whether the P4's TRNG is fully seeded without a radio (the P4-ETH has none; the SAR-ADC is the other entropy source) is **unverified**. Check the ESP-IDF documentation for the P4 before Stage 0b.

#### 4.B.7 Still to check (AI KVM team)

- The exact free GPIO for a button and LED, on hardware.
- Bootloader size with secure boot and flash encryption.
- OS fingerprinting retest, after the collection and the new serial are added.
- The NANO's BOOT GPIO, and the NANO errata workarounds.
- That every unit has a unique factory MAC burned in eFuse (§4.B.4).
- The real PID as seen by a host (0x4012 is derived from source, not observed).
- The P4 TRNG without a radio (§4.B.6).
- Whether macOS needs Input Monitoring for feature reports (§4.B.3).
- The NANO's RTC battery wiring, and the P4-ETH schematic (§6).
- Whether the IDF bootloader can be updated over OTA (§4.B.6).
- Whether `espressif/tinyusb` 0.21.0~1 matches upstream for the feature-report callbacks.
- Throughput of the framing (§4.B.3), now with a SET and a GET per fragment.
- **Console retest (new in v0.6):** Switch and Xbox behaviour, now that the HORI and XInput descriptors carry an `AIKVM-` serial at index 3 instead of `"0"`. AI KVM is retesting this. If a console rejects it, the serial rule of §4.7 doesn't hold in that mode, and §4.7 must be revised.
- Where a browser sign-in sets the KVM's clock, as the `kvm_rtc` comments say (§6). AI KVM couldn't find that code.
- RTC-chip behaviour other than the DS3231 (§6).
- That the pinned IDF version derives the P4 Ethernet MAC from the base MAC with no offset (checked only in IDF master).

Closed in v0.5: the USB serial string (§4.B.4), and report size and fragmentation (§4.B.3). The USB FIFO allocation item is closed per AI KVM's re-review.
Closed in v0.6: frame acknowledgement (stop-and-wait, §4.B.3); the multi-page NVS question (§6: `sl1id` is about 72 B).
Closed in v0.7: `components/kvm_rtc` was read (§6).

### 4.C Mobile by QR. 60 s.

1. The user starts "Add device" on the StickLLM kiosk. The stick creates a 32-byte `invite_secret` and a **60 s** expiry. It asks signalling for a mailbox (`pair.open`, §4.6), sending the QR join tag. It shows, on the approval overlay (§4.7), a QR code containing `sl1:M=<mailbox id, 16 hex digits>&K=<stick static pub>&P=<invite_secret>&E=<expiry>`. Nobody types the QR, so it uses the full 8-byte mailbox id and no `RRRR` (X2, changed in v0.5). If the optional code next to the QR (§11.1) is adopted, that screen also gets an `RRRR`.
2. The phone scans it. The QR code carries the stick's public key and a one-time secret, so scanning it authenticates the stick. It isn't just an address.
3. The phone generates or loads its own identity. It joins the mailbox with the mailbox id and a join MAC (§4.6). The server tells it the home id.
4. The phone opens **Noise IKpsk2** as initiator. It knows `K` from the QR code. The PSK is `boot_psk` with method `qr` (§4.5). Mailbox messages are sealed under the QR pairing envelope (§4.5, §4.6).
5. After the handshake completes, the phone sends its device name inside the session. The stick asks for approval on its approval overlay (§4.7): "Allow <phone model / name>?"
6. After Allow, both sides derive the long-term `pair_psk` (§4.5), run the pair-confirm and save the registry records. The stick sets up the signalling slot (§4.6). `invite_secret` is destroyed in memory, and the mailbox is closed.

### 4.D Desktop without a camera. Split code with SPAKE2.

**Code format: `RRRR-SSSSSS`**, for example `4821-907316`.
- `RRRR` is the **routing ID**. The signalling server assigns it, and it is unique across all homes while live (§4.6). The server uses it to connect the desktop to the right StickLLM pairing mailbox.
- `SSSSSS` is the **six-digit secret**, about 20 bits, chosen by the stick uniformly from 000000 to 999999 with a secure random generator. **Only the two devices ever use it. The rendezvous server never sees it.**

**SPAKE2 parameters (pinned):**

| Parameter | Value |
|---|---|
| Suite | `SPAKE2-P256-SHA256-HKDF-HMAC`, RFC 9382 |
| M, N | The fixed P-256 constants in RFC 9382 §6. Not the per-user M and N of RFC 9382 §5. |
| Party A | The desktop. Sends `pA`. |
| Party B | The stick. Sends `pB`. |
| Point encoding | Uncompressed SEC1 (65 bytes, 0x04 prefix), as in the RFC vectors |
| idA | ASCII `sl1/desktop` (11 bytes) |
| idB | ASCII `sl1/stick|` followed by the 16 raw bytes of `home_id` (26 bytes) |
| Password `pw` | The six digits `SSSSSS` as 6 ASCII bytes, leading zeros kept. No dash, no `RRRR`. |
| `w` | `w = OS2IP(HKDF(ikm = pw, salt = empty, info = "sl1/spake2-w" || RRRR || home_id, L = 48)) mod p`, where `p` is the P-256 group order and `RRRR` is 4 ASCII bytes. |
| TT, Ke, Ka | As RFC 9382: `Ke || Ka = SHA-256(TT)`. `Ke` is 16 bytes (128 bits). That is fine as HKDF input. |
| Confirmation keys | As RFC 9382, `KDF(Ka, nil, "ConfirmationKeys" || AAD)`, with `AAD = "sl1" || RRRR || home_id` (3 + 4 + 16 bytes) |
| `cA`, `cB` | `HMAC-SHA256(KcA, TT)` and `HMAC-SHA256(KcB, TT)`, as RFC 9382 |

Note on `w`: RFC 9382 requires the protocol to define how `w` is computed, and says the hash SHOULD be memory-hard. v0.4 proposed HKDF without a memory-hard function. Reasons: the code space is 10^6 either way, the code lives for 60 s and is never stored, and the protection that matters is the one-guess-per-code online limit (§5). 48 output bytes cover the RFC's advice to reduce a hash at least 64 bits longer than `p`. The external audit (§8b a) should confirm this choice. The RFC vectors start from `w`, so our `sl1` vectors must cover `pw → w`.

**StickLLM accepted plain HKDF in its v0.4 re-review**, because SPAKE2 gives no offline test of a guess, an active attacker tests one guess per session, §5 burns the code after one failure, and RFC 9382 leaves the method to the protocol. **Conditions, binding on every implementation:**
1. **Never persist** `pw`, `w`, `x` or `y`, `Ke`, `Ka`, the SPAKE2 state, the displayed code `SSSSSS`, or (for Method B) `Na`, `Nb` and the KVM code. Not to disk, logs, crash dumps or swap. On the stick: no core dumps for sticklinkd (`LimitCORE=0`, and the process marked non-dumpable), secret buffers locked in memory where the platform allows, and wiped after use. On the KVM: core dumps to flash off, or encrypted, in release builds (§4.B.6).
2. **Any stored PIN- or password-derived value uses a tuned slow hash.** That covers the P1 combined slot (Argon2id, §0) and the legacy `stickllm-pair` hash for as long as it lives (§0 P2, §8b f).
3. **Revisit** this choice, and use a memory-hard function, if the code is ever made longer-lived, reusable or user-chosen.
4. The `sl1` vectors cover `pw → w`.

The desktop learns `home_id` from the server when it joins (§4.6). If the server lies about it, idB and the AAD don't match and SPAKE2 fails. That is a denial of service, which a server can do anyway.

**Flow:**
1. On the StickLLM kiosk, the user starts "Pair a desktop". The stick asks signalling for a routing ID (`pair.open`, §4.6), picks `SSSSSS`, and shows `RRRR-SSSSSS` on the approval overlay (§4.7). It expires in **60 s**.
2. The user types it into the desktop app.
3. The desktop joins mailbox `RRRR`. There's no join MAC, because there's no shared secret yet. The server tells it the home id.
4. SPAKE2 runs through the mailbox, unsealed:
   1. Desktop → stick: `pA`.
   2. Stick → desktop: `pB`.
   3. Desktop → stick: `cA`. The stick checks it.
   4. Stick → desktop: `cB`, sent only after `cA` checks out. The desktop checks it.

   A failed check on either side is one failed attempt (§5). The messages differ (§5): a failed `cB` on the desktop means "possible interception", not "wrong code".

   **These messages are public by design.** SPAKE2 is built so that an observer of `pA`, `pB`, `cA` and `cB`, including the signalling server, learns nothing that allows an offline guess of the code. Nothing secret goes through the mailbox before both confirmations pass.
5. After confirmation, mailbox messages are sealed under the SPAKE2 pairing envelope (§4.5). The stick sends its static public key `K`. The desktop sends its static public key and device name. The desktop now knows `K`, which IK needs, and both sides can compute the full `TH`.
6. The desktop opens **Noise IKpsk2** with `psk = boot_psk`, method `spake2` (§4.5). Success proves both static keys belong to the SPAKE2 session.
7. The stick asks for approval on its approval overlay (§4.7).
8. They derive and save the long-term `pair_psk` inside the IKpsk2 session and run the pair-confirm (§4.5). The stick sets up the signalling slot (§4.6). The code and `RRRR` are cancelled.

### 4.5 Key derivation and domain separation (unified in v0.4)

Two rules, unchanged from v0.3:
1. A shared secret from SPAKE2, a QR code or USB is **never** fed straight into Noise.
2. **The Noise handshake hash `h` and the transcript hashes `TH` and `TH0` are not secret.** An observer may be able to reconstruct them. They are used only as **salt, context or binding**, never as key material by themselves.

**Encodings:**
- `HKDF(ikm, salt, info, L)` is HKDF-SHA256 (RFC 5869). `L` is 32 bytes unless stated. `salt = empty` means a zero-length salt.
- `HMAC` is HMAC-SHA256.
- Labels are ASCII, with no terminator.
- `enc(x)` = `u16be(length of x) || x`.
- Static keys: raw 32-byte X25519 public keys. `home_id`: 16 raw bytes. Route: for `spake2`, the routing ID as 4 ASCII digits; for `qr`, the 8-byte mailbox id; zero length when there is none. `key_epoch`: `u32be`, 1 at first pairing. Serial: the 18 ASCII bytes of §4.B.4.
- `h` is the Noise handshake hash at the end of the method's first handshake (32 bytes).
- Initiator and responder are the roles in that first handshake: phone/stick (C), desktop/stick (D), stick/KVM (B), stick 2/primary (A, deferred).

**Transcript hash:**
```
TH = SHA-256( enc("sl1/th/v1") || enc(method) || enc(route) || enc(home_id)
              || enc(extra) || initiator_static || responder_static )
```

`enc()` is applied **once**, in the formula above. The table gives the raw `extra` bytes. (v0.4's table wrote `enc(serial)`, which encoded the serial twice; AI KVM item 3.)

| Method | `method` | `route` | `home_id` | `extra` (raw bytes) | `initiator_static` |
|---|---|---|---|---|---|
| C, QR | `qr` | mailbox id (8 B) | home id | empty | **32 zero bytes** (see below) |
| D, split code | `spake2` | RRRR | home id | `enc(idA) || enc(idB) || enc(pA) || enc(pB)` (a concatenation, then encoded once more as a whole by the formula) | desktop static |
| B, KVM | `kvm-usb` | empty | empty (intentional, §4.B.4) | `serial` | stick static |
| A, USB (deferred) | `usb-invite` | defined when §4.A resumes | home id | empty | stick 2 static |
| Rotation (§6) | `rekey` | empty | home id, empty for the KVM | `u32be(new key_epoch)` | initiator's static |

**QR `TH` without the phone's key (X1, changed in v0.5).** In v0.4 the stick had to read IKpsk2 message 1 to learn the phone's static key before it could compute `boot_psk`. Noise allows that, but whether the Python, Swift, Kotlin and WASM Noise libraries let a responder set the PSK late is unverified. So for `qr` only, the `initiator_static` field in `TH` is 32 zero bytes. The stick can then compute `TH` and `boot_psk` before the handshake starts, and standard libraries work. The phone's static key is still bound: by `h` in the `pair_psk` salt, and by `initiator_static` in the `pair_psk` info, which always uses the real key. StickLLM's v0.5 re-review confirms this loses no binding.

**Key checks (v0.6, StickLLM's notes):**
- `initiator_static` in the `pair_psk` info (and `responder_static`) is always taken from **Noise's authenticated remote static key**, never from an app payload or a mailbox message.
- 32 zero bytes is also the encoding of a low-order X25519 point. Every implementation **rejects** an all-zero or low-order remote static key and an all-zero DH output, and aborts the handshake. The zero placeholder exists only inside the `TH` input and is never passed around or used as a key. (pyca/cryptography already raises an error for these; the vectors check three such keys.)

Method D needs a hash before the static keys are known, for its envelope:
```
TH0 = SHA-256( enc("sl1/th0/v1") || enc("spake2") || enc(RRRR) || enc(home_id)
               || enc(idA) || enc(idB) || enc(pA) || enc(pB) )
```

**Bootstrap PSK (one formula, first IKpsk2 only):**
```
boot_psk = HKDF(ikm = method_secret, salt = TH, info = "sl1/" || method || "-boot")
```

| Method | `method_secret` | Label |
|---|---|---|
| `qr` | `invite_secret` | `sl1/qr-boot` |
| `spake2` | `Ke` | `sl1/spake2-boot` |
| `usb-invite` (deferred) | `invite_secret` | `sl1/usb-invite-boot` |
| `kvm-usb` | none. No boot PSK; secrecy comes from the XX DH keys. | — |

This replaces v0.3's §4.C step 4 (no salt) and §4.D steps 4–6 (`boot_key`, `"sl1/boot-psk"`), which didn't match §4.5.

**Pairing envelopes** (seal mailbox messages during pairing, §4.6):
```
env_qr     = HKDF(ikm = invite_secret, salt = empty, info = "sl1/qr-env" || enc(mailbox id) || home_id)
env_spake2 = HKDF(ikm = Ke,            salt = TH0,   info = "sl1/spake2-env")
```
- ChaCha20-Poly1305 with a 12-byte random nonce. AAD = `enc(route) || mailbox id || direction`, where `route` is as in `TH` (the mailbox id for `qr`, `RRRR` for `spake2`) and direction is one byte: 0x01 joiner to stick, 0x02 stick to joiner.
- Method B has no envelope. It runs over USB, inside XX.

**Long-term pair PSK, derived inside the authenticated encrypted session:**
1. After the first Noise handshake (IKpsk2, or XX for the KVM) completes and the user has approved, each side sends a fresh **32-byte random contribution**, `r_i` from the initiator and `r_r` from the responder, as Noise transport messages. So they are encrypted and authenticated.
2. Both compute:
```
pair_psk = HKDF(ikm  = r_i || r_r || prior,
                salt = h || TH,
                info = "sl1/pair-psk/v1" || initiator_static || responder_static || u32be(key_epoch))
```
   `prior` is `boot_psk` for `qr`, `spake2` and `usb-invite`; empty for `kvm-usb`; the old `pair_psk` for `rekey`.
3. **Pair-confirm**, with role-specific labels so the two messages are never the same bytes:
```
kc        = HKDF(ikm = pair_psk, salt = empty, info = "sl1/pair-confirm")
initiator sends HMAC(kc, "sl1/pair-confirm/i" || h)
responder sends HMAC(kc, "sl1/pair-confirm/r" || h)
```
   Each side checks the other's before saving. If either check fails, nothing is stored.

So `pair_psk` comes from secrets only the two devices ever saw in plaintext, and it is bound to the authenticated handshake, both identities and the key epoch. If a library exposes a proper Noise channel-binding or exporter secret, it may be added to `ikm`, but never used in place of `r_i || r_r`.

- `pair_psk` is unique per pair and per key epoch. It's stored in the registry and used for all later IKpsk2 sessions.
- Each label is used for exactly one purpose. No key serves two roles.

**Test vectors, in the repo before any device implements a method:**
- **KVM vectors (authoritative, v0.5; unchanged in v0.6): `vectors/kvm_vectors.py` and `vectors/kvm-usb-v1.json`**, with `vectors/README.md`. Generated from the formulas in this version, starting from AI KVM's candidate script. They cover: the serial from a MAC, the prologue, a full XX run with fixed keys and empty payloads, `h`, the commitment, the code (including one with a leading zero, and the reduction at 0, 999,999, 1,000,000 and 2^64−1), `TH` with `extra` encoded once, `pair_psk`, `kc` and both pair-confirms, `P_slot`, `jk` and `env_k`, all 11 inner messages encrypted, and every HID frame of the run. Two serials are included. `python3 kvm_vectors.py --check` recomputes everything and compares it with the JSON. The handshake and transport messages are cross-checked against the `noiseprotocol` library when it is installed. Where these vectors and the prose disagree, fix one of them before implementing.
- **New in v0.6: `vectors/kvm-usb-v1-extra.json`** (AI KVM's notes). A second key set (serial `AIKVM-A0B1C2D3E4F5`), so the transport messages differ from the first file. Full runs with the pad-added prologues 0F0D:0092 and 045E:028E. A prologue mismatch that fails XX msg 2. The full stop-and-wait SET/GET sequence of one run (32 transfers) with ACK frames. The receiver seq rule, including the 0xFE → 0x00 wrap. A lost GET, a duplicate SET and an out-of-sequence frame. ABORT frames. A wrong `Nb` and a wrong `confirm_i`, with the encrypted 0x7F aborts that follow. An unknown abort reason, and low-order keys that must be rejected. `kvm-usb-v1.json` itself is unchanged, so AI KVM's independent check of it still applies.
- **New in v0.6: `vectors/qr-v1.json`** (StickLLM's note). The `qr` `TH` with the 32-zero-byte `initiator_static` field, `boot_psk`, `jk_qr`, the join MAC and `env_qr`. Generated by our script only; no independent check yet.
- Still to add: RFC 9382 Appendix B, and `sl1` vectors for `pw → w`, the confirmation AAD, `cA` and `cB`, `TH0`, `TH` for `spake2`, the `spake2` `boot_psk` and `env_spake2`.
- Noise IKpsk2-SHA256 with fixed keys.
- `rekey` vectors, including a same-epoch `rekey` with a different key replacing the pending entry (§6 rule (b), v0.7).
- QR `pair_psk` and confirm vectors (StickLLM's v0.6 note).
- The same vectors pass in Python, Rust, the WASM and mobile bindings, and C/mbedTLS.

### 4.6 Pairing mailboxes, routing IDs and signalling slots (new in v0.4)

This ties pairing to SIGNALLING-PLAN.md: one Durable Object per home, up to 16 slots, `jk = HKDF(P, "sl1/join")` and `env_k = HKDF(P, "sl1/env")`. The message names below are proposals for the signalling team.

**Routing IDs (split-code pairing only):**
- QR pairing doesn't use a routing ID (X2). It uses the server's 8-byte mailbox id, which is not typed. So only Method D draws from the 10,000 `RRRR` values.
- **The server assigns them,** not the stick. `RRRR` is 4 digits, only 10,000 values across all homes, so the server must keep each one unique while it's live.
- A single global router maps each live `RRRR` to a home and mailbox. It could be one Durable Object or a directory table with a unique constraint; the signalling team chooses. This is new to SIGNALLING-PLAN.md.
- The server picks uniformly at random among values that are not live, were not released in the last 10 minutes, and were not used by this home in the last 24 hours. The 10-minute hold (proposed) stops a late joiner from landing in another home's new mailbox and cancelling its code.
- If no value is free, the server answers `err:busy` and the stick says "try again".
- A routing ID is released on success, failure, cancel or expiry.
- Capacity: with 60 s live plus the 10-minute hold, about 900 new codes per minute across all homes. Beyond that, `RRRR` would need more digits, which changes the code format.

**Messages** (extend SIGNALLING-PLAN.md §2):
```
stick→S {"t":"pair.open","id":7,"m":"qr"|"code","exp":60,"jk":"<32B, qr only>"}
S→stick {"t":"pair.ok","id":7,"rid":"4821 (code only)","mbx":"<8B>"}
C→S     {"t":"pair.join","id":1,"rid":"4821"}               (code)
C→S     {"t":"pair.join","id":1,"mbx":"<8B>","mac":"<32B>"} (qr)
S→C     {"t":"pair.joined","id":1,"conn":"c5","home":"<16B>"}
S→stick {"t":"peer","conn":"c5","mbx":"<8B>","state":"join"}
either  {"t":"pmsg","to"|"from":"…","body":"<bytes>"}
stick→S {"t":"pair.close","id":8,"mbx":"<8B>","why":"done|fail|cancel"}
```
- Joiners have no device credential. `pair.join` takes the place of `hello`, like `join` for phones today.
- QR join tag: `jk_qr = HKDF(ikm = invite_secret, salt = empty, info = "sl1/qr-join")`. The join MAC is `HMAC(jk_qr, "sl1/qr-join-mac" || n || mailbox id)`, where `n` is the server nonce from `welcome`. The server checks it the same way it checks slot joins.

**What is sealed when:**

| Phase | QR (`qr`) | Split code (`code`) |
|---|---|---|
| Join | Join MAC with `jk_qr`. A bad MAC drops the connection; it isn't an attempt. | No MAC. |
| Before confirmation | Everything sealed under `env_qr`. The IKpsk2 messages travel inside. | Only `pA`, `pB`, `cA`, `cB`, in clear. Public by design; nothing secret. |
| After confirmation | `env_qr` | `env_spake2` |

**From mailbox to slot, after a successful pairing:**
- The stick picks a new random 8-byte slot id and derives `P_slot = HKDF(ikm = pair_psk, salt = empty, info = "sl1/slot-secret")`.
- It sends `slot.add` with `jk = HKDF(ikm = P_slot, salt = empty, info = "sl1/join")`. Later envelopes use `env_k = HKDF(ikm = P_slot, salt = empty, info = "sl1/env")`. These are SIGNALLING-PLAN.md's formulas with `P = P_slot`. SIGNALLING-PLAN.md was updated in v0.5 to say so (X5).
- The stick sends the home id and slot id to the peer inside the Noise session. The KVM gets them over USB (§4.B.5).
- The stick sends `pair.close`. The mailbox closes and the routing ID, if any, is released.
- On rotation, the new `pair_psk` gives a new `P_slot` and `jk`. The stick replaces the slot's join key when the old key is retired (§6).

### 4.7 Approval overlay and AI KVM input (new in v0.5, StickLLM N1, AI KVM item 4)

**Who owns it.** A native, **root-owned** program, `sticklink-approve`, started for sticklinkd (directly, or through a small root helper called via sudoers, as the existing helpers are). It is not part of Chromium, not reachable over HTTP, and not startable or readable by the kiosk user.

**How it draws (pinned in v0.6, StickLLM R1): its own virtual terminal, never a cage client.**
- Facts from StickLLM's reading of cage's source: cage has **no layer-shell**. A second window would show, but cage gives every client on its socket `wlr_screencopy_manager_v1` (0.1.4, 0.2.0, 0.3.0), virtual keyboard and pointer (0.2.0+) and `foreign_toplevel_manager_v1` (0.3.0+), whose activate and close requests could cover or close the overlay. Any kiosk-user process could then read the QR or code off the screen. A launcher client that switches between Chromium and the overlay has the same problem.
- How the stick runs cage today: `stickllm-kiosk` launches `cage -s -- <browser> … --ozone-platform=wayland` as `KIOSK_USER` via `runuser`, with `LIBSEAT_BACKEND=seatd` and `WLR_BACKENDS=drm,libinput`. `-s` enables VT switching. The stick builds from Debian bookworm, so it ships cage 0.1.4.
- So the overlay:
  1. switches to its own VT (`chvt` / `VT_ACTIVATE`, then waits until the VT is active);
  2. opens the DRM device and draws with KMS. A dumb buffer is enough;
  3. takes `EVIOCGRAB` on every evdev device (below);
  4. on close, clears its buffer, releases the grabs and the DRM device, and switches back to cage's VT.
- It is **never a Wayland client of cage** and never connects to cage's socket.
- **A small native binary (v0.7, StickLLM's note).** The stick has no python-evdev, so the overlay is a small native program using libdrm and the evdev ioctls, or StickLLM adds a package. libdrm comes in through wlroots; that is not checked on a built image.
- Why it can take the display (StickLLM's reading of seatd and Linux 6.1): on a VT release, seatd calls `drm_drop_master` on cage's DRM file descriptor and revokes cage's input devices before acknowledging the switch. So cage doesn't hold DRM master when the overlay opens the device, and root may take it.
- If its VT stops being the active VT while the prompt is open, the overlay treats that as Reject and ends the attempt (fail closed). It may use `VT_PROCESS` mode so that switch requests go through it.
- **Required hardware test (unverified):** that seatd and cage 0.1.4 release DRM master on the VT switch and restore it cleanly on the way back, on both the iGPU and the NVIDIA paths that `stickllm-kiosk` handles. The same test checks that Chromium recovers, and that a screencopy client in the kiosk session can't capture the overlay. If the test fails, this section is revised before Methods B–D ship. Approval never falls back to the kiosk.

**What the kiosk may still do.** The kiosk web UI may **start** a pairing ("Add device", "Pair a desktop", "Pair an AI KVM"). Starting is not a security gate, because nothing is saved without the overlay's Allow. The kiosk then shows "Look at the approval screen". It never shows a pairing secret.

**What only the overlay shows.** The QR code, the `RRRR-SSSSSS` code, the KVM check code, and the Allow/Reject prompt. These are never served through `stickllm-gateway`, so no local process or paired browser can read them.

**How input is read.**
- The overlay reads input directly from evdev (`/dev/input/event*`). While it is open, it takes an exclusive grab (`EVIOCGRAB`) on every input device, so Chromium and every other process get no input.
- It discards every event from a device classed as AI KVM (below), and from virtual devices (under `/devices/virtual`, including `uinput`). Only keyboard, touch and pointer events from physical, non-KVM devices count.
- **Allow** means entering a fresh 4-digit number that the overlay shows, on that same overlay: typed and confirmed with Enter, or tapped on an on-screen keypad whose keys are in a random order each time. This stops a device that types blindly (a "BadUSB" stick, or a KVM that escaped classification) from approving. It doesn't stop a device that can also see the screen.
- **Reject** is Esc or a Reject button. Three wrong entries count as Reject. The 60 s expiry (§5) still applies.
- When the overlay closes, the grabs are released.

**Which devices count as AI KVM (revised in v0.6, StickLLM R4, AI KVM item 2).** v0.5 failed open: on a computer with no pin yet, or on a new port, a KVM in BIOS or gamepad mode escaped every rule. An AI KVM sees the HDMI output, so it could read the 4-digit number and type it. Over-inclusive classification is fail-safe: it only discards input. A device counts as AI KVM if **any** of these hold:
1. **`AIKVM-` serial (primary rule, any port, any computer).** Its USB serial starts with `AIKVM-` (§4.B.4). Per AI KVM's corrected reading of the firmware, the serial is at index 3 in every mode with strings:

   | USB mode | VID:PID | Serial | Notes |
   |---|---|---|---|
   | Normal composite | 303A:4012 | Yes | Pairing available |
   | Legacy BIOS | 303A:4012 | Yes (same string table) | Keyboard only; no pairing |
   | HID + HORI pad added | 0F0D:0092 | Yes, once the firmware sets it | Pairing available. Switch retest pending (§4.B.7) |
   | HID + XInput pad added | 045E:028E | Yes, once the firmware sets it | Pairing available. Xbox retest pending (§4.B.7) |
   | Gamepad-only HORI / XInput | 0F0D:0092 / 045E:028E | Yes, once the firmware sets it (AI KVM: "the HORI and XInput modes carry index 3"; not confirmed separately for the gamepad-only modes, **unverified**) | No pairing |
   | XID (original Xbox) | 045E:0289 | **None** (no string descriptors) | No pairing. Accepted risk, below |

2. **Pinned port.** It is on a USB device port pinned to a paired AI KVM on this computer, or on a hub below that port. After a KVM pairing, StickLLM stores in that KVM's registry record a list of `{computer id, port}`:
   - `port` is the `ID_PATH` of the **`usb_device`** node, with the `:1.N` interface suffix stripped. A hidraw or input node's path includes the interface, which differs in BIOS mode (interface 0 only). Every device below that path matches.
   - `computer id` is the existing DMI digest (`machine_id` in `stickllm_usb_settings.py`). Its fallback, `stickllm-unknown-computer`, makes every DMI-less PC share one id. That errs toward excluding more input, which is safe.
   - `ID_PATH` can change with a dock or a firmware change. Re-pinning on a serial sighting covers that in every mode except XID.
3. Its VID:PID is on the AI KVM list (303A:4012 today, plus any PID AI KVM adds). 303A:4012 is a generic Espressif default, so other Espressif devices may be caught too; that only discards their input.
4. It exposes the 0xFF00 pairing collection.
5. During a KVM pairing: it is on the port of the device being paired.

On another computer the stick has no pin yet; rule 1 covers that. **A new port is pinned only after the real KVM proves its key (v0.7, StickLLM's note).** That means an authenticated contact against the stored `peer_static`: a successful IKpsk2 session with that KVM while it is on the new port, or a new USB pairing. Until then, rule 1 still discards the input of anything with an `AIKVM-` serial, but the port isn't pinned. Why: the serial is the public MAC, so a device faking a paired serial could otherwise pin the user's keyboard port (a denial of service). How sticklinkd ties a network session to the USB port is for StickLLM to define. If it can't, it asks the user on the overlay before pinning. The user is told about every new pin.

**New devices (v0.6, fail closed; T0 defined in v0.7, AI KVM's note).**
- **T0** is the moment sticklinkd takes the **input-device snapshot**: at the start of the attempt, when the user starts a pairing on the stick, before any pairing message is sent or accepted. There is exactly one snapshot per attempt.
- **Device identity** in the snapshot: the sysfs path of the `usb_device` plus VID:PID plus serial for USB devices, or the Bluetooth address for Bluetooth devices. For built-in devices (for example a laptop keyboard on i8042/serio, or internal I2C-HID) it is the sysfs device path. The evdev node number is not stable and is never used.
- **Every input device not in the T0 snapshot is ignored.** Its events never count, whatever it claims to be. That includes anything plugged in while the overlay is open.
- **A device that disconnects and reconnects after T0 counts as new.** That fails closed.
- **Approval is refused while any XID-class device (045E:0289) or other unclassified HID device that isn't in the T0 snapshot is connected.** The overlay shows only Reject and says "Unplug the new device, or start again". It adds: "A Bluetooth keyboard that went to sleep, or a USB keyboard behind a hub that reconnected, counts as new". A mode change re-enumerates the KVM, so a KVM that switches mode during a pairing shows up here.
- Trade-off: a keyboard plugged in or reconnected after T0 can't approve that pairing. The user connects it first, or starts again. A laptop's built-in keyboard is present at T0 and matches none of rules 1–5, so it can approve.

**Limits (documented):**
- **XID mode (accepted risk).** 045E:0289 has no strings, so a KVM in XID mode on an unpinned port can't be recognised. It is a gamepad-only mode, and the overlay counts only keyboard, touch and pointer events, never gamepad events. If it isn't in the T0 snapshot, approval is refused while it is connected. Stated in §8b (g).
- A malicious USB device can fake VID, PID and serial, or show none. Rules 1, 3 and 4 then fail, and rule 2 only helps on a pinned port.
- A device on another port that was connected before the pairing started, isn't classified, and can both type and see the screen (for example a second, unknown KVM with other firmware) could approve. This is accepted. The overlay's random number and keypad make blind injection fail.

**USB IDs (note, not a rule).** AI KVM uses Espressif's VID with an automatic PID. Nink could apply for a free PID from Espressif's allocation for ESP32 products, which would give the KVM its own ID. The terms of that programme are **unverified**. A purchased USB-IF VID is the other option. Neither changes the pinned-port rule.

## 5. Brute-force protection, rate limits and pairing denial-of-service

**A connection is not an attempt.** Joining a mailbox, or opening a socket with a routing ID, is only a **connection**.
- **An unauthenticated connection never uses up or invalidates an invitation.** This replaced v0.2's "one joiner per routing ID" rule, which let an attacker join first and lock out the real desktop.
- Each mailbox accepts up to **4 concurrent connections**. A connection that sends no valid pairing message within **5 s**, or sends malformed data, is dropped. The stick handles attempts one at a time.

**One failed attempt per code, invitation or window:**

| Method | One failed attempt is | Result |
|---|---|---|
| D, split code | `cA` or `cB` fails | Code and `RRRR` cancelled |
| C, QR | After a valid join MAC: the IKpsk2 handshake fails, the pair-confirm fails, or the user presses Reject | Invitation and mailbox cancelled |
| A, USB (deferred) | The first IKpsk2 handshake fails, the pair-confirm fails, or Reject | Invitation cancelled in the primary's registry and on the server. The file is dead even if it's still on the flash. |
| B, KVM | Commitment check fails, XX fails, either side rejects the code, the pair-confirm fails, or any protocol error (§4.B.5) | Window closed. A new trigger is needed. |

After a failure, the stick shows "A wrong code was tried" (or "Pairing failed"), and the owner starts again. In Method D the two sides say different things (X4):
- The stick's `cA` check fails: "A wrong code was tried."
- The desktop's `cB` check fails, after the stick accepted `cA`: "**Possible interception.** Pairing stopped. Start again on the stick." A wrong code can't cause this, because the stick only sends `cB` after `cA` checks out.

**Accepted risk: a stranger who guesses a live routing ID can cancel the owner's code.** Method D has no join MAC, so anyone who guesses a live `RRRR` can join and send a wrong SPAKE2 message. That cancels the code. The stranger can't learn the code. This is the cost of an online PAKE with a short routing ID, and v0.4 accepts it. For QR, a stranger without the QR code fails the join MAC, so can't cancel. (If the optional code next to the QR, §11, is adopted, the same risk applies to that screen.)

**Expiry:** 60 s for QR, split codes and the KVM window. USB invitation files expire after 1 hour, can be regenerated by hand and work once (when §4.A resumes).

**Rate limits**, so an attacker can't request thousands of new attempts:
- Codes can only be started by the owner on the stick (the kiosk starts them, the overlay shows them), and KVM windows only by the KVM trigger. An outsider can't request a code.
- Per home: at most 5 pairing sessions per 10 minutes and 20 per day. Once that's hit, a 1-hour lockout shows on the stick.
- At the rendezvous server: at most 10 mailbox connections per IP per minute, and at most 100 failed routing-ID lookups per IP per hour, after which that IP is blocked for an hour. Unknown routing IDs are refused without saying whether they exist.
- So the odds of guessing a code are 1 in a million per live code, with at most 20 tries a day per home, and only while the owner is actively pairing.

## 6. Lifecycle (implemented from the start)

- **Revocation:** any admin device (the stick, or a client marked admin) can revoke a peer. The stick deletes the registry record, sends `slot.del` to signalling, and has signalling withdraw that device's relay permit. Revocation takes effect at once on the paired devices, and on the relay through **pull on change**: signalling bumps a revocation counter, and the sidecar pulls a fresh allowlist straight away. **Fallback: a 15-minute allowlist TTL** (decided v0.3), so a missed change can last at most 15 minutes. While the stick's settings partition is locked, the stick can't process revocations (§3). **On every unlock, before serving, the stick fetches its home's revoked-peer set and deletes any matching local record. Remove-only: the server can delete records, never add them** (v0.9, StickLLM R6; the flash-rollback defence and its gaps are in §3). The stick fetches the set over its authenticated session and acts only on entries that match peers already in its registry. A failed fetch never blocks a local unlock; this is the offline gap R6 already documents (§3).
- **Lost client device:** revoke it from the stick. Nothing else is needed, because its keys only work against our pins.
- **Lost or dead stick:** the stick's private key is never copied, so there's no recovery of that identity. Pair a new or reflashed stick and re-pair clients. **No recovery token at launch** (decided v0.3).
- **Multiple clients:** up to 16 slots per home and 8 at once (from SIGNALLING-PLAN.md). Each client has its own `pair_psk`, pin and slot.
- **Key rotation:**
  - The rotating device generates its new static key itself, on the device, and never exports it. For the KVM, the KVM generates it.
  - It sends `rekey{new_static, key_epoch+1}` inside an authenticated IKpsk2 session under the old key. Both derive a new `pair_psk` inside that session with method `rekey` (§4.5).
  - Both sides keep `{old, new}` pin and PSK, keyed by `key_epoch`, until the first IKpsk2 session under the new key succeeds. A reboot can then never leave a half-updated pin or PSK. Each registry write is atomic (one NVS blob on the KVM, an atomic file replace on the stick).
  - **When the two sides' writes diverge (v0.6, AI KVM item 3).** Each side writes its `{old, new}` record separately, so a reboot or unplug between the two writes can leave one side with `new` and the other without it. Two rules:
    - (a) **Fall back to old.** The initiator (the KVM, for KVM peers) tries IKpsk2 under `new` for a peer whose record has `new`. If that handshake fails, it tries again under `old`, and it **never drops `old` because of such a failure**. Only a successful session under `new` (step 3 below) or the end of the overlap removes `old`.
    - (b) **A repeated `rekey` replaces the pending entry (changed in v0.7, AI KVM item 2).** A `rekey` with the same `key_epoch` as a pending entry **replaces** that entry, with the new PSK from the new session. That holds whether `new_static` is the same or different; it is never rejected. Why this is safe: `rekey` only arrives inside an authenticated IKpsk2 session under `old`, so only the real peer can send it. v0.6 refused a different `new_static`, which could strand a peer.
    - (c) **Save before send, MANDATORY for every rotating side (v0.7, AI KVM item 2).** Each rotating side, KVM and stick alike, **must** save its new key durably as `pending` before it sends any `rekey`, and must reuse that saved key for every `rekey` at that epoch. Rule (b) is a second safeguard, not a replacement.
    - (d) **Receive side of `rekey` (v0.8, AI KVM's nit).** A device accepts `rekey{new_static, key_epoch}` only inside a session authenticated under the record's current key (or, during an overlap, its `old` key), and only with `key_epoch == cur_epoch + 1`, where `cur_epoch` is the epoch of that current/old key. It **refuses** `rekey` inside a session under `new`, and any other epoch. Refusing changes no record.
    - So after a divergent crash, the next session under `old` succeeds, and the rotating side re-runs `rekey` for that peer. A re-run **replaces** the pending entry on both sides; it never adds one.
    - A peer that diverged and then stayed offline past the end of the overlap **must re-pair**. `old` is gone by then on the rotating side (AI KVM's note).
  - **For a routine rotation only**, the old key keeps working for up to 7 days so offline peers can catch up. That 7-day overlap starts only once the device's clock has been set from the network (SNTP, or `welcome.now` from signalling). Otherwise it is counted as time online. **On the KVM, see the RTC rule below (v0.7):** there the overlap is counted only by its online-time counter.
  - **RTC and the KVM's clock (AI KVM's findings, updated in v0.7 after reading `components/kvm_rtc`).**
    - The NANO has a header for a rechargeable RTC battery, but no battery is documented as fitted. Whether that header feeds the P4's low-power domain is unverified. The P4-ETH lists no RTC battery; its schematic wasn't checked.
    - `components/kvm_rtc` drives an **optional external, battery-backed I2C RTC chip**. It is not the P4's internal RTC and has nothing to do with the NANO header. Supported chips:
      - DS3231 at 0x68: auto-detected, and per the code comments the only one run on hardware;
      - PCF8563/BM8563 at 0x51: auto-detected;
      - PCF85063 and PCF8523: only when named in settings.
    - At boot, if the chip's time is valid and the system clock is unset, it sets the clock from the chip. No network is involved. "Valid" means `time()` ≥ 2025-01-01.
    - Separately, `kvm_sched` treats "anything after 2020" as set, and starts plain, **unauthenticated** SNTP.
    - The comments also say a browser sign-in sets the clock; AI KVM couldn't find that code (**unverified**, §4.B.7).
    - So the KVM **can** keep a clock across power loss when an RTC module is fitted, and can't without one.
    - **None of these time sources is trusted.** A wrong chip time or a spoofed SNTP reply could jump the clock forward. On the KVM, therefore:
      - the KVM persists an "online time" counter in NVS about once an hour;
      - **the 7-day overlap ends only once that counter reaches 7 days**;
      - wall-clock time may only lengthen the overlap, never shorten it;
      - the pairing code never treats the firmware's `time()` ≥ 2025 (or 2020) check as "set from the network".
    - A power loss can lose up to an hour of count, which only lengthens the overlap.
  - **Rotating the KVM's own identity key, atomically (new in v0.5, AI KVM item 5).** The KVM keeps its identity in one NVS blob `sl1id` = `{cur_epoch, cur_priv, pending_epoch, pending_priv}`. Steps:
    1. Generate the new key on the device and write it as `pending` in one write of `sl1id`. `cur` stays in use.
    2. For each paired peer, run `rekey` under the old key and write that peer's `sl1reg` record with `{old, new}` pin and PSK in one write.
    3. When a peer's first IKpsk2 session under the new key succeeds, rewrite its record without `old`.
    4. When every active peer has moved, or the overlap ends, promote: one write of `sl1id` with `cur = pending` and `pending` empty.
    5. A reboot at any step leaves a state the KVM can continue from: `pending` present means a rotation is in progress, and each peer record says which keys it accepts.
    - Step 1 is the mandatory save-before-send of rule (c): no `rekey` is sent before `pending` is in `sl1id`.
    - A compromised key skips the overlap: the KVM promotes at once and drops `old` everywhere, as for any compromised key above.
    - `sl1id` is about 72 B plus NVS overhead, well inside one NVS page (AI KVM's v0.5 re-review). So the multi-page power-loss question doesn't arise. Keep it within one page if it ever grows.
  - **Rotating the stick's own identity key (new in v0.7, AI KVM item 2).** The stick's identity key is sealed in the settings partition under `HKDF(registry_key, salt = empty, info = "sl1/identity")` (§3). Proposal, StickLLM to confirm: it is kept as one sealed file `{cur_epoch, cur_priv, pending_epoch, pending_priv}`, written only by atomic file replace (write, fsync, rename, fsync the directory), like the KVM's `sl1id`. Steps:
    1. Generate the new key on the stick and write it as `pending` in one atomic replace. `cur` stays in use. **No `rekey` is sent before this write has completed** (rule (c)).
    2. For each paired peer, at its next IKpsk2 session under the old key, send `rekey{new_static, key_epoch+1}` using the saved `pending` key. Write that peer's registry record with `{old, new}` pin and PSK in one atomic replace.
    3. When a peer's first IKpsk2 session under the new key succeeds, rewrite its record without `old`. Where the stick is the responder (for example to the KVM), it accepts both its `cur` and `pending` keys for a peer whose record has both, so the peer's fall-back to `old` in rule (a) works.
    4. When every active peer has moved, or the overlap ends, promote: one atomic replace with `cur = pending` and `pending` empty. The stick then updates the signalling slot's join key (§4.6).
    5. A reboot at any step leaves a state the stick can continue from: `pending` present means a rotation is in progress, and each peer record says which keys it accepts.
    - A compromised key skips the overlap, as for the KVM.
    - While the settings partition is locked, the stick can't rotate (§3).
  - **A revoked or compromised key is cut off immediately:** any revocation, or a rotation flagged `compromised`, deletes the old pin and `pair_psk` at once, skips the overlap, and bumps the revocation counter. A peer that missed the rotation must re-pair.
  - Clients rotate their relay key separately and more often, which is option A in SIGNALLING-PLAN.md.
- **Allowlist sync:** every pairing, revocation and rotation updates the signalling directory, which then updates the signed relay allowlist. The sidecar's last-known-good list keeps existing pairs working if Cloudflare is briefly down.

## 7. Work split (rough, after Nink approves)

- **Signalling server (sticklink):** a remove-only revoked-peer set per home that the stick fetches on every unlock (§6, v0.9). The stick fetches the set over its authenticated session and acts only on entries that match peers already in its registry. A failed fetch never blocks a local unlock; this is the offline gap R6 already documents. Also: pairing mailboxes, with a server-assigned routing ID for split codes (unique while live) and the mailbox id for QR; the global router; up to 4 concurrent connections per mailbox (no one-joiner rule); the QR join MAC check; the `pair.*` messages; rate limits; the revocation counter and pull-on-change.
- **StickLLM:** prerequisites P1–P3 (§0), including the PIN minimum and Argon2id parameters; the stick-resident `registry_key` and the identity key in the settings partition (§3); Methods C and D; the native approval overlay on its own VT with KMS and evdev, the VT-switch hardware test, KVM classification, new-device refusal and port pinning (§4.7); the recovery wrap, the single stick recovery phrase and its labelling, the checked keyslot procedure with the pinned `luksAddKey` command and the v0.8 phrase-change order, the pinned sealed-file formats with `luks_slot` and whole-header AD, the pinned LUKS slot map, the `.lock` and `.<target>.tmp.<hex>` names, directory fsyncs including `records/`, the 0700 directory and writer lock (§3), crash recovery at every unlock for the phrase and PIN pairs (§0 P1), the revoked-peer pull on every unlock before serving and the documented flash-rollback gaps (§3, §6), the optional `registry_gen` counter, the pinned phrase format and removing `recovery.sha256` (§0 P1, §3), and the vault's recovery-slot newline bug; the stick's own key rotation with save-before-send (§6); the T0 device snapshot (§4.7); the SPAKE2 wrapper and bindings; test vectors; revocation and rotation UI; the StickLLM side of Method B (hidraw, the `usb_id` udev rule, stop-and-wait framing, state machine, `vectors/`); no core dumps for sticklinkd (§4.D). Later, the §4.A blockers.
- **AI KVM:** the per-device USB serial (§4.B.4); the top-level vendor-defined HID collection, stop-and-wait framing and ABORT frames (§4.B.3); the Switch and Xbox retest with the serial; the 5 s ABORT period; a pairing trigger that doesn't re-enumerate (§4.B.2); the online-time-only overlap (§6); the pairing trigger and display per §8b (b); Noise XX with the commit-then-reveal code and the state machine (§4.B.5); the certificate fingerprint display; the `sl1reg` registry and `sl1id`; atomic writes and rotation, including the fall-back-to-old and repeated-`rekey` rules (§6); passing `vectors/`; the security staging in §4.B.6, with NVS migration and the cable bootloader step; the checks in §4.B.7; the hardware measurements in §10.
- **Mobile and desktop apps:** Methods C and D, the SPAKE2 bindings, plus the keystore.

## 8. Decisions (settled by Nink, 2026-10-29 11:23 AM ET)

1. KVM check code (§4.B): **6 digits**, if practical to display and verify. Otherwise use the documented physical fallback.
2. Lost-stick recovery token (§6): **no at launch**.
3. Relay revocation (§6): **pull on change, with a 15-minute TTL as fallback**.
4. SPAKE2 or CPace (§4.D): **SPAKE2 (RFC 9382)**, subject to finding a validated library for every client platform.
5. USB invitation expiry (§4.A): **1 hour, with manual regeneration**.

**How v0.4 affects them:**
- Decision 1 depends on §8b (b). On a stock board with no display and no second LAN device, the code can't be shown, and the physical fallback needs an added button (§4.B.2).
- Decision 4: SPAKE2 is kept, now pinned to the P-256 suite. Its condition isn't met yet: no audited SPAKE2 library was found on any platform. See §8b (a).
- Decision 5 applies when §4.A resumes. See §8b (c).

**Knock-on effect to confirm:** the 15-minute fallback TTL replaces the 2-hour allowlist TTL in SIGNALLING-PLAN.md decision 8. If signalling or Cloudflare is down for more than 15 minutes, the relay stops admitting devices, though direct connections are unaffected. Before, it was 2 hours. The sidecar pull interval (60 s) is unchanged.

## 8b. Open decisions for Nink (new in v0.4)

Each has a recommended default. Nink hasn't answered these yet; v0.5 leaves every default unchanged and only adds AI KVM's advice.

**(a) SPAKE2 library and external audit budget (§2, §4.D).**
- Default: wrap `pakery-spake2` 0.6.2 as one shared core on every platform, pinned to that version, with the RFC and `sl1` vectors. Budget an external audit of the core and our wrapper, including the `pw → w` choice. Method D doesn't ship before the audit.
- Alternatives: a different RFC 9382 library (for example `backkem/spake2-go`, also unaudited, and Go doesn't cover the stick or mobile), or launching without Method D.

**(b) KVM pairing trigger and display hardware (§4.B.2).**
- Default: option 2, the status display. Pairing is started and confirmed from the logged-in HTTPS config UI, and the display shows the code. Fitting an added button as well is recommended, so pairing also works without a second device.
- Alternatives: option 1 (button and LED on header pins) or option 3 (config UI only).
- AI KVM firmware advice (v0.4 re-review, advice only): strongly in favour of option 2 plus a button. Against offering the presence-only fallback where no button is fitted.

**(c) §4.A deferred until the stick blockers are fixed.**
- Default: defer. Launch with Methods B, C and D. Resume §4.A once every item in "What has to exist before §4.A resumes" is done and reviewed.

**(d) Combined unlock prerequisite (§0 P1), owned by StickLLM.**
- Default: sticklink doesn't ship until key file plus PIN is one combined slot and the plaintext-only slots are removed. StickLLM owns the work and its review.

**(e) KVM security staging timeline (§4.B.6).**
- Default: Stage 0 and 0b before any build that stores a `pair_psk` leaves the bench. Stage 1 on one spare board in parallel. Stage 2 before KVM pairing is released to customers. Until then, release notes state that keys are readable from the flash.
- AI KVM firmware advice (advice only): agrees that Stage 0 and 0b come before any `pair_psk` build. Add the NVS migration (or documented reset) and the cable bootloader flash for field units to the plan (§4.B.6).

**(f) Legacy `stickllm-pair` (§0 P2).**
- Default: retire it before sticklink ships. Alternative: keep it for a while, hardened (salted, slow hash) and off by default, with no access to the sticklink registry.

**(g) Ignoring AI KVM input during every approval (§4 rules).**
- Default: yes, for every method. Trade-off: a machine operated only through an AI KVM can't approve a pairing; the user needs a directly connected keyboard, mouse or touch screen.
- AI KVM firmware advice (advice only): strongly in favour, with the pinned USB port of §4.7.
- AI KVM gave no view on (a), (c), (d) or (f).
- Note (v0.6, StickLLM R4): with this default, KVM detection relies on the `AIKVM-` serial in every mode that has strings. XID mode (045E:0289) has none, so a KVM in XID mode on an unpinned port can't be recognised. That is an accepted risk: XID is gamepad-only, gamepad events never count, and approval is refused while a newly appeared XID-class or unknown HID device is connected (§4.7). The default itself is unchanged.

## 9. Sign-off

| Reviewer | Area | Status |
|---|---|---|
| Nink | Overall | Reviewed v0.2, decisions in v0.3. Open decisions in §8b pending. |
| AI KVM | §2, §3, §4.B, §4.5, §4.7, §6 on ESP32-P4, §10, `vectors/` | **Signed off v0.8 (design only), 2026-10-29 12:38 PM ET.** Vectors re-checked, 622 of 622 match (v0.9 changes are stick-side only) |
| StickLLM | §0, §3, §4.A, §4.C, §4.D, §4.5, §4.6, §4.7, §6 | **Signed off v0.9 (design only), final, 2026-10-29 12:43 PM ET.** Conditional on the VT overlay hardware test and Nink's §8b decisions (a)–(g). No further review rounds. |

## 10. Open hardware notes (not spec rules)

From AI KVM's review. These affect the product, not the pairing protocol.
- **Two-cable setup:** neither board meets it on its own (HDMI in, plus one USB lead to the target that also powers the board).
  - P4-ETH: powered back through the OTG lead, which is an MX1.25 header, so it needs an MX1.25-to-USB-A cable. It has no radio, so network access needs Ethernet, a third cable.
  - NANO: has Wi-Fi through its C6. Its OTG port is a USB-A socket that drives its own 5 V, so the lead to the target must be an A-to-A cable with the 5 V wire cut. So the target probably can't power it, and it needs separate power (USB-C, the 5 V header or PoE). Feeding the target's 5 V into the board would need custom hardware. Unverified.
- **USB power:** the configuration descriptor declares 100 mA. That is probably too low for a P4 at 360 MHz plus the Ethernet PHY, the capture board and (on the NANO) Wi-Fi. The actual draw is unmeasured. Measure it, declare it honestly (USB 2.0 allows up to 500 mA if declared), and test on laptops that police port current.
- The board reboots whenever the target cuts VBUS, for example on sleep or shutdown on some laptops. That is why §3 and §6 require atomic writes.

## 11. Optional additions (not required for sign-off)

1. **Show `RRRR-SSSSSS` next to the QR code,** for devices without a camera. Both use the same mailbox, which then accepts either a QR attempt or a code attempt. One failure cancels both. This brings Method D's cancellation risk (§5) to the QR screen, and puts QR pairing back into the `RRRR` pool (§4.6).
2. **Lock the vault and registry when the stick is removed.** FEATURES.md lists "lock on removal"; it isn't implemented.
3. **List `python3-cryptography` and `python3-nacl` explicitly** in the stick's package list.
4. **Duress PIN, future only, not promised.** One design: the duress PIN opens an empty decoy registry with no identity, destroys the real record keys, and queues a best-effort signed revoke-all. It isn't implemented today.
5. **KVM trigger by a power-on window** (the first 60 s after a power-on reset) was considered and not chosen. Whether a remote attacker could force a VBUS cycle depends on the target PC (unverified).
