/* StickLLM desktop layout (DOM side). Plan: PLAN-desktop-ui.md.
 * Windows: WinBox.js 0.2.82, vendored at vendor/winbox-0.2.82/ (Apache-2.0,
 * see THIRD_PARTY_NOTICES.md). Loaded only when the desktop layout starts.
 * Runs after app.js and reuses its globals (openSettings, showApps,
 * lockVault, toast). Classic/mobile layout is left exactly as it was. */
(function () {
  "use strict";
  const core = window.StickDeskCore;
  if (!core || !document.getElementById("app")) return;
  const WINBOX_SRC = "vendor/winbox-0.2.82/winbox.bundle.min.js";
  const store = core.localStore(window.localStorage);
  const $ = (s, r) => (r || document).querySelector(s);

  // Bundled starter apps: window size and the name shown in the launcher.
  const APPS = {
    files: { title: "Files", w: 920, h: 600 },
    notepad: { title: "Notepad", w: 780, h: 540 },
    calculator: { title: "Calculator", w: 360, h: 560 },
    minesweeper: { title: "Minesweeper", w: 940, h: 680 },
    solitaire: { title: "Solitaire", w: 1040, h: 720 },
    tetris: { title: "Tetris", w: 620, h: 760 },
    media: { title: "Media", w: 900, h: 600 },
    monitor: { title: "System monitor", w: 760, h: 540 },
  };
  const CHAT = "chat";

  let on = false;
  // Published by app.js (window.stickApp); absent until app.js has run.
  const appApi = () => window.stickApp || {};
  let wm = null;
  let ui = null;           // nodes we created
  let moved = [];          // [{node, parent, next}] to put back on leave
  let starting = null;

  function iconFor(id) {
    if (id === CHAT) {
      const s = document.createElement("span");
      s.className = "deskGlyph";
      s.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4z"/></svg>';
      return s;
    }
    const g = $('#deskIcons a.deskIcon[data-starter="' + id + '"] .deskGlyph');
    if (g) return g.cloneNode(true);
    const s = document.createElement("span");
    s.className = "deskGlyph";
    return s;
  }
  function appHref(id) {
    const a = $('#deskIcons a.deskIcon[data-starter="' + id + '"]');
    return (a && a.getAttribute("href")) || "/apps/" + id + "/";
  }

  function wantDesktop() {
    return core.detectLayout({
      pointerFine: matchMedia("(pointer:fine)").matches,
      hover: matchMedia("(hover:hover)").matches,
      width: window.innerWidth,
      height: window.innerHeight,
      override: core.readOverride(store),
    }) === "desktop";
  }

  function loadWinBox() {
    if (window.WinBox) return Promise.resolve(window.WinBox);
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = WINBOX_SRC;
      s.onload = () => (window.WinBox ? resolve(window.WinBox) : reject(new Error("WinBox missing")));
      s.onerror = () => reject(new Error("WinBox failed to load"));
      document.head.appendChild(s);
    });
  }

  function move(node, parent, before) {
    if (!node) return;
    moved.push({ node: node, parent: node.parentNode, next: node.nextSibling });
    parent.insertBefore(node, before || null);
  }
  function putBack() {
    for (let i = moved.length - 1; i >= 0; i--) {
      const m = moved[i];
      try { m.parent.insertBefore(m.node, m.next && m.next.parentNode === m.parent ? m.next : null); } catch (e) {}
    }
    moved = [];
  }

  // ---------- DOM ----------
  function el(tag, cls, html) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  const SVG = {
    lockOpen: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 017.7-1.5"/></svg>',
    lockShut: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/></svg>',
    net: '<svg viewBox="0 0 24 24"><path d="M2 8.5a15 15 0 0120 0M5 12a10 10 0 0114 0M8.5 15.5a5 5 0 017 0"/><circle cx="12" cy="19" r="1.2" fill="currentColor"/></svg>',
    netOff: '<svg viewBox="0 0 24 24"><path d="M2 8.5a15 15 0 0120 0M5 12a10 10 0 0114 0M8.5 15.5a5 5 0 017 0"/><circle cx="12" cy="19" r="1.2" fill="currentColor"/><path d="M4 4l16 16"/></svg>',
    gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>',
    apps: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>',
    classic: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>',
  };

  function build() {
    const layer = el("div", "deskLayer");
    layer.id = "deskLayer";
    const wall = el("div", "deskWall");
    wall.id = "deskWall";
    wall.setAttribute("role", "list");
    wall.setAttribute("aria-label", "Desktop");
    [CHAT].concat(Object.keys(APPS)).forEach((id) => {
      const b = el("button", "wallIcon");
      b.type = "button";
      b.dataset.app = id;
      b.setAttribute("role", "listitem");
      b.title = "Open " + (id === CHAT ? "Chat" : APPS[id].title) + " (double-click)";
      b.appendChild(iconFor(id));
      b.appendChild(el("span", "wallLabel")).textContent = id === CHAT ? "Chat" : APPS[id].title;
      wall.appendChild(b);
    });
    wall.addEventListener("dblclick", (e) => {
      const b = e.target.closest(".wallIcon");
      if (b) openApp(b.dataset.app);
    });
    wall.addEventListener("keydown", (e) => {
      const b = e.target.closest(".wallIcon");
      if (b && e.key === "Enter") { e.preventDefault(); openApp(b.dataset.app); }
    });
    layer.appendChild(wall);

    const bar = el("nav", "taskbar");
    bar.id = "taskbar";
    bar.setAttribute("aria-label", "Taskbar");
    const start = el("button", "startBtn", '<span class="logo" aria-hidden="true"></span><span>Start</span>');
    start.type = "button";
    start.id = "startBtn";
    start.title = "Apps (Ctrl+Alt+Space)";
    start.setAttribute("aria-haspopup", "menu");
    start.setAttribute("aria-expanded", "false");
    start.addEventListener("click", (e) => { e.stopPropagation(); toggleLauncher(); });
    const tasks = el("div", "taskApps");
    tasks.id = "taskApps";
    tasks.setAttribute("role", "toolbar");
    tasks.setAttribute("aria-label", "Open windows");
    tasks.addEventListener("click", (e) => {
      const b = e.target.closest(".taskBtn");
      if (b && wm) wm.taskbarClick(b.dataset.app);
    });
    const tray = el("div", "tray");
    tray.id = "deskTray";
    bar.append(start, tasks, tray);
    // WinBox blurs the active window on any body mousedown outside a window.
    // The taskbar and launcher must not count: "click the active window's
    // button to minimise it" needs the window to still be active at click.
    const keepFocus = (e) => e.stopPropagation();
    bar.addEventListener("mousedown", keepFocus);

    const launcher = el("div", "launcher");
    launcher.id = "launcher";
    launcher.addEventListener("mousedown", keepFocus);
    launcher.hidden = true;
    launcher.setAttribute("role", "dialog");
    launcher.setAttribute("aria-label", "Launcher");
    launcher.innerHTML =
      '<input type="search" class="launchSearch" id="launchSearch" placeholder="Search apps" aria-label="Search apps" autocomplete="off">' +
      '<div class="launchHead">Apps</div><div class="launchGrid" id="launchGrid" role="menu"></div>' +
      '<div class="launchFoot" id="launchFoot"></div>';
    const grid = launcher.querySelector("#launchGrid");
    [CHAT].concat(Object.keys(APPS)).forEach((id) => {
      const b = el("button", "launchItem");
      b.type = "button";
      b.dataset.app = id;
      b.setAttribute("role", "menuitem");
      b.appendChild(iconFor(id));
      b.appendChild(el("span", "launchLabel")).textContent = id === CHAT ? "Chat" : APPS[id].title;
      grid.appendChild(b);
    });
    const foot = launcher.querySelector("#launchFoot");
    const footBtn = (key, label, svg) => {
      const b = el("button", "launchAct", svg + "<span></span>");
      b.type = "button";
      b.dataset.act = key;
      b.querySelector("span").textContent = label;
      foot.appendChild(b);
      return b;
    };
    footBtn("apps", "Apps & installs", SVG.apps);
    footBtn("settings", "Settings", SVG.gear);
    footBtn("lock", "Lock vault", SVG.lockShut).hidden = true;
    footBtn("classic", "Classic layout", SVG.classic);
    launcher.addEventListener("click", (e) => {
      const it = e.target.closest(".launchItem");
      if (it) { toggleLauncher(false); openApp(it.dataset.app); return; }
      const act = e.target.closest(".launchAct");
      if (act) { toggleLauncher(false); launcherAction(act.dataset.act); }
    });
    launcher.querySelector("#launchSearch").addEventListener("input", filterLauncher);
    launcher.querySelector("#launchSearch").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = [...grid.children].find((b) => !b.hidden);
        if (first) { e.preventDefault(); toggleLauncher(false); openApp(first.dataset.app); }
      } else if (e.key === "ArrowDown") {
        const first = [...grid.children].find((b) => !b.hidden);
        if (first) { e.preventDefault(); first.focus(); }
      }
    });
    grid.addEventListener("keydown", (e) => {
      const items = [...grid.children].filter((b) => !b.hidden);
      const i = items.indexOf(document.activeElement);
      if (i < 0) return;
      const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 4, ArrowUp: -4 }[e.key];
      if (step) { e.preventDefault(); const n = items[i + step]; (n || (step < 0 ? launcher.querySelector("#launchSearch") : items[items.length - 1])).focus(); }
    });

    document.body.append(layer, bar, launcher);
    return { layer: layer, wall: wall, bar: bar, start: start, tasks: tasks, tray: tray, launcher: launcher };
  }

  function filterLauncher() {
    const q = ui.launcher.querySelector("#launchSearch").value.trim().toLowerCase();
    ui.launcher.querySelectorAll(".launchItem").forEach((b) => {
      b.hidden = !!q && !b.textContent.toLowerCase().includes(q) && !b.dataset.app.includes(q);
    });
  }
  function toggleLauncher(force) {
    if (!ui) return;
    const open = force == null ? ui.launcher.hidden : !!force;
    ui.launcher.hidden = !open;
    ui.start.setAttribute("aria-expanded", String(open));
    ui.start.classList.toggle("on", open);
    if (open) {
      const lock = ui.launcher.querySelector('[data-act="lock"]');
      lock.hidden = vaultState() !== "open";
      const s = ui.launcher.querySelector("#launchSearch");
      s.value = "";
      filterLauncher();
      setTimeout(() => s.focus(), 0);
    }
  }
  function launcherAction(act) {
    if (act === "settings") { if (appApi().openSettings) appApi().openSettings(); }
    else if (act === "lock") { if (appApi().lockVault) appApi().lockVault(); }
    else if (act === "apps") { openApp(CHAT); if (appApi().showApps) appApi().showApps(); }
    else if (act === "classic") { core.writeOverride(store, "classic"); syncLayoutSeg(); evaluate(); }
  }

  // ---------- tray ----------
  function vaultState() {
    const t = (($("#popVault") || {}).textContent || "").trim().toLowerCase();
    if (t === "unlocked") return "open";
    if (t === "not set up") return "none";
    return "locked";
  }
  function buildTray() {
    const tray = ui.tray;
    const pairSrc = $(".topPair");
    if (pairSrc) {
      const p = pairSrc.cloneNode(true);
      p.classList.remove("topPair");
      p.classList.add("trayBtn", "trayPair");
      p.addEventListener("click", (e) => { e.preventDefault(); pairSrc.click(); });
      tray.appendChild(p);
    }
    const chipWrap = el("div", "trayChip");
    tray.appendChild(chipWrap);
    move($("#statusChip"), chipWrap);
    move($("#statusPop"), chipWrap);
    const net = el("button", "trayBtn trayNet");
    net.type = "button";
    net.id = "trayNet";
    net.addEventListener("click", () => { if (appApi().openSettings) appApi().openSettings("network"); });
    const vault = el("button", "trayBtn trayVault");
    vault.type = "button";
    vault.id = "trayVault";
    vault.addEventListener("click", () => {
      if (vaultState() === "open") { if (appApi().lockVault) appApi().lockVault(); }
      else if (appApi().openSettings) appApi().openSettings("storage");
    });
    const theme = el("button", "trayBtn trayTheme", '<svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>');
    theme.type = "button";
    theme.title = "Toggle theme";
    theme.setAttribute("aria-label", "Toggle light/dark theme");
    theme.addEventListener("click", () => { const t = $("#themeBtn"); if (t) t.click(); });
    const clock = el("div", "trayClock");
    clock.id = "trayClock";
    tray.append(net, vault, theme, clock);
    syncTray();
    const obs = new MutationObserver(syncTray);
    ["#popVault", "#popUplink", "#chipModel"].forEach((s) => {
      const n = $(s);
      if (n) obs.observe(n, { childList: true, characterData: true, subtree: true });
    });
    ui.obs = obs;
    tickClock();
    ui.clockT = setInterval(tickClock, 15000);
  }
  function tickClock() {
    const c = $("#trayClock");
    if (!c) return;
    const d = new Date();
    c.textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    c.title = d.toLocaleDateString([], { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  }
  function syncTray() {
    const net = $("#trayNet"), vault = $("#trayVault");
    if (net) {
      const up = (($("#popUplink") || {}).textContent || "").trim();
      const model = (($("#chipModel") || {}).textContent || "").trim();
      let st = "unknown", label = "Network: checking";
      if (/not answering/i.test(model)) { st = "down"; label = "Network: stick not answering"; }
      else if (/^online$/i.test(up)) { st = "ok"; label = "Network: online (uplink)"; }
      else if (up && up !== "\u2014") { st = "local"; label = "Network: " + up + " (local only)"; }
      net.dataset.state = st;
      net.innerHTML = st === "ok" || st === "unknown" ? SVG.net : SVG.netOff;
      net.title = label + " \u2014 click for Network settings";
      net.setAttribute("aria-label", label);
    }
    if (vault) {
      const v = vaultState();
      const label = v === "open" ? "Vault unlocked \u2014 click to lock (Ctrl+Shift+L)"
        : v === "none" ? "Vault not set up \u2014 click for Storage & Vault" : "Vault locked \u2014 click for Storage & Vault";
      vault.dataset.state = v;
      vault.innerHTML = v === "open" ? SVG.lockOpen : SVG.lockShut;
      vault.title = label;
      vault.setAttribute("aria-label", label);
    }
  }

  // ---------- taskbar ----------
  let renderQ = false;
  function renderTasks() {
    if (renderQ) return;
    renderQ = true;
    requestAnimationFrame(() => {
      renderQ = false;
      if (!ui || !wm) return;
      const list = wm.list();
      const have = new Map([...ui.tasks.children].map((b) => [b.dataset.app, b]));
      list.forEach((w, i) => {
        let b = have.get(w.id);
        if (!b) {
          b = el("button", "taskBtn");
          b.type = "button";
          b.dataset.app = w.id;
          b.appendChild(iconFor(w.id));
          b.appendChild(el("span", "taskLabel"));
        }
        have.delete(w.id);
        b.querySelector(".taskLabel").textContent = w.title;
        b.classList.toggle("active", w.active);
        b.classList.toggle("min", w.min);
        b.setAttribute("aria-pressed", String(w.active));
        b.title = w.title + (w.min ? " (minimised) \u2014 click to restore" : w.active ? " \u2014 click to minimise" : " \u2014 click to bring to front");
        if (ui.tasks.children[i] !== b) ui.tasks.insertBefore(b, ui.tasks.children[i] || null);
      });
      have.forEach((b) => b.remove());
      document.body.classList.toggle("deskHasActive", !!wm.activeId());
    });
  }

  // ---------- windows ----------
  function frameHooks(frame, id) {
    // Clicks inside a same-origin app don't reach this page: focus the window
    // ourselves, and forward the global shortcuts (lock first of all).
    frame.addEventListener("load", () => {
      let w;
      try { w = frame.contentWindow; void w.document; } catch (e) { return; }
      try {
        w.addEventListener("pointerdown", () => { if (wm) wm.focus(id); }, true);
        // "Back to Apps" / "StickLLM" links point at the main page, which
        // refuses to be framed. In a window they mean "back to the desktop".
        w.addEventListener("click", (e) => {
          if (e.defaultPrevented || e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
          const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
          if (!a) return;
          let u;
          try { u = new URL(a.getAttribute("href"), w.location.href); } catch (_) { return; }
          if (u.origin !== location.origin || u.pathname !== "/") return;
          e.preventDefault();
          try { frame.blur(); window.focus(); } catch (_) {}
          if (wm) wm.minimize(id);
          if (u.hash === "#apps") toggleLauncher(true);
          else if (wm) wm.focus(CHAT);
        }, true);
        w.addEventListener("keydown", (e) => {
          if (!isGlobalKey(e)) return;
          e.preventDefault();
          e.stopPropagation();
          window.dispatchEvent(new KeyboardEvent("keydown", {
            key: e.key, code: e.code, ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey,
            repeat: e.repeat, bubbles: true, cancelable: true,
          }));
        }, true);
      } catch (e) {}
    });
  }
  function isGlobalKey(e) {
    const k = (e.key || "").toLowerCase();
    if (e.key === "F9" || e.key === "F10") return true;
    if (e.ctrlKey && e.shiftKey && k === "l") return true;
    if (e.ctrlKey && e.altKey && !e.shiftKey) return [" ", "w", "m", "n", "c", "arrowup"].includes(k);
    return false;
  }

  function createWin(params, spec) {
    const wb = new window.WinBox(Object.assign(params, {
      root: ui.layer,
      class: ["no-full", "dk-win", "dk-" + spec.id],
    }));
    if (spec.mountNode) wb.mount(spec.mountNode);
    else {
      const f = document.createElement("iframe");
      f.name = "stickllm-" + spec.id;          // the app bridge answers Agent Zero for named apps
      f.title = spec.title;
      f.src = spec.url;
      f.setAttribute("allow", "fullscreen; clipboard-read; clipboard-write; autoplay");
      frameHooks(f, spec.id);
      wb.body.appendChild(f);
    }
    return wb;
  }

  function openApp(id) {
    if (!on || !wm) return null;
    if (id === CHAT) {
      const w = wm.open(chatSpec());
      return w;
    }
    if (!Object.prototype.hasOwnProperty.call(APPS, id)) return null;
    const a = APPS[id];
    return wm.open({ id: id, title: a.title, w: a.w, h: a.h, url: appHref(id) });
  }
  function chatSpec() {
    return { id: CHAT, title: "Chat", w: 1000, h: 720, pinned: true, mountNode: $("#app") };
  }

  // ---------- enter / leave ----------
  async function enter() {
    if (on || starting) return starting;
    starting = (async () => {
      try { await loadWinBox(); } catch (e) {
        if (appApi().toast) appApi().toast("Desktop layout unavailable: " + e.message);
        return;
      }
      if (!wantDesktop()) return;
      on = true;
      document.body.classList.add("deskMode");
      ui = build();
      // Overlays must not sit inside a window (WinBox windows contain
      // fixed-position children): dialogs, load bar and toast go to <body>.
      document.querySelectorAll("#app > .modalWrap, #app > #loadStatus, #app > #toast").forEach((n) => move(n, document.body));
      buildTray();
      wm = new core.WindowManager({
        create: createWin,
        store: store,
        area: () => ({ w: window.innerWidth, h: window.innerHeight - core.TASKBAR_H }),
        onchange: renderTasks,
      });
      openApp(CHAT);
      window.addEventListener("resize", onResize);
      renderTasks();
      syncLayoutSeg();
    })();
    try { await starting; } finally { starting = null; }
  }
  function leave() {
    if (!on) return;
    on = false;
    toggleLauncher(false);
    try { wm.closeAll(true); } catch (e) {}
    const appNode = $("#app");
    if (appNode && appNode.parentNode !== document.body) document.body.insertBefore(appNode, document.body.firstChild);
    putBack();
    if (ui) {
      if (ui.obs) ui.obs.disconnect();
      clearInterval(ui.clockT);
      ui.layer.remove(); ui.bar.remove(); ui.launcher.remove();
    }
    ui = null;
    wm = null;
    window.removeEventListener("resize", onResize);
    document.body.classList.remove("deskMode", "deskHasActive");
    syncLayoutSeg();
  }
  let resizeT = 0;
  function onResize() {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => { if (wm) wm.fit(); }, 120);
  }
  let evalT = 0;
  function evaluate() {
    clearTimeout(evalT);
    evalT = setTimeout(() => {
      const want = wantDesktop();
      if (want && !on) enter();
      else if (!want && on) leave();
      syncLayoutSeg();
    }, 60);
  }

  // ---------- settings: Layout ----------
  function syncLayoutSeg() {
    const v = core.readOverride(store);
    document.querySelectorAll("#layoutSeg button").forEach((b) => b.classList.toggle("on", b.dataset.layout === v));
    const now = $("#layoutNow");
    if (now) now.textContent = "Now: " + (on ? "desktop" : "classic") + (v === "auto" ? " (auto)" : "");
  }
  document.querySelectorAll("#layoutSeg button").forEach((b) => {
    b.addEventListener("click", () => { core.writeOverride(store, b.dataset.layout); syncLayoutSeg(); evaluate(); });
  });

  // ---------- keys ----------
  window.addEventListener("keydown", (e) => {
    if (!on) return;
    const k = (e.key || "").toLowerCase();
    if (e.key === "Escape" && ui && !ui.launcher.hidden) {
      e.preventDefault(); e.stopImmediatePropagation(); toggleLauncher(false); ui.start.focus(); return;
    }
    if (!(e.ctrlKey && e.altKey) || e.shiftKey) return;
    const act = wm && wm.activeId();
    let done = true;
    if (k === " ") toggleLauncher();
    else if (k === "c") openApp(CHAT);
    else if (k === "n") wm.next();
    else if (k === "w" && act) wm.close(act);
    else if (k === "m" && act) wm.minimize(act);
    else if (k === "arrowup" && act) wm.toggleMax(act);
    else done = false;
    if (done) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  document.addEventListener("pointerdown", (e) => {
    if (!ui || ui.launcher.hidden) return;
    if (!ui.launcher.contains(e.target) && !ui.start.contains(e.target)) toggleLauncher(false);
  }, true);
  // Same-origin app iframes take focus without a click reaching us (keyboard,
  // programmatic): when this page blurs into an app frame, mark it active.
  window.addEventListener("blur", () => {
    setTimeout(() => {
      const a = document.activeElement;
      if (!wm || !a || a.tagName !== "IFRAME") return;
      const box = a.closest(".winbox");
      const id = box && box.id && box.id.replace(/^win-/, "");
      const w = id && wm.has(id) ? wm.get(id) : null;
      if (w && !w.min && wm.activeId() !== id) wm.focus(id);
    }, 0);
  });

  // Public hooks for app.js.
  window.stickDesk = {
    active: () => on,
    handles: (id) => on && Object.prototype.hasOwnProperty.call(APPS, id),
    openApp: (id) => openApp(id),
    closeAll: () => { if (wm) wm.closeAll(false); toggleLauncher(false); },
    list: () => (wm ? wm.list() : []),
    _wm: () => wm,
    evaluate: evaluate,
  };

  ["(pointer:fine)", "(hover:hover)"].forEach((q) => {
    try { matchMedia(q).addEventListener("change", evaluate); } catch (e) {}
  });
  window.addEventListener("resize", evaluate);
  syncLayoutSeg();
  evaluate();
})();
