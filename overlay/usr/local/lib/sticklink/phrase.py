"""Recovery phrase and PIN rules (§0 P1, §8b defaults).

Stick recovery phrase (pinned format, StickLLM's choice): 12 words drawn
uniformly with secrets.choice from the BIP-0039 English list (2048 words,
11 bits each, 132 bits; no BIP-39 checksum, the words are independent).
Normalisation: lower case, single spaces, no leading/trailing whitespace, no
newline. The 48-hex format is not offered for new phrases; it is still accepted
when typed (12 groups of 4 hex, 192 bits) because existing vault phrases use it.

PIN ("combined unlock" user secret). One of:
  * generated default: 4 words from the EFF large list (7776 words, ~51.7 bits)
  * user passphrase: >= 8 characters, not all digits, not on the common list
  * digits only: >= 12 digits
4-6 digit PINs (and anything weaker) are refused.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from functools import lru_cache
from pathlib import Path

SHARE = Path(os.environ.get("STICKLINK_SHARE", "/usr/local/share/sticklink"))
if not SHARE.is_dir():
    SHARE = Path(__file__).resolve().parents[2] / "share" / "sticklink"

BIP39_SHA256 = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"
EFF_SHA256 = "addd35536511597a02fa0a9ff1e5284677b8883b83e986e43f15a3db996b903e"
COMMON_SHA256 = "68782d6a4a19a4768d5f15dd66bd534e7a33055cc755411e33f16d18c50fdcce"

STICK_PHRASE_LABEL = "Stick recovery phrase (opens this StickLLM stick)"


def vault_phrase_label(computer_name: str) -> str:
    return f"Recovery phrase for the SSD vault on {computer_name}"


def _load(name: str, sha: str) -> bytes:
    data = (SHARE / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise RuntimeError(f"{name}: word list does not match its pinned sha256")
    return data


@lru_cache(None)
def bip39() -> tuple[str, ...]:
    words = tuple(_load("bip39-english.txt", BIP39_SHA256).decode().split())
    assert len(words) == 2048 and len(set(words)) == 2048
    return words


@lru_cache(None)
def eff() -> tuple[str, ...]:
    lines = _load("eff_large_wordlist.txt", EFF_SHA256).decode().splitlines()
    words = tuple(l.split("\t")[1] for l in lines if l.strip())
    assert len(words) == 7776 and len(set(words)) == 7776
    return words


@lru_cache(None)
def common() -> frozenset:
    return frozenset(w.strip().lower() for w in _load("common-passwords.txt", COMMON_SHA256).decode(errors="ignore").splitlines() if w.strip())


def generate_recovery_phrase() -> str:
    w = bip39()
    return " ".join(secrets.choice(w) for _ in range(12))


def generate_pin_passphrase() -> str:
    w = eff()
    return " ".join(secrets.choice(w) for _ in range(4))


_HEX_RE = re.compile(r"^[0-9a-f]{48}$")


def normalise(phrase: str) -> str:
    return " ".join(phrase.strip().lower().split())


def parse_recovery_phrase(phrase: str) -> str:
    """Return the normalised phrase, or raise ValueError if it isn't a pinned format."""
    n = normalise(phrase)
    words = n.split(" ")
    if len(words) == 12 and all(len(x) == 4 for x in words) and _HEX_RE.match("".join(words)):
        return n
    if len(words) == 1 and _HEX_RE.match(n):
        return " ".join(n[i:i + 4] for i in range(0, 48, 4))
    if len(words) == 12:
        known = set(bip39())
        bad = [i + 1 for i, x in enumerate(words) if x not in known]
        if not bad:
            return n
        raise ValueError(f"word {bad[0]} is not in the recovery word list")
    raise ValueError("a recovery phrase is 12 words")


def check_pin(pin: str) -> tuple[bool, str]:
    """PIN strength rule. Returns (ok, reason). The PIN is used byte-exact (UTF-8)."""
    if pin != pin.strip() or "\n" in pin or "\r" in pin:
        return False, "no leading or trailing spaces or line breaks"
    if pin.isdigit():
        if len(pin) < 12:
            return False, "a number-only PIN needs at least 12 digits (4-6 digit PINs are not allowed)"
        if len(set(pin)) <= 2:
            return False, "that number is too easy to guess"
        return True, "ok"
    if len(pin) < 8:
        return False, "use at least 8 characters, or the suggested 4-word passphrase"
    low = pin.lower()
    if low in common() or low.replace(" ", "") in common():
        return False, "that passphrase is on a list of common passwords"
    if len(set(low)) < 4:
        return False, "that passphrase is too easy to guess"
    return True, "ok"
