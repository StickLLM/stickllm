#!/usr/bin/env python3
# Copyright (c) 2026 Nink Inc. All rights reserved.
"""IKpsk2 + signalling-envelope vectors for the AI KVM (network initiator)
and StickLLM (responder). TEST ONLY, fixed keys.

  Noise_IKpsk2_25519_ChaChaPoly_SHA256, reference: Python `noiseprotocol` 0.3.1.
  The psk is the slot_join pair_psk from signalling-v2.json (itself from
  vectors/kvm-usb-v1.json run 0), so the chain USB pairing -> pair_psk ->
  network session is covered end to end.

PROPOSALS (not yet in PAIRING-SPEC; see server/OPEN-QUESTIONS.md Q-N1/Q-N2):
  * network prologue (v2, decided by Nink 2026-10-29, Q-N1) =
        "sl1/net" || ver(1)=0x01 || home_id(16) || slot_id(8)
        || initiator_static_pub(32) || responder_static_pub(32)          (96 bytes)
    initiator = AI KVM / phone / desktop, responder = StickLLM
  * sig box           = nonce(12) || ChaCha20-Poly1305(env_k, nonce, inner, aad)
    aad               = "sl1/box" || home_id(16) || slot_id(8) || dir(1)
                        dir 0x01 = client->stick, 0x02 = stick->client
Usage: python3 gen_ikpsk2_vectors.py signalling-v2.json > ikpsk2-v2.json
"""
import base64, json, sys
from noise.connection import NoiseConnection, Keypair
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives import serialization as S

def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def pub(sk): return X25519PrivateKey.from_private_bytes(sk).public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)

sig = json.load(open(sys.argv[1]))
sj = sig["slot_join"]
home, slot = bytes.fromhex(sj["home"]), bytes.fromhex(sj["slot"])
psk, env_k = bytes.fromhex(sj["pair_psk"]), bytes.fromhex(sj["env_k"])
NAME = b"Noise_IKpsk2_25519_ChaChaPoly_SHA256"
keys = {k: bytes([i]) * 32 for k, i in (("kvm_static", 0x11), ("kvm_eph", 0x22), ("stick_static", 0x33), ("stick_eph", 0x44))}
NET_VER = 1
def net_prologue(home, slot, ipub, rpub):
    assert len(home) == 16 and len(slot) == 8 and len(ipub) == 32 and len(rpub) == 32
    return b"sl1/net" + bytes([NET_VER]) + home + slot + ipub + rpub
prologue = net_prologue(home, slot, pub(keys["kvm_static"]), pub(keys["stick_static"]))
assert len(prologue) == 96

def conn(initiator):
    c = NoiseConnection.from_name(NAME)
    if initiator:
        c.set_as_initiator()
        c.set_keypair_from_private_bytes(Keypair.STATIC, keys["kvm_static"])
        c.set_keypair_from_private_bytes(Keypair.EPHEMERAL, keys["kvm_eph"])
        c.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC, pub(keys["stick_static"]))
    else:
        c.set_as_responder()
        c.set_keypair_from_private_bytes(Keypair.STATIC, keys["stick_static"])
        c.set_keypair_from_private_bytes(Keypair.EPHEMERAL, keys["stick_eph"])
    c.set_psks(psk=psk)
    c.set_prologue(prologue)
    c.start_handshake()
    return c

i, r = conn(True), conn(False)
p1, p2 = b"", b""
m1 = i.write_message(p1); assert r.read_message(m1) == p1
m2 = r.write_message(p2); assert i.read_message(m2) == p2
assert i.handshake_finished and r.handshake_finished
assert i.get_handshake_hash() == r.get_handshake_hash()
t1_plain = b'{"k":"ping"}'
t1 = i.encrypt(t1_plain); assert r.decrypt(t1) == t1_plain
t2 = r.encrypt(t1_plain); assert i.decrypt(t2) == t1_plain

# psk2: the PSK is mixed in at the END of message 2, so a responder holding the
# wrong psk still reads msg1 (static keys are not psk-protected); the failure
# is at the initiator reading msg2.
bad = NoiseConnection.from_name(NAME); bad.set_as_responder()
bad.set_keypair_from_private_bytes(Keypair.STATIC, keys["stick_static"])
bad.set_keypair_from_private_bytes(Keypair.EPHEMERAL, keys["stick_eph"])
bad.set_psks(psk=b"\x00" * 32); bad.set_prologue(prologue); bad.start_handshake()
bad.read_message(m1)
bm2 = bad.write_message(b"")
i2 = conn(True); i2.write_message(b"")
try:
    i2.read_message(bm2); wrong_psk_fails = False
