# Verified list (hash pinning) — v0.5.3

StickLLM pins a hash for every app, Agent Zero plugin and catalog model it
ships. When upstream changes something, StickLLM notices and blocks the new
build until Nink checks it and updates the pin. People can still install
things that are not on the list, but they have to confirm this warning on
screen first:

> Not verified by StickLLM: this hasn't been checked and may be unsafe

## What is pinned

| Kind | Pin | Where |
| --- | --- | --- |
| Apps (Office, Radicale, Vikunja, Actual, Trilium, Node-RED, Agent Zero) | OCI index digest (`manifest_digest`) and linux/amd64 digest (`amd64_digest`) for one version tag | `overlay/usr/local/share/stickllm/addons/<id>.pin`, `onlyoffice.pin`, `agent-zero.pin` (and the `pin` dict in `stickllm_addons.APPS`) |
| Agent Zero plugins | git commit SHA (40 hex) and tree sha256 of the files | `overlay/usr/local/share/stickllm/agent-zero-plugins.allow` |
| Models | Hugging Face LFS sha256 for each GGUF file | `config/models/catalog.toml` (`sha256 = [...]`) |

`scripts/pins.py manifest` combines all of these into
`overlay/usr/local/share/stickllm/verified.json`. That file ships on the
stick. The ISO build runs `pins.py verify` and stops if anything disagrees.

## States

| State | Badge | Meaning | What happens |
| --- | --- | --- | --- |
| verified | green **Verified** | On the list and the hash matches | Installs normally. Apps are always pulled as `image@amd64_digest`, so Docker itself checks the hash. |
| changed | red **Changed upstream** | The app's version tag now points at a different image than the pin | The new build is **blocked**. The screen offers *Install verified version* (type VERIFIED), which pulls the pinned digest. |
| blocked | red **Blocked** | A plugin or model file does not match its pinned hash | Not loaded or downloaded. A plugin with a different commit or tree hash is skipped at Agent Zero start. |
| unverified | amber **Not verified** | Not on the list | Shows the warning above. Continues only after a typed confirm (INSTALL or DOWNLOAD). |

Where the checks run:

- **Apps page Install** (`POST /api/apps/install`, `POST /api/agent/install`). The gateway asks Docker Hub what the pinned tag points at now (cached 6 hours in `/run/stickllm/upstream-digests.json`).
  - Changed → `409 {"error":"blocked","verification":{...}}` unless the request has `verified_version: true`.
  - Not on the list → `428 {"error":"unverified"}` unless it has `accept_unverified: true`.
  - Offline → treated as verified: the pinned digest is what gets pulled anyway.
- **Apps list** (`GET /api/apps`). Each row has `verification` (status, label, version, digests). It never goes online itself; it only reuses an earlier upstream answer.
- **`GET /api/verified`** returns the whole list with offline statuses. The Apps page uses it for the plugin badges under Agent Zero.
- **Models**
  - The Models page marks a model Verified only when its sha256 is in the catalog. Any other download (known publisher, unknown, local) shows the warning and needs DOWNLOAD typed in.
  - `stickllm-control model_download` also refuses a non-catalog file without `accept_unverified: true`, and refuses a catalog file whose sha256 differs from the pin.
  - For non-catalog files StickLLM still passes Hugging Face's own LFS sha256, so the download is checked against what HF serves. That check proves the file arrived intact, not that StickLLM reviewed it.
- **Plugins.** Only allowlisted plugins are baked into the ISO, at the pinned commit with the tree hash checked. Agent Zero start re-hashes them and skips any mismatch. Other plugins are quarantined; there is no runtime plugin install (see Open questions).
- **Agent Zero**
  - `install_app` replies carry the verification status.
  - The tool prompt tells the agent to report it and never get around it.
  - Nothing installs without the user's click on their own screen. A changed or unverified app still needs that screen's typed confirm, so Agent Zero cannot install unverified items by itself.

## Approving a new upstream version

1. `python3 scripts/pins.py upstream` lists each item as VERIFIED, CHANGED (with the new digest) or UNKNOWN (offline). It exits with 1 when something changed.
2. Check the new release: changelog, image contents, licence.
3. Update the item's `.pin` (and the `pin` dict in `stickllm_addons.APPS`), the allow line, or the catalog sha256.
4. `python3 scripts/pins.py manifest`, then `python3 scripts/pins.py verify`.
5. Run the tests and rebuild the ISO.

## Status on 2026-10-28

`pins.py upstream`: everything VERIFIED.

- **Radicale.** The old pin `sha256:d1046845…` (amd64 `befe4ba4…`, built 2026-10-27 03:38 UTC) was a nightly `push_latest` rebuild that had been pushed under the `3.9.0.0` tag. The tag now points at `sha256:2f215d0e…` (amd64 `18a9ab6d…`). That is the official release-workflow build for GitHub release 3.9.0.0 ("Update to Radicale 3.9.0", published 2026-10-26 12:39 UTC; image built 12:40 UTC).
  - Both builds have the same Dockerfile history, alpine-minirootfs 3.24.3 base layer, labels, UID 2999, healthcheck, volumes and port 5232.
  - The pin is now the release build.
- Both plugins VERIFIED (their pinned commits are still published).
- All four model files VERIFIED (the HF LFS sha256 matches).

## Agent Zero egress

v0.5.3 default-denies Agent Zero internet egress (nft + host proxy + pre-exec scanner + seccomp). See "Egress hardening" under Agent in [APPS.md](APPS.md).

## Blocked apps

Some apps are never installable, whatever their pin: see "Blocked in v0.5.3" in [APPS.md](APPS.md). The ids are in `overlay/usr/local/share/stickllm/blocked-apps.list` and in `verified.json` under `"blocked_apps"`, and `GET /api/verified` lists them as `blocked_apps`. A blocked app can never be pinned: `pins.py verify` fails if one has a `.pin`.

## Testing a changed hash

On a test VM, edit `/usr/local/share/stickllm/verified.json` and change an app's `manifest_digest`, or point its `tag` at another tag. Remove `/run/stickllm/upstream-digests.json` and click Install: the Changed upstream box appears. Deleting the app's entry shows the Not verified box instead.
