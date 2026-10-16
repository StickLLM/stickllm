# REVIEW notes (zip had no REVIEW.md)

`stickllm-clean-ui-models.zip` shipped `clean/MAP.md` only. Constraints applied from MAP.md + `ui/mockup/DESIGN.md`:

## Avoid
- SSH password / credentials in the LAN browser (stick console / F10 on kiosk only)
- Pair code in the always-visible header strip (Devices & Pairing / kiosk only)
- Stamping “web on” on every reply bubble
- Partitioning or formatting the user’s own drives (claim = StickLLM stick only)
- Whole-partition vault create / ERASE-PARTITION flows
- Committing secrets, vault passcodes, or HF tokens into the repo

## Prefer
- Models saved to the folder the user picks (USB DATA vs vault/SSD mount)
- Catalog pinned downloads with hash verify; live HF search can follow later
- Shared picker for vault / models folder / (later) attach
