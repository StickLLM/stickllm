// Copyright (c) 2026 Nink Inc. All rights reserved.
import { describe, expect, it } from "vitest";
import { ipBucket } from "../../src/ipbucket";

describe("ipBucket", () => {
  it("keeps IPv4", () => expect(ipBucket("203.0.113.9")).toBe("203.0.113.9"));
  it("maps v4-mapped v6 to v4", () => expect(ipBucket("::ffff:203.0.113.9")).toBe("203.0.113.9"));
  it("groups an IPv6 /64", () => {
    const a = ipBucket("2001:db8:1:2::1");
    expect(a).toBe("2001:db8:1:2::/64");
    expect(ipBucket("2001:0db8:0001:0002:ffff:ffff:ffff:ffff")).toBe(a);
    expect(ipBucket("2001:db8:1:3::1")).not.toBe(a);
  });
  it("handles :: forms", () => {
    expect(ipBucket("::1")).toBe("0:0:0:0::/64");
    expect(ipBucket("2001:db8::")).toBe("2001:db8:0:0::/64");
  });
  it("leaves garbage as-is", () => expect(ipBucket("local")).toBe("local"));
});
