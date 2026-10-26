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
    const named = window.name === "stickllm-" + id;
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

  const events = new EventSource("/api/ui/events");
  events.addEventListener("app_state", function (ev) { handle("app_state", ev); });
  events.addEventListener("app_act", function (ev) { handle("app_act", ev); });
})();
