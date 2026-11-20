/* Relays app_state / app_act from the StickLLM event stream to this tab. */
(function () {
  "use strict";
  const parts = location.pathname.split("/").filter(Boolean);
  const id = parts[0] === "apps" ? parts[1] : "";
  if (!id || typeof EventSource !== "function") return;

  function reply(kind, req, result) {
    const body = {
      id: id,
      req: req,
      kind: kind,
      ok: !!(result && result.ok !== false),
    };
    if (result && Object.prototype.hasOwnProperty.call(result, "state")) body.state = result.state;
    if (result && result.error) body.error = String(result.error);
    fetch("/api/ui/app-reply", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-StickLLM-Client": "ui" },
      body: JSON.stringify(body),
    }).catch(function () {});
  }

  function handle(kind, ev) {
    let data = {};
    try { data = JSON.parse(ev.data || "{}"); } catch (e) { return; }
    if (!data || data.id !== id || !data.req) return;
    // App tabs (desktop icon or open_app) are named "stickllm-<id>"; the
    // fallback panel's iframe is "stickllm-embed-<id>". Those answer even
    // when hidden, so Agent Zero can play while you look at another tab.
    const named = window.name === "stickllm-" + id || window.name === "stickllm-embed-" + id;
    if (document.visibilityState === "hidden" && !named) return;
    const api = window.stickllmApp;
    if (!api) {
      reply(kind, data.req, { ok: false, error: "no_adapter" });
      return;
    }
    try {
      const out = kind === "app_state" ? api.state() : api.act(data.action || {});
      const finish = function (value) {
        if (value && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "ok")) {
          reply(kind, data.req, value);
          return;
        }
        reply(kind, data.req, { ok: true, state: value });
      };
      if (out && typeof out.then === "function") {
        out.then(finish, function (err) { reply(kind, data.req, { ok: false, error: String(err) }); });
      } else {
        finish(out);
      }
    } catch (err) {
      reply(kind, data.req, { ok: false, error: String(err) });
    }
  }

  // 0.5.6 app agent: the chat page talks to this app over a same-origin
  // BroadcastChannel. It learns which app window was used last ("focus") and
  // reads / drives it ("call") with the same window.stickllmApp state()/act().
  if (typeof BroadcastChannel === "function") {
    try {
      const bc = new BroadcastChannel("stickllm-appbridge");
      // One window answers a call: the chat page names the window (inst) it last saw.
      const inst = Math.random().toString(36).slice(2, 10);
      const say = function (type) {
        try { bc.postMessage({ type: type, id: id, inst: inst, t: Date.now(), visible: document.visibilityState !== "hidden" }); } catch (e) {}
      };
      bc.onmessage = function (ev) {
        const m = ev.data || {};
        if (m.type === "who") { say("hello"); return; }
        if (m.type !== "call" || m.to !== id || !m.req) return;
        if (m.inst && m.inst !== inst) return;
        const api = window.stickllmApp;
        const send = function (ok, result, error) {
          try { bc.postMessage({ type: "reply", id: id, inst: inst, req: m.req, ok: ok, result: result, error: error || "" }); } catch (e) {}
        };
        if (!api) { send(false, null, "no_adapter"); return; }
        try {
          const out = m.kind === "state" ? api.state() : api.act(m.action || {});
          Promise.resolve(out).then(function (v) {
            if (v && typeof v === "object" && v.ok === false) send(false, v.state || null, String(v.error || "failed"));
            else send(true, v, "");
          }, function (err) { send(false, null, String(err)); });
        } catch (err) { send(false, null, String(err)); }
      };
      window.addEventListener("focus", function () { say("focus"); });
      document.addEventListener("pointerdown", function () { say("focus"); }, true);
      document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") say("focus"); });
      window.addEventListener("pagehide", function () { say("bye"); });
      say(document.hasFocus() ? "focus" : "hello");
    } catch (e) {}
  }

  // ?app= tells the gateway this screen has the app open, so app_state /
  // app_act go here and fail fast ("app_not_open") when no page has it.
  const events = new EventSource("/api/ui/events?app=" + encodeURIComponent(id));
  events.addEventListener("app_state", function (ev) { handle("app_state", ev); });
  events.addEventListener("app_act", function (ev) { handle("app_act", ev); });
  // A top-level app tab is up: the StickLLM tab closes its fallback panel for
  // this app, so only this page applies app_act.
  events.addEventListener("open", function () {
    if (window.top !== window || typeof BroadcastChannel !== "function") return;
    try { new BroadcastChannel("stickllm-apps").postMessage({ type: "tab-ready", id: id }); } catch (e) {}
  });
})();
