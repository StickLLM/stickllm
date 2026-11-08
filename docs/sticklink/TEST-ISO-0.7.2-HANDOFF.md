# v0.7.2 TEST ISO — operator handoff

**Stop here for human hardware test.** No shipping tag `v0.7.2` yet.

| | |
|--|--|
| ISO | `C:\Users\peter\stickllm-sticklink-wt\out\v0.7.2\StickLLM-v0.7.2.iso` |
| SHA-256 | `d28cd326eb1fe55a84788ab6ec8caf828f601ba43c74e845de06c70de1943374` |
| Checksum file | `checksums/v0.7.2.sha256` |
| Size | 9272559616 bytes |
| Method C known-good | tag `methodc-lte-accept-20261108.1` @ `860ea3cc…` (unchanged) |
| Parked prior bake | `StickLLM-v0.7.2-pre-methodc-20261108am.iso` (`5a6d09df…`) |

## Your checklist

1. Flash Samsung USB (Rufus DD or elevated `out/safe-flash-samsung-auth.py`).
2. Boot → kiosk READY.
3. Devices & Pairing: StickLink QR; wait past ~60s; refresh/remint; new QR.
4. Lab join publisher + phone LTE Method C chat.
5. Report PASS/FAIL — only then cut shipping tag.

## UNTESTED on this ISO (by design — operator)

- Real hardware boot to kiosk
- QR generation + post-60s refresh on this flash
- Phone ICE type over LTE
