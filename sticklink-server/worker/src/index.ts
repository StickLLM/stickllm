// Copyright (c) 2026 Nink Inc. All rights reserved.
// Worker entry: routes WebSocket upgrades to the right Durable Object and
// serves the relay allowlist to sticklink-admit. No logging of ids/keys/IPs.
import { hex, unb64u, utf8 } from "./b64";
import { SUBPROTOCOL, type Env, codeModeEnabled } from "./config";
import { ctEqualStr, ipKey, sha256 } from "./crypto";
import type { LimitKind } from "./limiter";
import { RID_RE } from "./proto";
import { buildAllowlist, currentSeq, prune, signer } from "./relay";
import { b64u } from "./b64";

export { HomeDO } from "./home";
export { RouterDO } from "./router";
export { LimiterDO } from "./limiter";
export { FeedDO } from "./feed";

const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json" } });
const notFound = () => new Response("not found", { status: 404 });

function clientIp(req: Request): string {
  return req.headers.get("cf-connecting-ip") ?? "local";
}

async function limiter(env: Env, req: Request) {
  const k = await ipKey(env.IP_PEPPER, clientIp(req));
  return { k, stub: env.LIMITER.get(env.LIMITER.idFromName(k)) };
}

async function relayAuth(env: Env, req: Request, rg: string): Promise<boolean> {
  const m = /^Bearer ([A-Za-z0-9_\-.~]{16,256})$/.exec(req.headers.get("authorization") ?? "");
  if (!m) return false;
  let tokens: Record<string, string>;
  try {
    tokens = JSON.parse(env.RELAY_TOKENS);
  } catch {
    return false;
  }
  const want = tokens[rg];
  if (!want) return false;
  return ctEqualStr(hex(await sha256(utf8(m[1]))), want);
}

async function handleWs(req: Request, env: Env): Promise<Response> {
  if (req.headers.get("upgrade")?.toLowerCase() !== "websocket") return new Response("upgrade required", { status: 426 });
  const protos = (req.headers.get("sec-websocket-protocol") ?? "").split(",").map((s) => s.trim());
  if (!protos.includes(SUBPROTOCOL)) return new Response("subprotocol", { status: 400 });

  const q = new URL(req.url).searchParams;
  const route = q.has("dev") ? "dev" : q.has("home") ? "home" : q.has("rid") ? "rid" : q.has("mbx") ? "mbx" : null;
  if (!route) return notFound();

  const lim = await limiter(env, req);
  // A blocked IP gets the same 404 as an unknown mailbox (no oracle).
  if ((route === "rid" || route === "mbx") && (await lim.stub.blockedFor())) return notFound();
  const kinds: LimitKind[] = route === "rid" || route === "mbx" ? ["upgrade", "mbx"] : ["upgrade"];
  const retry = await lim.stub.hit(kinds);
  if (retry) return new Response("rate", { status: 429, headers: { "retry-after": String(retry) } });

  const fwd = new Headers(req.headers);
  fwd.set("x-sl-route", route);
  fwd.set("x-sl-ipk", lim.k);
  let home: string | null = null;

  if (route === "dev") {
    const dev = q.get("dev")!;
    if (!unb64u(dev, 16)) return notFound();
    const row = await env.DB.prepare("SELECT home FROM devices WHERE dev=?1 AND kind='stick' AND status='active'").bind(dev).first<{ home: string | null }>();
    if (!row?.home) return notFound();
    home = row.home;
    fwd.set("x-sl-dev", dev);
  } else if (route === "home") {
    const h = q.get("home")!;
    if (!unb64u(h, 16)) return notFound();
    const row = await env.DB.prepare("SELECT 1 AS x FROM homes WHERE home=?1").bind(h).first();
    if (!row) return notFound();
    home = h;
  } else {
    // Pairing mailbox lookups. Unknown / expired / blocked are indistinguishable.
    const router = env.ROUTER.get(env.ROUTER.idFromName("global"));
    let hit: { home: string; mbx: string } | null = null;
    {
      if (route === "rid") {
        const rid = q.get("rid")!;
        if (codeModeEnabled(env) && RID_RE.test(rid)) {
          hit = await router.lookupRid(rid);
          if (hit) fwd.set("x-sl-rid", rid);
        }
      } else {
        const mbx = q.get("mbx")!;
        if (unb64u(mbx, 8)) {
          const r = await router.lookupMbx(mbx);
          if (r) hit = { home: r.home, mbx };
        }
      }
      if (!hit) await lim.stub.lookupFailed();
    }
    if (!hit) return notFound();
    home = hit.home;
    fwd.set("x-sl-mbx", hit.mbx);
  }

  fwd.set("x-sl-home", home);
  const stub = env.HOME.get(env.HOME.idFromName(home));
  return stub.fetch(new Request(req.url, { headers: fwd }));
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method !== "GET") return new Response("method", { status: 405 });
    switch (url.pathname) {
      case "/healthz":
        return new Response("ok");
      case "/v1/ws":
        return handleWs(req, env);
      case "/v1/keys": {
        const s = await signer(env);
        return json({ v: 1, keys: [{ kid: s.kid, alg: "Ed25519", pub: b64u(s.pub) }] });
      }
      case "/v1/relay/allowlist":
      case "/v1/relay/rev":
      case "/v1/relay/feed": {
        const rg = url.searchParams.get("rg") ?? "";
        if (!(await relayAuth(env, req, rg))) return new Response("unauthorized", { status: 401 });
        if (url.pathname === "/v1/relay/rev") return json({ rg, seq: await currentSeq(env, rg) });
        if (url.pathname === "/v1/relay/feed") {
          if (req.headers.get("upgrade")?.toLowerCase() !== "websocket") return new Response("upgrade required", { status: 426 });
          const seq = await currentSeq(env, rg);
          return env.FEED.get(env.FEED.idFromName(rg)).fetch(new Request(`https://feed/?seq=${seq}`, { headers: req.headers }));
        }
        const since = Number(url.searchParams.get("since") ?? "0");
        if (!Number.isSafeInteger(since) || since < 0) return new Response("bad since", { status: 400 });
        return json(await buildAllowlist(env, rg, since), 200);
      }
      default:
        return notFound();
    }
  },

  async scheduled(_c: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(prune(env));
  },
} satisfies ExportedHandler<Env>;
