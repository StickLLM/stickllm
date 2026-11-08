// Copyright (c) 2026 Nink Inc. All rights reserved.
// Wire-format validation. Every byte field has a fixed length so constrained
// clients (AI KVM, ~111 KB RAM) can parse with fixed buffers.
import { unb64u } from "./b64";

export const LEN = { home: 16, slot: 8, mbx: 8, dev: 16, mac: 32, jk: 32, n: 32, sig: 64, ak: 32, pop: 64 } as const;

export type ErrCode = "rate" | "auth" | "size" | "offline" | "unknown" | "busy" | "bad" | "nf" | "disabled";

export const NK_RE = /^nodekey:[0-9a-f]{64}$/;
export const RID_RE = /^[0-9]{4}$/;
export const CONN_RE = /^c[0-9]{1,6}$/;

export type Msg = Record<string, unknown> & { t: string; id?: number };

export function parse(raw: string): Msg | null {
  let m: unknown;
  try {
    m = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!m || typeof m !== "object" || Array.isArray(m)) return null;
  const o = m as Msg;
  if (typeof o.t !== "string" || o.t.length > 16) return null;
  if (o.id !== undefined && (!Number.isInteger(o.id) || (o.id as number) < 0 || (o.id as number) > 0xffffffff)) return null;
  return o;
}

export const bytes = (m: Msg, k: keyof typeof LEN) => unb64u(m[k], LEN[k]);
export const bytesAs = (v: unknown, k: keyof typeof LEN) => unb64u(v, LEN[k]);

export function err(code: ErrCode, id?: number, retry?: number): string {
  const o: Record<string, unknown> = { t: "err", code };
  if (id !== undefined) o.id = id;
  if (retry !== undefined) o.retry = Math.max(1, Math.ceil(retry));
  return JSON.stringify(o);
}

export const nowS = () => Math.floor(Date.now() / 1000);
