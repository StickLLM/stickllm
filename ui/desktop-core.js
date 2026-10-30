/* StickLLM desktop layout: pure logic (no DOM). Loaded by index.html before
 * desktop.js, and by tests/desktop_ui.test.js under Node. Window drawing comes
 * from WinBox.js (ui/vendor/winbox-0.2.82, Apache-2.0); this file only drives
 * a WinBox-like object, so tests can pass a fake. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.StickDeskCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const LAYOUT_KEY = "stickllm.uiLayout";      // auto | desktop | classic (per browser)
  const STATE_KEY = "stickllm.desk.v1";        // { geom: { id: {x,y,w,h,max} } }
  const MIN_W = 1024, MIN_H = 600;              // smallest viewport for auto desktop
  const TASKBAR_H = 48;
  const MIN_WIN_W = 240, MIN_WIN_H = 160;

  function normOverride(v) {
    v = String(v || "").toLowerCase();
    return v === "desktop" || v === "classic" ? v : "auto";
  }

  // Desktop when the main pointer is precise (mouse/trackpad), it can hover,
  // and the viewport is big enough; phones and touch tablets stay classic.
  // The per-device override wins either way.
  function detectLayout(o) {
    o = o || {};
    const ov = normOverride(o.override);
    if (ov !== "auto") return ov;
    const fine = !!o.pointerFine;
    const hover = o.hover === undefined ? fine : !!o.hover;
    const w = Number(o.width) || 0, h = Number(o.height) || 0;
    return fine && hover && w >= MIN_W && h >= MIN_H ? "desktop" : "classic";
  }

  function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

  // Keep a window fully reachable inside the work area (above the taskbar).
  function clampGeom(g, area) {
    const aw = Math.max(MIN_WIN_W, Math.floor(area.w)), ah = Math.max(MIN_WIN_H, Math.floor(area.h));
    let w = Math.round(Number(g.w) || 0), h = Math.round(Number(g.h) || 0);
    w = clamp(w || 640, MIN_WIN_W, aw);
    h = clamp(h || 480, MIN_WIN_H, ah);
    let x = Math.round(Number(g.x)), y = Math.round(Number(g.y));
    if (!isFinite(x)) x = Math.round((aw - w) / 2);
    if (!isFinite(y)) y = Math.round((ah - h) / 2);
    x = clamp(x, 0, aw - w);
    y = clamp(y, 0, ah - h);
    return { x: x, y: y, w: w, h: h };
  }

  // New windows: centred, then stepped down-right per open window.
  function cascade(size, n, area) {
    const step = 28;
    const w = Math.min(size.w, area.w - 40), h = Math.min(size.h, area.h - 40);
    const k = n % 8;
    const x = Math.round((area.w - w) / 2 - 3.5 * step + k * step);
    const y = Math.round((area.h - h) / 2 - 3 * step + k * step);
    return clampGeom({ x: x, y: y, w: w, h: h }, area);
  }

  // Taskbar button: bring back a minimised window, focus a background one,
  // minimise the one already in front.
  function taskbarAction(win) {
    if (!win) return "none";
    if (win.min) return "restore";
    if (win.focused) return "minimize";
    return "focus";
  }

  function memStore() {
    const m = new Map();
    return { get: (k) => (m.has(k) ? m.get(k) : null), set: (k, v) => { m.set(k, v); } };
  }
  function localStore(ls) {
    return {
      get(k) { try { const s = ls.getItem(k); return s == null ? null : s; } catch (e) { return null; } },
      set(k, v) { try { ls.setItem(k, v); } catch (e) {} },
    };
  }
  function readOverride(store) { return normOverride(store.get(LAYOUT_KEY)); }
  function writeOverride(store, v) { store.set(LAYOUT_KEY, normOverride(v)); }

  function loadState(store) {
    try {
      const s = JSON.parse(store.get(STATE_KEY) || "{}");
      if (s && typeof s === "object" && s.geom && typeof s.geom === "object") return { geom: s.geom };
    } catch (e) {}
    return { geom: {} };
  }

  // WindowManager: one window per app id. opts.create(params) returns a
  // WinBox (or a fake with the same surface). opts.area() is the work area
  // {w,h}; opts.onchange() fires after anything the taskbar shows changes.
  function WindowManager(opts) {
    this.create = opts.create;
    this.area = opts.area || (() => ({ w: 1280, h: 720 }));
    this.store = opts.store || memStore();
    this.onchange = opts.onchange || function () {};
    this.wins = new Map();       // id -> { spec, win }
    this.order = [];             // taskbar order (open order, pinned first)
    this.state = loadState(this.store);
  }
  WindowManager.prototype._changed = function () { try { this.onchange(); } catch (e) {} };
  WindowManager.prototype._save = function () {
    this.store.set(STATE_KEY, JSON.stringify({ geom: this.state.geom }));
  };
  WindowManager.prototype.remember = function (id) {
    const e = this.wins.get(id);
    if (!e || !e.win || e.win.min) return;
    const w = e.win, prev = this.state.geom[id] || {};
    if (w.max) this.state.geom[id] = Object.assign({}, prev, { max: true });
    else this.state.geom[id] = { x: w.x, y: w.y, w: w.width, h: w.height, max: false };
    this._save();
  };
  WindowManager.prototype.geomFor = function (spec) {
    const area = this.area();
    const saved = this.state.geom[spec.id];
    const size = { w: spec.w || 800, h: spec.h || 560 };
    if (saved && isFinite(saved.x) && isFinite(saved.w)) {
      return Object.assign(clampGeom(saved, area), { max: !!saved.max });
    }
    let n = 0;
    this.wins.forEach((e) => { if (!e.spec.pinned) n++; });
    return Object.assign(cascade(size, n, area), { max: !!(saved && saved.max) });
  };
  WindowManager.prototype.has = function (id) { return this.wins.has(id); };
  WindowManager.prototype.get = function (id) { const e = this.wins.get(id); return e ? e.win : null; };
  WindowManager.prototype.open = function (spec) {
    const have = this.wins.get(spec.id);
    if (have) {
      if (have.win.min) have.win.restore();
      have.win.focus();
      this._changed();
      return have.win;
    }
    const self = this, id = spec.id, g = this.geomFor(spec);
    const entry = { spec: spec, win: null };
    this.wins.set(id, entry);
    if (spec.pinned) this.order.unshift(id); else this.order.push(id);
    const params = Object.assign({}, spec.params || {}, {
      id: "win-" + id,
      title: spec.title,
      x: g.x, y: g.y, width: g.w, height: g.h,
      top: 0, left: 0, right: 0, bottom: spec.bottom == null ? TASKBAR_H : spec.bottom,
      minwidth: MIN_WIN_W, minheight: MIN_WIN_H,
      onfocus: function () { self._changed(); spec.onfocus && spec.onfocus(this); },
      onblur: function () { self._changed(); },
      onminimize: function () { self._changed(); },
      onmaximize: function () { self.remember(id); self._changed(); },
      onrestore: function () { self.remember(id); self._changed(); },
      onmove: function () { self._remSoon(id); },
      onresize: function () { self._remSoon(id); },
      onclose: function (force) {
        // Pinned windows (Chat) are the shell: closing them minimises.
        if (spec.pinned && !force) { this.minimize(); self._changed(); return true; }
        if (spec.onclose && spec.onclose(this, force) === true && !force) return true;
        self.wins.delete(id);
        self.order = self.order.filter((x) => x !== id);
        setTimeout(() => self._changed(), 0);
        return false;
      },
    });
    entry.win = this.create(params, spec);
    if (g.max) entry.win.maximize();
    entry.win.focus();
    this._changed();
    return entry.win;
  };
  WindowManager.prototype._remSoon = function (id) {
    clearTimeout(this._remT);
    this._remT = setTimeout(() => this.remember(id), 250);
  };
  WindowManager.prototype.activeId = function () {
    let a = null;
    this.wins.forEach((e, id) => { if (e.win && e.win.focused && !e.win.min) a = id; });
    return a;
  };
  WindowManager.prototype.focus = function (id) {
    const w = this.get(id); if (!w) return false;
    if (w.min) w.restore();
    w.focus(); this._changed(); return true;
  };
  WindowManager.prototype.minimize = function (id) {
    const w = this.get(id); if (!w) return false;
    w.minimize(); this._changed(); return true;
  };
  WindowManager.prototype.toggleMax = function (id) {
    const w = this.get(id); if (!w) return false;
    if (w.max) w.restore(); else w.maximize();
    w.focus(); this._changed(); return true;
  };
  WindowManager.prototype.close = function (id, force) {
    const w = this.get(id); if (!w) return false;
    w.close(!!force);
    return !this.wins.has(id);
  };
  WindowManager.prototype.taskbarClick = function (id) {
    const w = this.get(id);
    const act = taskbarAction(w);
    if (act === "restore" || act === "focus") this.focus(id);
    else if (act === "minimize") this.minimize(id);
    return act;
  };
  // Lock / leaving the layout: every app window goes (vault data); pinned
  // windows stay unless all=true.
  WindowManager.prototype.closeAll = function (all) {
    const ids = this.order.slice();
    ids.forEach((id) => {
      const e = this.wins.get(id);
      if (!e) return;
      if (e.spec.pinned && !all) return;
      try { e.win.close(true); } catch (err) {}
      this.wins.delete(id);
    });
    this.order = this.order.filter((id) => this.wins.has(id));
    this._changed();
  };
  // Ctrl+Alt+N: next non-active window in taskbar order (restores minimised).
  WindowManager.prototype.next = function () {
    if (!this.order.length) return null;
    const cur = this.activeId();
    const i = cur ? this.order.indexOf(cur) : -1;
    const id = this.order[(i + 1) % this.order.length];
    this.focus(id);
    return id;
  };
  WindowManager.prototype.list = function () {
    const act = this.activeId();
    return this.order.map((id) => {
      const e = this.wins.get(id);
      return {
        id: id, title: e.spec.title, icon: e.spec.icon || "", pinned: !!e.spec.pinned,
        min: !!e.win.min, max: !!e.win.max, active: id === act,
      };
    });
  };
  // Browser window resized: keep every window reachable.
  WindowManager.prototype.fit = function () {
    const area = this.area();
    this.wins.forEach((e) => {
      const w = e.win;
      if (!w || w.min) return;
      if (w.max) { w.restore(); w.maximize(); return; }
      const g = clampGeom({ x: w.x, y: w.y, w: w.width, h: w.height }, area);
      if (g.w !== w.width || g.h !== w.height) w.resize(g.w, g.h);
      if (g.x !== w.x || g.y !== w.y) w.move(g.x, g.y);
    });
  };

  return {
    LAYOUT_KEY: LAYOUT_KEY, STATE_KEY: STATE_KEY, TASKBAR_H: TASKBAR_H,
    MIN_W: MIN_W, MIN_H: MIN_H,
    normOverride: normOverride, detectLayout: detectLayout,
    clampGeom: clampGeom, cascade: cascade, taskbarAction: taskbarAction,
    memStore: memStore, localStore: localStore,
    readOverride: readOverride, writeOverride: writeOverride, loadState: loadState,
    WindowManager: WindowManager,
  };
});
