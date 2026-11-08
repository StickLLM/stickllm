// Copyright (c) 2026 Nink Inc. All rights reserved.
// Cross-implementation vectors: Python generator (server/vectors) vs Worker crypto.
import { describe, expect, it } from "vitest";
import V from "../../../vectors/signalling-v2.json";
import QR from "../../../../vectors/qr-v1.json";
import { b64u, unb64u, unhex, utf8 } from "../../src/b64";
import {
  DOM_ALLOWLIST, DOM_DEV_HELLO, DOM_DEV_ROTATE, DOM_PERMIT, DOM_REVOKED, ed25519Verify, getSigner, helloBody, hkdf, hmac,
  hmacVerify, joinInput, qrJoinInput, ROLE_CLIENT, ROLE_SERVER, rotateBody, signedInput,
} from "../../src/crypto";

describe("signalling-v2 vectors", () => {
  it("device Ed25519 hello signatures (server and client roles) and auth.rotate PoP", async () => {
    const d = V.device;
    const n = unhex(d.nonce);
    const dev = unhex(d.dev);
    const ak = unhex(d.ak);
    const hs = helloBody(n, dev, ROLE_SERVER, unhex(d.home));
    const hc = helloBody(n, dev, ROLE_CLIENT, null);
    expect(Buffer.from(signedInput(DOM_DEV_HELLO, hs)).toString("hex")).toBe(d.hello_input_server);
    expect(Buffer.from(signedInput(DOM_DEV_HELLO, hc)).toString("hex")).toBe(d.hello_input_client);
    expect(await ed25519Verify(ak, DOM_DEV_HELLO, hs, unhex(d.hello_sig_server))).toBe(true);
    expect(await ed25519Verify(ak, DOM_DEV_HELLO, hc, unhex(d.hello_sig_client))).toBe(true);
    expect(await ed25519Verify(ak, DOM_DEV_HELLO, hc, unhex(d.hello_sig_server))).toBe(false); // role is bound
    expect(JSON.parse(d.wire_hello_server).sig).toBe(d.hello_sig_server_b64);
    expect(d.wire_hello_server.length).toBeLessThan(260);
    const nak = unhex(d.rotate_new_ak);
    const rb = rotateBody(n, dev, nak, ak);
    expect(Buffer.from(signedInput(DOM_DEV_ROTATE, rb)).toString("hex")).toBe(d.rotate_input);
    expect(await ed25519Verify(nak, DOM_DEV_ROTATE, rb, unhex(d.rotate_pop))).toBe(true);
    expect(await ed25519Verify(ak, DOM_DEV_ROTATE, rb, unhex(d.rotate_pop))).toBe(false);
    // The private seeds are deterministic test values; the derived public keys must match.
    for (const [seed, pub] of [[d.auth_seed, d.ak], [d.rotate_new_seed, d.rotate_new_ak]]) {
      const pk8 = new Uint8Array([...unhex("302e020100300506032b657004220420"), ...unhex(seed)]);
      const k = await crypto.subtle.importKey("pkcs8", pk8, { name: "Ed25519" }, true, ["sign"]);
      const jwk = (await crypto.subtle.exportKey("jwk", k)) as JsonWebKey;
      expect(Buffer.from(unb64u(jwk.x!)!).toString("hex")).toBe(pub);
    }
  });

  it("slot join key chain and join MAC (KVM / phone)", async () => {
    const s = V.slot_join;
    const P = await hkdf(unhex(s.pair_psk), "sl1/slot-secret");
    expect(Buffer.from(P).toString("hex")).toBe(s.P_slot);
    const jk = await hkdf(P, "sl1/join");
    expect(Buffer.from(jk).toString("hex")).toBe(s.jk);
    expect(Buffer.from(await hkdf(P, "sl1/env")).toString("hex")).toBe(s.env_k);
    const mac = await hmac(jk, joinInput(unhex(s.nonce), unhex(s.home), unhex(s.slot)));
    expect(b64u(mac)).toBe(s.join_mac_b64);
    expect(JSON.parse(s.wire_join).mac).toBe(s.join_mac_b64);
    expect(s.wire_join.length).toBeLessThan(160); // KVM-sized frame
  });

  it("QR mailbox join MAC matches qr-v1.json", async () => {
    const jk = await hkdf(unhex(QR.invite_secret), "sl1/qr-join");
    expect(Buffer.from(jk).toString("hex")).toBe(QR.jk_qr);
    const ok = await hmacVerify(jk, qrJoinInput(unhex(QR.server_nonce), unhex(QR.mailbox_id)), unhex(QR.join_mac));
    expect(ok).toBe(true);
  });

  it("Ed25519: Worker signer reproduces Python signatures byte-for-byte", async () => {
    const s = await getSigner(V.signing.seed_b64, "test-1");
    expect(b64u(s.pub)).toBe(V.signing.pub_b64);
    for (const [dom, e] of [[DOM_PERMIT, V.permit], [DOM_ALLOWLIST, V.allowlist_full], [DOM_ALLOWLIST, V.allowlist_delta], [DOM_REVOKED, V.revoked]] as const) {
      const body = unb64u(e.body)!;
      expect(new TextDecoder().decode(body)).toBe(e.body_json);
      expect(b64u(await s.sign(dom, body))).toBe(e.sig);
      expect(await ed25519Verify(s.pub, dom, body, unb64u(e.sig)!)).toBe(true);
      // Domain separation: a permit signature is not an allowlist signature.
      expect(await ed25519Verify(s.pub, dom === DOM_PERMIT ? DOM_ALLOWLIST : DOM_PERMIT, body, unb64u(e.sig)!)).toBe(false);
    }
    expect(V.permit.tok).toBe(V.permit.body + "." + V.permit.sig);
  });

  it("base64url is strict and canonical", () => {
    expect(unb64u("AAEC")).toEqual(new Uint8Array([0, 1, 2]));
    expect(unb64u("AAE=")).toBeNull(); // padding
    expect(unb64u("AAF")).toBeNull(); // non-canonical trailing bits
    expect(unb64u("AA+C")).toBeNull(); // not url alphabet
    expect(unb64u(b64u(utf8("x".repeat(8))), 8)).not.toBeNull();
    expect(unb64u(b64u(utf8("x".repeat(9))), 8)).toBeNull();
  });
});
