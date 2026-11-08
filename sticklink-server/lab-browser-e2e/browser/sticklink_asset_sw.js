/**
 * StickLink Phase 1: HTTP asset tunnel via Service Worker.
 * Intercepts /agent-zero, /socket.io, /api/agent, /api/csrf only.
 * WebSockets are NOT handled here — page uses the constructor adapter.
 * v=perf2 — gzip mux + concurrency 8 + static Cache API.
 */
/* eslint-disable no-restricted-globals */

const CACHE_NAME = "sticklink-a0-static-v1";

const TUNNEL_PREFIXES = [
  "/agent-zero",
  "/socket.io",
  "/api/agent",
  "/api/csrf",
  "/public",
  "/plugins",
  "/js",
  "/components",
  "/vendor",
  "/ui",
  "/extensions",
  "/css",
  "/index.js",
  "/index.css",
];

function shouldTunnel(pathname) {
  const p = pathname || "";
  if (p === "/api/csrf_token" || p === "/favicon.ico" || p === "/sw.js") return true;
  return TUNNEL_PREFIXES.some((pre) => p === pre || p.startsWith(pre + "/") || p.startsWith(pre));
}

function isStaticCacheable(pathname, method) {
  if (method && String(method).toUpperCase() !== "GET") return false;
  const p = pathname || "";
  // Never cache authenticated / dynamic Agent Zero surfaces.
  if (p.includes("/api/") || p.includes("/socket.io")) return false;
  if (p.endsWith("/ui/index") || p.endsWith("/agent-zero/") || p.endsWith("/agent-zero")) return false;
  if (p.includes("/csrf")) return false;
  return (
    p.includes("/vendor/") ||
    p.includes("/public/") ||
    /\.(js|mjs|css|woff2?|ttf|otf|svg|png|jpg|jpeg|webp|map)$/i.test(p)
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (!shouldTunnel(url.pathname)) return;
  event.respondWith(tunnelFetch(event));
});

async function findHostClient() {
  const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  const join = all.find((c) => /\/browser\/agent_join\.html/.test(c.url));
  return join || all[0] || null;
}

async function tunnelFetch(event) {
  const swStart = Date.now();
  const req = event.request;
  const url = new URL(req.url);

  if (isStaticCacheable(url.pathname, req.method)) {
    try {
      const cache = await caches.open(CACHE_NAME);
      const hit = await cache.match(req);
      if (hit) {
        const headers = new Headers(hit.headers);
        headers.set("x-sticklink-sw-cache", "HIT");
        return new Response(hit.body, { status: hit.status, statusText: hit.statusText, headers });
      }
    } catch (_) {}
  }

  const host = await findHostClient();
  if (!host) {
    return new Response(
      JSON.stringify({ error: "sticklink_sw_no_host", message: "Pair page not controlling mux" }),
      { status: 503, headers: { "content-type": "application/json" } },
    );
  }
  const headers = {};
  req.headers.forEach((v, k) => {
    headers[k] = v;
  });

  let body = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.arrayBuffer();
  }

  const postAt = Date.now();
  const mc = new MessageChannel();
  const reply = new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("sticklink mux timeout")), 180000);
    mc.port1.onmessage = (ev) => {
      clearTimeout(t);
      const d = ev.data || {};
      if (d.error) reject(new Error(d.error));
      else resolve(d);
    };
  });

  host.postMessage(
    {
      type: "sticklink-mux-http",
      method: req.method,
      path: url.pathname + url.search,
      headers,
      body,
      _swStart: swStart,
    },
    [mc.port2],
  );

  let data;
  try {
    data = await reply;
  } catch (e) {
    return new Response(String(e && e.message ? e.message : e), {
      status: 502,
      headers: { "content-type": "text/plain" },
    });
  }
  const hostReplyMs = Date.now() - postAt;
  const totalMs = Date.now() - swStart;

  const outHeaders = new Headers();
  const raw = data.headers || {};
  for (const [k, v] of Object.entries(raw)) {
    if (v == null) continue;
    const lk = k.toLowerCase();
    if (lk === "content-encoding" || lk === "content-length" || lk === "transfer-encoding") continue;
    try {
      outHeaders.set(k, String(v));
    } catch (_) {
      /* hop / invalid */
    }
  }
  outHeaders.set("x-sticklink-sw-ms", String(totalMs));
  outHeaders.set("x-sticklink-sw-host-ms", String(hostReplyMs));

  let bodyOut = data.body || new ArrayBuffer(0);
  const bytes =
    bodyOut instanceof ArrayBuffer
      ? bodyOut.byteLength
      : bodyOut && bodyOut.byteLength != null
        ? bodyOut.byteLength
        : 0;
  try {
    host.postMessage({
      type: "sticklink-sw-perf",
      path: url.pathname + url.search,
      swStart,
      hostReplyMs,
      totalMs,
      status: data.status || 200,
      bytes,
    });
  } catch (_) {}

  const ct = (outHeaders.get("content-type") || "").toLowerCase();
  if (req.method === "GET" && ct.includes("text/html")) {
    bodyOut = injectHtmlFixes(bodyOut);
    outHeaders.delete("content-length");
  }

  outHeaders.set("x-sticklink-sw-cache", "MISS");
  const response = new Response(bodyOut, { status: data.status || 200, headers: outHeaders });
  if (
    (data.status || 200) === 200 &&
    isStaticCacheable(url.pathname, req.method) &&
    !ct.includes("text/html")
  ) {
    try {
      const cache = await caches.open(CACHE_NAME);
      await cache.put(req, response.clone());
    } catch (_) {}
  }
  return response;
}

function injectHtmlFixes(buf) {
  const td = new TextDecoder();
  const te = new TextEncoder();
  let html = td.decode(buf instanceof ArrayBuffer ? buf : new Uint8Array(buf));
  // Relative assets in /agent-zero/ui/index resolve under /ui/ and 404 — pin base.
  if (!/<base\b/i.test(html)) {
    const base = '<base href="/agent-zero/" data-sticklink-base="1">';
    if (/<head[^>]*>/i.test(html)) html = html.replace(/<head[^>]*>/i, (m) => m + base);
    else html = base + html;
  }
  if (!html.includes("data-sticklink-ws-bridge")) {
    const bridge =
      '<script data-sticklink-ws-bridge="1" src="/browser/a0_ws_bridge.js"><\/script>';
    if (/<head[^>]*>/i.test(html)) {
      html = html.replace(/<head[^>]*>/i, (m) => m + bridge);
    } else {
      html = bridge + html;
    }
  }
  return te.encode(html).buffer;
}
