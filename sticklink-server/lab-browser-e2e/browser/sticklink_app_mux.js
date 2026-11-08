/**
 * StickLink app-mux v1 client (see docs/sticklink/APP-MUX-V1.md).
 * Runs on the Noise DC after agent_ready. No Service Worker.
 */
const te = new TextEncoder();
const td = new TextDecoder();
const b64u = (u8) => btoa(String.fromCharCode(...u8)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  return Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad), (c) => c.charCodeAt(0));
};

const CHUNK = 36 * 1024;
const MAX_BODY = 8 * 1024 * 1024;

export function createAppMux({ sendPt, recvLoop, log }) {
  const L = (m) => log?.(m);
  const pendingHttp = new Map(); // id -> {resolve,reject,chunks,headers,status,role}
  const pendingWsOpen = new Map();
  const wsSockets = new Map(); // id -> StickSocket
  let httpSeq = 1;
  let wsSeq = 1;
  let inflightHttp = 0;
  // Overridable for perf experiments: window.__sticklinkHttpMax
  const HTTP_MAX =
    typeof window !== "undefined" && Number(window.__sticklinkHttpMax) > 0
      ? Number(window.__sticklinkHttpMax)
      : 8;
  const httpWaiters = [];
  const perf = () => (typeof window !== "undefined" ? window.__sticklinkPerf : null);
  let slotChain = Promise.resolve();

  function pumpHttpWaiters() {
    while (inflightHttp < HTTP_MAX && httpWaiters.length) {
      httpWaiters.shift()();
    }
  }

  /** Serialize slot acquire so inflight never races past HTTP_MAX. */
  async function withHttpSlot(fn) {
    const queuedAt = perf()?.now?.() ?? 0;
    const run = slotChain.then(async () => {
      if (inflightHttp >= HTTP_MAX) {
        await new Promise((r) => httpWaiters.push(r));
      }
      inflightHttp++;
    });
    slotChain = run.catch(() => {});
    await run;
    const waitedMs = (perf()?.now?.() ?? 0) - queuedAt;
    try {
      return await fn({ queuedAt, waitedMs, inflightAtStart: inflightHttp });
    } finally {
      inflightHttp--;
      pumpHttpWaiters();
    }
  }

  async function maybeGunzip(headers, body) {
    const ce = (headers && (headers["x-sticklink-ce"] || headers["X-StickLink-Ce"])) || "";
    if (String(ce).toLowerCase() !== "gzip" || !body || !body.length) return body;
    if (typeof DecompressionStream === "undefined") return body;
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([body]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  function onMuxMessage(msg) {
    const t = msg?.t;
    if (t === "http_res") {
      const p = pendingHttp.get(msg.id);
      if (!p) return;
      const ttfb = perf()?.now?.() ?? 0;
      if (msg.body_len != null && msg.body_b64 == null && !msg.eof) {
        p.status = msg.status;
        p.headers = msg.headers || {};
        p.chunks = [];
        p.expect = Number(msg.body_len) || 0;
        p._ttfbMs = ttfb;
        return;
      }
      const body = msg.body_b64 ? unb64u(msg.body_b64) : new Uint8Array(0);
      const headers = msg.headers || {};
      pendingHttp.delete(msg.id);
      maybeGunzip(headers, body)
        .then((plain) => {
          p.resolve({
            status: msg.status,
            headers,
            body: plain,
            text: td.decode(plain),
            _ttfbMs: ttfb,
            _chunks: 1,
          });
        })
        .catch((e) => p.reject(e));
      return;
    }
    if (t === "http_chunk" && msg.role === "res") {
      const p = pendingHttp.get(msg.id);
      if (!p) return;
      if (p._ttfbMs == null) p._ttfbMs = perf()?.now?.() ?? 0;
      p.chunks = p.chunks || [];
      const piece = msg.body_b64 ? unb64u(msg.body_b64) : new Uint8Array(0);
      p.chunks.push(piece);
      const n = p.chunks.reduce((a, c) => a + c.length, 0);
      if (n > MAX_BODY) {
        p.reject(new Error("body too large"));
        pendingHttp.delete(msg.id);
        return;
      }
      if (msg.eof) {
        const body = new Uint8Array(n);
        let o = 0;
        for (const c of p.chunks) {
          body.set(c, o);
          o += c.length;
        }
        const headers = p.headers || {};
        const chunks = p.chunks.length;
        const ttfb0 = p._ttfbMs;
        pendingHttp.delete(msg.id);
        maybeGunzip(headers, body)
          .then((plain) => {
            p.resolve({
              status: p.status,
              headers,
              body: plain,
              text: td.decode(plain),
              _ttfbMs: ttfb0,
              _chunks: chunks,
            });
          })
          .catch((e) => p.reject(e));
      }
      return;
    }
    if (t === "ws_opened") {
      const w = pendingWsOpen.get(msg.id);
      if (w) {
        pendingWsOpen.delete(msg.id);
        w.resolve();
      }
      return;
    }
    if (t === "ws_error") {
      const w = pendingWsOpen.get(msg.id);
      if (w) {
        pendingWsOpen.delete(msg.id);
        w.reject(new Error(msg.message || "ws_error"));
      }
      const sock = wsSockets.get(msg.id);
      sock?._onError(msg.message || "ws_error");
      return;
    }
    if (t === "ws_data" || t === "ws_chunk") {
      const sock = wsSockets.get(msg.id);
      if (!sock) return;
      if (t === "ws_data") {
        const raw = msg.body_b64 ? unb64u(msg.body_b64) : new Uint8Array(0);
        sock._onData(raw, !!msg.binary);
        return;
      }
      sock._pushChunk(msg);
      return;
    }
    if (t === "ws_close") {
      const sock = wsSockets.get(msg.id);
      sock?._onClose(msg.code || 1000, msg.reason || "");
      wsSockets.delete(msg.id);
      return;
    }
    if (t === "pong" || t === "ping") return;
  }

  // recvLoop is owned by caller: they call mux.dispatch(msg) for app types
  const mux = {
    dispatch: onMuxMessage,

    async http(method, path, headers = {}, body = null) {
      return withHttpSlot(async (slot) => {
        const id = "r" + httpSeq++;
        const u8 =
          body == null
            ? null
            : typeof body === "string"
              ? te.encode(body)
              : body instanceof Uint8Array
                ? body
                : new Uint8Array(body);
        const P = perf();
        const startAt = P?.now?.() ?? 0;
        P?.onHttpStart?.({
          id,
          method: method.toUpperCase(),
          path,
          queuedAt: slot?.queuedAt ?? startAt,
          startAt,
          waitedMs: slot?.waitedMs ?? 0,
          inflightAtStart: slot?.inflightAtStart ?? inflightHttp,
          ttfbMs: null,
          doneMs: null,
          status: null,
          bytes: 0,
          chunks: 0,
        });

        const result = await new Promise((resolve, reject) => {
          const entry = {
            resolve,
            reject,
            status: 0,
            headers: {},
            chunks: null,
            _perfId: id,
            _startAt: startAt,
          };
          pendingHttp.set(id, entry);
          const hdrs = {};
          for (const [k, v] of Object.entries(headers || {})) {
            if (v == null) continue;
            hdrs[k] = String(v);
          }
          if (!u8 || u8.length <= CHUNK) {
            const payload = {
              t: "http_req",
              id,
              method: method.toUpperCase(),
              path,
              headers: hdrs,
            };
            if (u8 && u8.length) payload.body_b64 = b64u(u8);
            sendPt(payload);
          } else {
            sendPt({
              t: "http_req",
              id,
              method: method.toUpperCase(),
              path,
              headers: hdrs,
              body_len: u8.length,
            });
            let seq = 0;
            for (let i = 0; i < u8.length; i += CHUNK) {
              const slice = u8.subarray(i, Math.min(i + CHUNK, u8.length));
              const eof = i + CHUNK >= u8.length;
              sendPt({
                t: "http_chunk",
                id,
                role: "req",
                seq: seq++,
                eof,
                body_b64: b64u(slice),
              });
            }
          }
          setTimeout(() => {
            if (pendingHttp.has(id)) {
              pendingHttp.delete(id);
              reject(new Error("http timeout " + path));
            }
          }, 180000);
        });
        const ce =
          (result.headers &&
            (result.headers["x-sticklink-ce"] ||
              result.headers["content-encoding"] ||
              result.headers["Content-Encoding"])) ||
          null;
        P?.onHttpDone?.(id, {
          doneMs: P?.now?.() ?? 0,
          ttfbMs: result._ttfbMs ?? null,
          status: result.status,
          bytes: result.body ? result.body.length : 0,
          chunks: result._chunks || (result.body && result.body.length > CHUNK ? 2 : 1),
          contentEncoding: ce,
        });
        return result;
      });
    },

    openWebSocket(url, protocols) {
      const id = "w" + wsSeq++;
      const sock = new StickSocket(id, url, protocols, sendPt, () => wsSockets.delete(id));
      wsSockets.set(id, sock);
      const opened = new Promise((resolve, reject) => {
        pendingWsOpen.set(id, { resolve, reject });
        setTimeout(() => {
          if (pendingWsOpen.has(id)) {
            pendingWsOpen.delete(id);
            reject(new Error("ws_open timeout"));
          }
        }, 60000);
      });
      const path = (() => {
        try {
          if (url.startsWith("/")) return url;
          const u = new URL(url, location.href);
          return u.pathname + u.search;
        } catch {
          return String(url);
        }
      })();
      sendPt({
        t: "ws_open",
        id,
        url: path,
        protocols: protocols
          ? Array.isArray(protocols)
            ? protocols
            : [protocols]
          : [],
      });
      opened.then(
        () => sock._markOpen(),
        (e) => sock._onError(String(e)),
      );
      return sock;
    },
  };
  return mux;
}

class StickSocket {
  constructor(id, url, protocols, sendPt, onGone) {
    this.id = id;
    this.url = url;
    this.protocol = "";
    this.readyState = 0; // CONNECTING
    this.bufferedAmount = 0;
    this.extensions = "";
    this.binaryType = "arraybuffer";
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    this._sendPt = sendPt;
    this._onGone = onGone;
    this._chunks = null;
    this._chunkBin = false;
  }
  _markOpen() {
    this.readyState = 1;
    this.onopen?.({ type: "open", target: this });
  }
  _onError(message) {
    this.onerror?.({ type: "error", message, target: this });
  }
  _onClose(code, reason) {
    this.readyState = 3;
    this.onclose?.({ type: "close", code, reason, wasClean: code === 1000, target: this });
    this._onGone?.();
  }
  _onData(raw, binary) {
    let data;
    if (binary) data = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
    else data = td.decode(raw);
    this.onmessage?.({ type: "message", data, target: this });
  }
  _pushChunk(msg) {
    this._chunks = this._chunks || [];
    this._chunkBin = !!msg.binary;
    const piece = msg.body_b64 ? unb64u(msg.body_b64) : new Uint8Array(0);
    this._chunks.push(piece);
    if (msg.eof) {
      const n = this._chunks.reduce((a, c) => a + c.length, 0);
      const body = new Uint8Array(n);
      let o = 0;
      for (const c of this._chunks) {
        body.set(c, o);
        o += c.length;
      }
      this._chunks = null;
      this._onData(body, this._chunkBin);
    }
  }
  send(data) {
    if (this.readyState !== 1) throw new Error("INVALID_STATE_ERR");
    let u8;
    let binary = false;
    if (typeof data === "string") u8 = te.encode(data);
    else if (data instanceof ArrayBuffer) {
      u8 = new Uint8Array(data);
      binary = true;
    } else if (ArrayBuffer.isView(data)) {
      u8 = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      binary = true;
    } else {
      u8 = te.encode(String(data));
    }
    if (u8.length <= CHUNK) {
      this._sendPt({ t: "ws_data", id: this.id, binary, body_b64: b64u(u8) });
      return;
    }
    let seq = 0;
    for (let i = 0; i < u8.length; i += CHUNK) {
      const slice = u8.subarray(i, Math.min(i + CHUNK, u8.length));
      this._sendPt({
        t: "ws_chunk",
        id: this.id,
        seq: seq++,
        eof: i + CHUNK >= u8.length,
        binary,
        body_b64: b64u(slice),
      });
    }
  }
  close(code = 1000, reason = "") {
    if (this.readyState === 2 || this.readyState === 3) return;
    this.readyState = 2;
    this._sendPt({ t: "ws_close", id: this.id, code, reason: String(reason || "") });
  }
  addEventListener(type, fn) {
    if (type === "open") this.onopen = fn;
    else if (type === "message") this.onmessage = fn;
    else if (type === "error") this.onerror = fn;
    else if (type === "close") this.onclose = fn;
  }
  removeEventListener() {}
}

/** Install fetch / XHR / WebSocket adapters that use mux. Call before loading A0. */
export function installBrowserTransport(mux, { log } = {}) {
  const L = (m) => log?.(m);
  const OrigWS = window.WebSocket;
  const OrigFetch = window.fetch.bind(window);
  const OrigXHR = window.XMLHttpRequest;

  function shouldTunnel(url) {
    try {
      const u = typeof url === "string" ? new URL(url, location.href) : new URL(url.url || String(url), location.href);
      const p = u.pathname;
      return (
        p.startsWith("/agent-zero") ||
        p.startsWith("/socket.io") ||
        p.startsWith("/api/agent") ||
        p.startsWith("/api/csrf") ||
        p === "/api/csrf_token"
      );
    } catch {
      return false;
    }
  }

  function toPath(url) {
    const u = new URL(typeof url === "string" ? url : String(url), location.href);
    return u.pathname + u.search;
  }

  window.WebSocket = function PatchedWebSocket(url, protocols) {
    if (!shouldTunnel(url)) return new OrigWS(url, protocols);
    L("WS via StickLink " + url);
    return mux.openWebSocket(String(url), protocols);
  };
  window.WebSocket.CONNECTING = 0;
  window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2;
  window.WebSocket.CLOSED = 3;
  window.WebSocket.prototype = OrigWS.prototype;

  window.fetch = async function patchedFetch(input, init = {}) {
    const url = typeof input === "string" ? input : input.url;
    if (!shouldTunnel(url)) return OrigFetch(input, init);
    const method = (init.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();
    const headers = {};
    const h = init.headers || (typeof input !== "string" ? input.headers : null);
    if (h) {
      if (h.forEach) h.forEach((v, k) => (headers[k] = v));
      else for (const [k, v] of Object.entries(h)) headers[k] = v;
    }
    let body = init.body ?? null;
    if (body && typeof body !== "string" && !(body instanceof Uint8Array) && !(body instanceof ArrayBuffer)) {
      if (body instanceof Blob) body = new Uint8Array(await body.arrayBuffer());
      else body = String(body);
    }
    if (body instanceof ArrayBuffer) body = new Uint8Array(body);
    L(`HTTP ${method} ${toPath(url)} via StickLink`);
    const res = await mux.http(method, toPath(url), headers, body);
    return new Response(res.body, {
      status: res.status,
      headers: res.headers,
    });
  };

  window.XMLHttpRequest = function PatchedXHR() {
    const xhr = new OrigXHR();
    let _url = "";
    let _method = "GET";
    let _headers = {};
    let _tunnel = false;
    const open = xhr.open.bind(xhr);
    xhr.open = function (method, url, ...rest) {
      _method = method;
      _url = String(url);
      _tunnel = shouldTunnel(_url);
      if (!_tunnel) return open(method, url, ...rest);
      this.readyState = 1;
      this.onreadystatechange?.();
    };
    const setRequestHeader = xhr.setRequestHeader.bind(xhr);
    xhr.setRequestHeader = function (k, v) {
      if (!_tunnel) return setRequestHeader(k, v);
      _headers[k] = v;
    };
    const send = xhr.send.bind(xhr);
    xhr.send = async function (body) {
      if (!_tunnel) return send(body);
      try {
        let b = body;
        if (typeof b === "string" || b == null || b instanceof Uint8Array) {
          /* ok */
        } else if (b instanceof ArrayBuffer) b = new Uint8Array(b);
        else b = String(b);
        const res = await mux.http(_method, toPath(_url), _headers, b);
        Object.defineProperty(xhr, "status", { value: res.status });
        Object.defineProperty(xhr, "statusText", { value: String(res.status) });
        Object.defineProperty(xhr, "responseText", { value: res.text });
        Object.defineProperty(xhr, "response", {
          value: xhr.responseType === "arraybuffer" ? res.body.buffer : res.text,
        });
        xhr.getAllResponseHeaders = () =>
          Object.entries(res.headers)
            .map(([k, v]) => k + ": " + v)
            .join("\r\n");
        xhr.getResponseHeader = (name) => res.headers[name.toLowerCase()] || res.headers[name] || null;
        xhr.readyState = 4;
        xhr.onreadystatechange?.();
        xhr.onload?.();
      } catch (e) {
        xhr.onerror?.(e);
      }
    };
    return xhr;
  };

  return function uninstall() {
    window.WebSocket = OrigWS;
    window.fetch = OrigFetch;
    window.XMLHttpRequest = OrigXHR;
  };
}
