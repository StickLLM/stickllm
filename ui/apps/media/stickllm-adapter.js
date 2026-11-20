/* Drive the Media page for the app agent. Clicks the page's own buttons. */
(function () {
  "use strict";

  function $(s) { return document.querySelector(s); }

  function entries() {
    const out = [];
    document.querySelectorAll("#files button").forEach(function (btn) {
      const text = String(btn.textContent || "").trim();
      const folder = text.indexOf("Folder") === 0;
      out.push({ name: folder ? text.replace(/^Folder\s+/, "") : text, dir: folder });
    });
    return out;
  }

  function stageEl() {
    const stage = $("#stage");
    return stage ? stage.querySelector("img,audio,video") : null;
  }

  function state() {
    const el = stageEl();
    return {
      root: document.body.dataset.mediaRoot || (($("#root") && $("#root").value) || ""),
      path: document.body.dataset.mediaPath || "",
      entries: entries(),
      file: el ? (el.alt || "") : "",
      kind: el ? el.tagName.toLowerCase() : "",
      paused: !!(el && el.paused),
    };
  }

  function buttonFor(name) {
    const want = String(name || "").trim();
    let hit = null;
    document.querySelectorAll("#files button").forEach(function (btn) {
      const text = String(btn.textContent || "").trim();
      const folder = text.indexOf("Folder") === 0;
      const label = folder ? text.replace(/^Folder\s+/, "") : text;
      if (label === want) hit = btn;
    });
    return hit;
  }

  function act(action) {
    action = action || {};
    if (action.up) {
      const up = $("#up");
      if (!up) return { ok: false, error: "no_up", state: state() };
      up.click();
      return waitState();
    }
    if (action.root) {
      const sel = $("#root");
      if (!sel) return { ok: false, error: "no_root", state: state() };
      const id = String(action.root);
      const ok = Array.prototype.some.call(sel.options, function (o) { return o.value === id; });
      if (!ok) return { ok: false, error: "unknown_root", state: state() };
      sel.value = id;
      sel.dispatchEvent(new Event("change"));
      return waitState();
    }
    if (action.open) {
      const btn = buttonFor(action.open);
      if (!btn) return { ok: false, error: "not_in_this_folder", state: state() };
      btn.click();
      return waitState();
    }
    if (action.play || action.pause) {
      const el = stageEl();
      if (!el || el.tagName === "IMG") return { ok: false, error: "nothing_to_play", state: state() };
      if (action.pause) el.pause();
      else {
        const p = el.play();
        if (p && typeof p.catch === "function") p.catch(function () {});
      }
      return waitState();
    }
    return { ok: false, error: "unknown_action", state: state() };
  }

  function waitState() {
    return new Promise(function (resolve) {
      setTimeout(function () { resolve({ ok: true, state: state() }); }, 400);
    });
  }

  window.stickllmApp = {
    describe: function () {
      return { id: "media", actions: ["open", "up", "root", "play", "pause"] };
    },
    state: state,
    act: act,
  };
})();
