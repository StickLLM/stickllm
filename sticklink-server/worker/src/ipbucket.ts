// Copyright (c) 2026 Nink Inc. All rights reserved.
// Rate-limit bucket for a client IP: IPv4 as-is, IPv6 by /64 (one subscriber
// usually holds a whole /64, so per-address limits would be trivial to dodge).

export function ipBucket(ip: string): string {
  if (!ip.includes(":")) return ip;
  const v4tail = /^(.*:)(\d+\.\d+\.\d+\.\d+)$/.exec(ip); // ::ffff:1.2.3.4
  if (v4tail && /^(::ffff:|::)$/i.test(v4tail[1])) return v4tail[2];
  const [head, tail] = ip.toLowerCase().split("::");
  const h = head ? head.split(":") : [];
  const t = tail !== undefined && tail !== "" ? tail.split(":") : [];
  const fill = tail === undefined ? [] : Array(Math.max(0, 8 - h.length - t.length)).fill("0");
  const parts = [...h, ...fill, ...t];
  if (parts.length !== 8 || parts.some((x) => !/^[0-9a-f]{1,4}$/.test(x))) return ip; // unparseable: exact string
  return parts.slice(0, 4).map((x) => x.replace(/^0+(?=.)/, "")).join(":") + "::/64";
}