except Exception:
    wrong_psk_fails = True
assert wrong_psk_fails

# Binding: a responder whose prologue differs in ANY field (here: the statics swapped, i.e.
# role confusion) cannot read msg1, because h (which absorbed the prologue) keys the
# encryption of the initiator static.
def resp_with(pro):
    c = NoiseConnection.from_name(NAME); c.set_as_responder()
    c.set_keypair_from_private_bytes(Keypair.STATIC, keys["stick_static"])
    c.set_keypair_from_private_bytes(Keypair.EPHEMERAL, keys["stick_eph"])
    c.set_psks(psk=psk); c.set_prologue(pro); c.start_handshake(); return c
mismatch = {}
for name, pro in (("swapped_statics", net_prologue(home, slot, pub(keys["stick_static"]), pub(keys["kvm_static"]))),
                  ("other_slot", net_prologue(home, b"\xff" * 8, pub(keys["kvm_static"]), pub(keys["stick_static"]))),
                  ("ver_2", b"sl1/net" + b"\x02" + prologue[8:]),
                  ("v1_31_byte", b"sl1/net" + home + slot)):
    try:
        resp_with(pro).read_message(m1); mismatch[name] = False
    except Exception:
        mismatch[name] = True
    assert mismatch[name], name

# Signalling box (proposal): what a KVM puts in {"t":"sig","to":"stick","box":...}
inner = json.dumps({"k": "derp", "sid": "AAAAAAAAAAA", "nk": "nodekey:" + "ab" * 32, "rg": "tor1"}, separators=(",", ":")).encode()
nonce = bytes(range(12))
aad = b"sl1/box" + home + slot + b"\x01"
box = nonce + ChaCha20Poly1305(env_k).encrypt(nonce, inner, aad)
frame = json.dumps({"t": "sig", "id": 7, "to": "stick", "box": b64u(box)}, separators=(",", ":"))

out = {
    "_copyright": "Copyright (c) 2026 Nink Inc. All rights reserved.",
    "note": "TEST ONLY. Generated by gen_ikpsk2_vectors.py with noiseprotocol 0.3.1. Prologue v2 decided by Nink 2026-10-29 (Q-N1); box AAD per Q-N2.",
    "version": 2,
    "changes_from_v1": "prologue now binds net version and both static public keys (96 B); msg1/msg2/hash/transport values changed accordingly. psk, keys and box unchanged.",
    "protocol": NAME.decode(),
    "roles": "initiator = AI KVM (or any client), responder = StickLLM",
    "prologue_rule": "'sl1/net'(7) || ver(1)=0x01 || home_id(16) || slot_id(8) || initiator_static_pub(32) || responder_static_pub(32)  (96 B)",
    "prologue_len": len(prologue),
    "prologue": prologue.hex(),
    "psk": psk.hex(), "psk_source": "signalling-v2.json slot_join.pair_psk",
    **{k: v.hex() for k, v in keys.items()},
    "kvm_static_pub": pub(keys["kvm_static"]).hex(), "stick_static_pub": pub(keys["stick_static"]).hex(),
    "msg1": m1.hex(), "msg1_len": len(m1), "msg1_layout": "e(32) || enc(s)(32+16) || enc(payload)(len+16); empty payload -> 96",
    "msg2": m2.hex(), "msg2_len": len(m2), "msg2_layout": "e(32) || enc(payload)(len+16); empty payload -> 48",
    "handshake_hash": i.get_handshake_hash().hex(),
    "transport_plain": t1_plain.decode(),
    "transport_i2r_0": t1.hex(), "transport_r2i_0": t2.hex(),
    "wrong_psk_msg2": bm2.hex(), "wrong_psk_initiator_rejects_msg2": wrong_psk_fails,
    "prologue_mismatch_responder_rejects_msg1": mismatch,
    "box": {"env_k": env_k.hex(), "nonce": nonce.hex(), "aad_rule": "'sl1/box' || home(16) || slot(8) || dir(1: 0x01 client->stick, 0x02 stick->client)",
            "aad": aad.hex(), "inner": inner.decode(), "box": box.hex(), "box_b64": b64u(box), "box_len": len(box),
            "wire_sig": frame, "wire_sig_len": len(frame)},
}
json.dump(out, sys.stdout, indent=2); print()
