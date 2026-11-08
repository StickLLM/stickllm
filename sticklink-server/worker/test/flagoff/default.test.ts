// Copyright (c) 2026 Nink Inc. All rights reserved.
// Default deployment config: FEATURE_SPAKE2_CODE=0 (PAIRING-SPEC §8b(a)).
import { describe, expect, it } from "vitest";
import { b64u, randomBytes } from "../../src/b64";
import { connectStick, routerStub, seedHome, uniqIp, upgrade } from "../helpers";

describe("SPAKE2 code mode is off by default", () => {
  it("pair.open m:code -> err:disabled; QR still works", async () => {
    const f = await seedHome();
    const stick = await connectStick(f);
    expect(await stick.req({ t: "pair.open", id: 1, m: "code" })).toEqual({ t: "err", code: "disabled", id: 1 });
    const ok = await stick.req({ t: "pair.open", id: 2, m: "qr", jk: b64u(randomBytes(32)) }, "pair.ok");
    expect(ok.rid).toBeUndefined();
    expect((await routerStub().stats()).live).toBe(0);
  });

  it("?rid= lookups are always 404", async () => {
    for (const rid of ["0000", "1234", "9999"]) expect((await upgrade("rid=" + rid, uniqIp())).status).toBe(404);
  });
});
