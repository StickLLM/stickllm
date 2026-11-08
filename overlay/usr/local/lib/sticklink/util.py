"""Small helpers: base64url without padding (API.md "Encoding")."""
from __future__ import annotations

import base64
import binascii


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def unb64u(s: str, want: int | None = None) -> bytes:
    if not isinstance(s, str) or "=" in s:
        raise ValueError("bad b64url")
    try:
        b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError) as e:
        raise ValueError("bad b64url") from e
    if b64u(b) != s:
        raise ValueError("non-canonical b64url")
    if want is not None and len(b) != want:
        raise ValueError(f"want {want} bytes, got {len(b)}")
    return b
