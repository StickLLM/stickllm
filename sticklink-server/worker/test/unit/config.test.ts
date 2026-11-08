// Copyright (c) 2026 Nink Inc. All rights reserved.
import { describe, expect, it } from "vitest";
import { L, relayRegPerDay, type Env } from "../../src/config";

const env = (kid: string, o?: string) => ({ SIGNING_KID: kid, TEST_RELAY_REG_PER_DAY: o }) as unknown as Env;

describe("relayRegPerDay (Q-S21)", () => {
  it("defaults to the production quota", () => expect(relayRegPerDay(env("test-1"))).toBe(L.RELAY_REG_PER_DAY));
  it("honours the override with a test- key", () => expect(relayRegPerDay(env("test-1", "1000"))).toBe(1000));
  it("ignores the override with a production key", () => expect(relayRegPerDay(env("k2026-1", "1000"))).toBe(L.RELAY_REG_PER_DAY));
  it("ignores garbage", () => {
    expect(relayRegPerDay(env("test-1", "abc"))).toBe(L.RELAY_REG_PER_DAY);
    expect(relayRegPerDay(env("test-1", "0"))).toBe(L.RELAY_REG_PER_DAY);
  });
});
