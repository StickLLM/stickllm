/* StickLLM desktop layout (DOM side). Plan: PLAN-desktop-ui.md.
 * Windows: WinBox.js 0.2.82, vendored at vendor/winbox-0.2.82/ (Apache-2.0,
 * see THIRD_PARTY_NOTICES.md). Loaded only when the desktop layout starts.
 * Runs after app.js and reuses its globals (openSettings, showApps,
 * lockVault, toast). Classic/mobile layout is left exactly as it was.
 * 0.5.6: the chat window is chat only. Settings, Models, the App Store,
 * the Agent and the Browser are their own desktop apps; installed catalog
 * apps get a desktop icon and a launcher entry; the taskbar carries the
 * Ephemeral/Vault switch (with unlock) and the model button. */
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
  // StickLLM's own apps (0.5.6). Settings, Models and the App Store mount the
  // existing panels from index.html; Agent and catalog apps are iframes.
  const SYS = {
    // 0.6.5: one Agent Zero window (legacy StickLLM Chat chrome + icon retired).
    chat: { title: "Agent Zero", w: 1180, h: 800 },
    browser: { title: "Browser", w: 1180, h: 780 },
    agent: { title: "Agent Zero", w: 1180, h: 800 },
    store: { title: "App Store", w: 1000, h: 700 },
    models: { title: "Models", w: 1060, h: 740 },
    settings: { title: "Settings", w: 1000, h: 720 },
  };
  const GLYPH = {
    agent: '<svg viewBox="0 0 24 24"><rect x="5" y="7" width="14" height="11" rx="2"/><path d="M12 3v4M9 12h.01M15 12h.01"/></svg>',
    browser: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/></svg>',
    store: '<svg viewBox="0 0 24 24"><path d="M5 8h14l-1 12H6z"/><path d="M9 8V6a3 3 0 016 0v2"/></svg>',
    models: '<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>',
    settings: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 010-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 014 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 010 4h-.1a1.7 1.7 0 00-1.5 1z"/></svg>',
  };
  // Desktop order: Agent Zero once (no separate Chat icon), then Browser /
  // Store; starter + catalog apps; Models/Settings at the end.
  const FRONT = ["agent", "browser", "store"];
  const BACK = ["models", "settings"];
  let catalog = [];         // [{id,title,label,color,svg,frame,running,state}] from app.js
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const catalogApp = (id) => catalog.find((a) => a.id === id) || null;
  function appTitle(id) {
    if (has(SYS, id)) return SYS[id].title;
    if (has(APPS, id)) return APPS[id].title;
    const c = catalogApp(id);
    return c ? c.title : id;
  }
  function appOrder() {
    return FRONT.concat(Object.keys(APPS), catalog.map((a) => a.id), BACK);
  }

  let on = false;
  // Published by app.js (window.stickApp); absent until app.js has run.
  const appApi = () => window.stickApp || {};
  let wm = null;
  let ui = null;           // nodes we created
  let moved = [];          // [{node, parent, next}] to put back on leave
  let starting = null;

  function iconFor(id) {
    if (has(GLYPH, id)) {
      const s = document.createElement("span");
      s.className = "deskGlyph";
      s.innerHTML = GLYPH[id];
      return s;
    }
    if (id === "agent" || id === CHAT) {
      const s = document.createElement("span");
      s.className = "deskGlyph deskGlyphImg";
      s.innerHTML = '<img src="agent-zero.png?v=desk4" alt="">';
      return s;
    }
    const c = catalogApp(id);
    if (c) {
      const s = document.createElement("span");
      s.className = "deskGlyph deskGlyphCat";
      if (c.color) s.style.background = c.color;
      if (c.svg) s.innerHTML = /^\s*<svg/.test(c.svg) ? c.svg : '<svg viewBox="0 0 24 24">' + c.svg + "</svg>";
      else s.textContent = (c.label || c.title || "?").slice(0, 2);
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

  // 0.5.6: on the stick's own screen this page is a window on the Xfce
  // desktop (stickllm-xfce-open adds ?shell=xfce), which already gives real
  // windows and a taskbar, so "auto" keeps the classic page there.
  function hostShell() {
    try {
      if (/[?&]shell=xfce(?:&|$)/.test(location.search)) sessionStorage.setItem("stickllm.shell", "xfce");
      return sessionStorage.getItem("stickllm.shell") || "";
    } catch (e) { return ""; }
  }
  function wantDesktop() {
    if (hostShell() === "xfce" && core.readOverride(store) === "auto") return false;
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
      if (b && b.classList.contains("taskExt")) {
        // Like any taskbar: minimised -> restore, front -> minimise, else bring to front.
        browserOp(b.dataset.ext, "toggle");
        return;
      }
      if (b && wm) {
        // 0.6.2: a Chrome window sits above the whole desktop page, so a
        // "focused" app window behind it is not really in front. Raise it
        // (minimise the browser windows) instead of minimising it.
        if (browserCovers()) { yieldBrowser(); wm.focus(b.dataset.app); }
        else wm.taskbarClick(b.dataset.app);
      }
    });
    // Right-click a browser button: Restore / Minimise / Maximise / Close.
    tasks.addEventListener("contextmenu", (e) => {
      const b = e.target.closest(".taskBtn.taskExt");
      if (!b) return;
      e.preventDefault();
      showBrowserMenu(b);
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
    const foot = launcher.querySelector("#launchFoot");
    const footBtn = (key, label, svg) => {
      const b = el("button", "launchAct", svg + "<span></span>");
      b.type = "button";
      b.dataset.act = key;
      b.querySelector("span").textContent = label;
      foot.appendChild(b);
      return b;
    };
    footBtn("apps", "App Store", SVG.apps);
    footBtn("settings", "Settings", SVG.gear);
    footBtn("lock", "Lock vault", SVG.lockShut).hidden = true;
    // 0.6.1: Power off (stick screen only; asks first).
    footBtn("power", "Power off", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v9"/><path d="M6.3 7.5a8 8 0 1 0 11.4 0"/></svg>').hidden = !isLocal();
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

    // Hidden parking spot for panels while their window is closed.
    const hold = el("div", "deskHold");
    hold.id = "deskHold";
    hold.hidden = true;
    document.body.append(layer, bar, launcher, hold);
    return { layer: layer, wall: wall, bar: bar, start: start, tasks: tasks, tray: tray, launcher: launcher, grid: grid, hold: hold };
  }

  // Wall icons and launcher entries, rebuilt when the installed set changes.
  let iconSig = "";
  function renderIcons() {
    if (!ui) return;
    const order = appOrder();
    const sig = order.join(",") + "|" + catalog.map((a) => a.title + a.color).join(",");
    if (sig === iconSig) return;
    iconSig = sig;
    ui.wall.textContent = "";
    ui.grid.textContent = "";
    order.forEach((id) => {
      const title = appTitle(id);
      const b = el("button", "wallIcon");
      b.type = "button";
      b.dataset.app = id;
      if (catalogApp(id)) b.dataset.catalog = "1";
      b.setAttribute("role", "listitem");
      b.title = "Open " + title + " (double-click)";
      b.appendChild(iconFor(id));
      b.appendChild(el("span", "wallLabel")).textContent = title;
      ui.wall.appendChild(b);
      const l = el("button", "launchItem");
      l.type = "button";
      l.dataset.app = id;
      l.setAttribute("role", "menuitem");
      l.appendChild(iconFor(id));
      l.appendChild(el("span", "launchLabel")).textContent = title;
      ui.grid.appendChild(l);
    });
  }
  // Installed catalog apps come from app.js (the same /api/apps rows the App
  // Store shows). Windows of apps that were uninstalled are closed.
  function syncCatalog() {
    if (!on) return;
    const api = appApi();
    const next = api.deskCatalog ? api.deskCatalog() : [];
    const gone = catalog.filter((a) => !next.some((b) => b.id === a.id)).map((a) => a.id);
    catalog = next;
    gone.forEach((id) => { if (wm && wm.has(id)) wm.close(id, true); });
    renderIcons();
    renderTasks();
  }
  let catT = 0;
  function scheduleCatalog() { clearTimeout(catT); catT = setTimeout(syncCatalog, 80); }

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
    if (act === "settings") openApp("settings");
    else if (act === "lock") { if (appApi().lockVault) appApi().lockVault(); }
    else if (act === "apps") openApp("store");
    else if (act === "power") powerOff();
  }
  // 0.6.1: kiosk Power off with confirm. The gateway only accepts it from the
  // stick's own screen (loopback) and only with confirm:true.
  function powerOff() {
    if (!isLocal()) return;
    if (!window.confirm("Power off this computer now?\n\nUnsaved work in open apps is lost. Your vault, chats and models are kept.")) return;
    const api = appApi();
    if (api.toast) api.toast("Powering off\u2026");
    fetch("/api/system/power", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-StickLLM-Client": "ui" },
      body: JSON.stringify({ action: "poweroff", confirm: true }),
    }).then((r) => r.json().catch(() => ({}))).then((j) => {
      if (!j || !j.ok) { if (api.toast) api.toast((j && j.message) || "Power off failed"); }
    }).catch((e) => { if (api.toast) api.toast("Power off failed: " + e.message); });
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
    // Ephemeral | Vault switch. app.js's setSessionMode keeps every 0.5.5
    // guard (vault must be unlocked, stale-response epoch, lock clears chat).
    const mode = el("div", "trayMode");
    mode.id = "trayMode";
    mode.setAttribute("role", "radiogroup");
    mode.setAttribute("aria-label", "Storage mode");
    mode.innerHTML =
      '<button type="button" role="radio" data-tmode="ephemeral"><svg viewBox="0 0 24 24"><path d="M12 3c3 4 6 7 6 11a6 6 0 01-12 0c0-4 3-7 6-11z"/></svg><span>Ephemeral</span></button>' +
      '<button type="button" role="radio" data-tmode="vault"><span class="tmLock"></span><span>Vault</span></button>';
    mode.addEventListener("click", (e) => {
      const b = e.target.closest("[data-tmode]");
      if (!b) return;
      e.stopPropagation();
      const want = b.dataset.tmode;
      if (want === "vault" && vaultState() !== "open") { toggleVaultPop(true); return; }
      if (want === curMode()) { if (want === "vault") toggleVaultPop(); return; }
      toggleVaultPop(false);
      if (appApi().setSessionMode) appApi().setSessionMode(want);
    });
    mode.addEventListener("mousedown", (e) => e.stopPropagation());
    // Model button: the model name opens the Models window.
    const model = el("button", "trayModel");
    model.type = "button";
    model.id = "trayModel";
    model.innerHTML = '<span class="dot"></span><span class="tmName"></span><span class="tmMeta"></span><span class="chipLoad tmLoad" hidden><span class="chipLoadFill"></span></span>';
    model.addEventListener("click", () => openApp("models"));
    // The old chip and its popover stay in the DOM (app.js writes to them)
    // but are parked out of sight.
    const chipWrap = el("div", "trayChip");
    chipWrap.hidden = true;
    tray.appendChild(chipWrap);
    move($("#statusChip"), chipWrap);
    move($("#statusPop"), chipWrap);
    const pairSrc = $(".topPair");
    let pair = null;
    if (pairSrc) {
      pair = pairSrc.cloneNode(true);
      pair.classList.remove("topPair");
      pair.classList.add("trayBtn", "trayPair");
      pair.addEventListener("click", (e) => { e.preventDefault(); pairSrc.click(); });
      ui.pairObs = new MutationObserver(() => { pair.dataset.state = pairSrc.dataset.state || ""; pair.title = pairSrc.title; });
      ui.pairObs.observe(pairSrc, { attributes: true });
    }
    const net = el("button", "trayBtn trayNet");
    net.type = "button";
    net.id = "trayNet";
    net.addEventListener("click", () => openSettings("network"));
    const vault = el("button", "trayBtn trayVault");
    vault.type = "button";
    vault.id = "trayVault";
    vault.addEventListener("click", (e) => { e.stopPropagation(); toggleVaultPop(); });
    const theme = el("button", "trayBtn trayTheme", '<svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>');
    theme.type = "button";
    theme.title = "Toggle theme";
    theme.setAttribute("aria-label", "Toggle light/dark theme");
    theme.addEventListener("click", () => { const t = $("#themeBtn"); if (t) t.click(); });
    const clock = el("div", "trayClock");
    clock.id = "trayClock";
    tray.append(mode, el("span", "traySep"), model, el("span", "traySep"));
    if (pair) tray.appendChild(pair);
    tray.append(net, vault, theme, clock);
    buildVaultPop();
    syncTray();
    const obs = new MutationObserver(syncTray);
    ["#popVault", "#popUplink", "#statusChip", "#popModel", "#popCtx", "#popBackend", "#unlockMsg"].forEach((s) => {
      const n = $(s);
      if (n) obs.observe(n, { childList: true, characterData: true, subtree: true, attributes: true });
    });
    document.querySelectorAll(".modeSeg [data-mode]").forEach((n) => obs.observe(n, { attributes: true }));
    ui.obs = obs;
    tickClock();
    ui.clockT = setInterval(tickClock, 15000);
  }

  // ---------- vault popover (taskbar) ----------
  function curMode() {
    const api = appApi();
    if (api.sessionMode) return api.sessionMode() === "vault" ? "vault" : "ephemeral";
    const b = $(".modeSeg [data-mode].on");
    return b ? b.dataset.mode : "ephemeral";
  }
  function openSettings(sec) { if (appApi().openSettings) appApi().openSettings(sec); }
  function buildVaultPop() {
    const pop = el("div", "vaultPop");
    pop.id = "vaultPop";
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Vault");
    pop.innerHTML =
      '<div class="vpHead"><span class="vpIcon"></span><div><b class="vpTitle"></b><small class="vpSub"></small></div></div>' +
      '<form class="vpUnlock" autocomplete="off"><input type="text" class="secret vpPass" placeholder="Vault passcode" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" data-lpignore="true" data-1p-ignore aria-label="Vault passcode"><button class="btn primary sm">Unlock</button></form>' +
      '<small class="vpMsg" role="alert" hidden></small>' +
      '<div class="vpActs"><button type="button" class="btn sm vpLock">Lock vault</button><button type="button" class="btn sm ghost vpEph">Use Ephemeral</button><button type="button" class="btn sm ghost vpSet">Storage &amp; Vault settings\u2026</button></div>' +
      '<small class="vpKeys">Ctrl+Shift+L locks the vault and clears the chat.</small>';
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
    pop.querySelector(".vpUnlock").addEventListener("submit", (e) => {
      e.preventDefault();
      const v = pop.querySelector(".vpPass");
      const src = $("#vaultPass"), form = $("#unlockForm");
      if (!src || !form) { toggleVaultPop(false); openSettings("storage"); return; }
      if (!v.value) { showVpMsg("Enter the vault passcode."); v.focus(); return; }
      src.value = v.value;
      v.value = "";
      showVpMsg("Unlocking\u2026", true);
      // The Storage panel's own unlock form does the work (one code path).
      if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event("submit", { cancelable: true }));
    });
    pop.querySelector(".vpLock").addEventListener("click", () => { toggleVaultPop(false); if (appApi().lockVault) appApi().lockVault(); });
    pop.querySelector(".vpEph").addEventListener("click", () => { toggleVaultPop(false); if (appApi().setSessionMode) appApi().setSessionMode("ephemeral"); });
    pop.querySelector(".vpSet").addEventListener("click", () => { toggleVaultPop(false); openSettings("storage"); });
    document.body.appendChild(pop);
    ui.vaultPop = pop;
  }
  function showVpMsg(t, info) {
    const m = ui && ui.vaultPop && ui.vaultPop.querySelector(".vpMsg");
    if (!m) return;
    m.textContent = t || "";
    m.hidden = !t;
    m.classList.toggle("info", !!info);
  }
  function toggleVaultPop(force) {
    if (!ui || !ui.vaultPop) return false;
    const pop = ui.vaultPop;
    const open = force == null ? pop.hidden : !!force;
    pop.hidden = !open;
    if (open) {
      toggleLauncher(false);
      showVpMsg("");
      const um = $("#unlockMsg");
      if (um) { um.hidden = true; um.textContent = ""; }
      syncTray();
      if (vaultState() === "locked") setTimeout(() => pop.querySelector(".vpPass").focus(), 0);
    }
    return true;
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
    const v = vaultState();
    const m = curMode();
    const txt = (s) => (($(s) || {}).textContent || "").trim();
    if (net) {
      const up = txt("#popUplink");
      const model = txt("#chipModel");
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
      const label = v === "open" ? "Vault unlocked \u2014 click to lock or manage"
        : v === "none" ? "Vault not set up \u2014 click to set one up" : "Vault locked \u2014 click to unlock";
      vault.dataset.state = v;
      vault.innerHTML = v === "open" ? SVG.lockOpen : SVG.lockShut;
      vault.title = label;
      vault.setAttribute("aria-label", label);
    }
    const tm = $("#trayMode");
    if (tm) {
      tm.dataset.mode = m;
      tm.dataset.vault = v;
      tm.querySelectorAll("[data-tmode]").forEach((b) => {
        const sel = b.dataset.tmode === m;
        b.classList.toggle("on", sel);
        b.setAttribute("aria-checked", String(sel));
      });
      const vb = tm.querySelector('[data-tmode="vault"]');
      vb.querySelector(".tmLock").innerHTML = v === "open" ? SVG.lockOpen : SVG.lockShut;
      vb.title = v === "open" ? (m === "vault" ? "Vault mode: chats are saved encrypted (click to lock or manage)" : "Vault unlocked \u2014 click to save chats in the vault")
        : v === "none" ? "No vault yet \u2014 click to set one up" : "Vault locked \u2014 click to unlock";
      tm.querySelector('[data-tmode="ephemeral"]').title = "Ephemeral: nothing is written to disk; chats are gone at reboot";
    }
    const tb = $("#trayModel");
    if (tb) {
      const name = txt("#chipModel");
      const meta = txt("#chipMeta");
      const none = !name || /^none$/i.test(name) || name === "\u2014";
      const dot = $("#statusChip .dot");
      tb.querySelector(".dot").className = dot ? dot.className : "dot";
      tb.querySelector(".tmName").textContent = none ? "Open Model" : name;
      tb.querySelector(".tmMeta").textContent = none || !meta || meta === "?" ? "" : meta;
      tb.classList.toggle("none", none);
      const ld = $("#chipLoad"), lf = $("#chipLoadFill");
      const tl = tb.querySelector(".tmLoad");
      tl.hidden = !ld || ld.hidden;
      if (lf) tl.firstChild.style.width = lf.style.width;
      const pm = txt("#popModel"), ctx = txt("#popCtx"), be = txt("#popBackend");
      tb.title = none ? "No model loaded \u2014 click to open one"
        : "Model: " + (pm && pm !== "\u2014" ? pm : name) + (ctx && ctx !== "\u2014" ? " \u00b7 context " + ctx : "") + (be && be !== "\u2014" ? " \u00b7 " + be : "") + " \u2014 click for Models";
    }
    const pop = ui && ui.vaultPop;
    if (pop) {
      pop.dataset.vault = v;
      pop.querySelector(".vpIcon").innerHTML = v === "open" ? SVG.lockOpen : SVG.lockShut;
      pop.querySelector(".vpTitle").textContent = v === "open" ? "Vault unlocked" : v === "none" ? "No vault set up" : "Vault locked";
      pop.querySelector(".vpSub").textContent = v === "open"
        ? (m === "vault" ? "Vault mode \u2014 chats are saved encrypted." : "Ephemeral mode \u2014 nothing is saved.")
        : v === "none" ? "Create or attach a vault in Storage & Vault." : "Ephemeral works while locked. Unlock to save chats and use apps.";
      pop.querySelector(".vpUnlock").hidden = v !== "locked";
      pop.querySelector(".vpLock").hidden = v !== "open";
      pop.querySelector(".vpEph").hidden = !(v === "open" && m === "vault");
      pop.querySelector(".vpSet").textContent = v === "none" ? "Set up a vault\u2026" : "Storage & Vault settings\u2026";
      const um = $("#unlockMsg");
      const msg = um && !um.hidden ? (um.textContent || "").trim() : "";
      const cur = pop.querySelector(".vpMsg").textContent;
      if (msg && !pop.hidden) showVpMsg(msg);
      else if (v === "open" && !pop.hidden && /Unlocking/.test(cur)) toggleVaultPop(false);
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
      browserWins.forEach((bw, j) => {
        const key = "chrome:" + (bw.id || j);
        let b = have.get(key);
        if (!b) {
          b = el("button", "taskBtn taskExt");
          b.type = "button";
          b.dataset.app = key;
          b.dataset.ext = String(bw.id || "");
          b.appendChild(iconFor("browser"));
          b.appendChild(el("span", "taskLabel"));
          ui.tasks.appendChild(b);
        }
        have.delete(key);
        const label = bw.page_title || bw.title || "Browser";
        b.querySelector(".taskLabel").textContent = label;
        b.classList.toggle("active", !!bw.focused && !bw.minimised);
        b.classList.toggle("min", !!bw.minimised);
        b.setAttribute("aria-pressed", String(!!bw.focused && !bw.minimised));
        b.title = label + (bw.minimised ? " (minimised) \u2014 click to restore" : bw.focused ? " \u2014 click to minimise" : " \u2014 click to bring to front") + " \u00b7 right-click for more";
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
      if (spec.url && typeof spec.url.then === "function") {
        spec.url.then((u) => { f.src = u || "about:blank"; }, () => { f.src = "about:blank"; });
      } else f.src = spec.url;
      // Explicit feature allow-list so Chat/Agent embeds can call getUserMedia
      // when the top page is a secure context (https://stick-ip/).
      f.setAttribute("allow", "microphone *; camera *; autoplay; clipboard-read; clipboard-write; fullscreen");
      f.setAttribute("allowfullscreen", "");
      // Paint containment: A0 token/tool DOM thrash stays inside the frame.
      f.style.cssText = "width:100%;height:100%;border:0;display:block;contain:strict;isolation:isolate";
      frameHooks(f, spec.id);
      wb.body.appendChild(f);
      // 0.6.1 (item 24): on a LAN browser the Agent window loads
      // https://<ip>:5443, whose self-signed certificate can't be accepted
      // inside a frame. Always offer a new tab instead of a dead frame.
      if (spec.id === "agent" && !isLocal()) {
        const bar = document.createElement("div");
        bar.className = "dkFrameFallback";
        bar.innerHTML = '<span>Agent Zero not showing?</span> <button type="button" class="btn sm">Open Agent Zero in a new tab</button> <button type="button" class="btn sm ghost" aria-label="Hide">×</button>';
        const [openBtn, hideBtn] = bar.querySelectorAll("button");
        openBtn.onclick = (ev) => { ev.stopPropagation(); openOutside("agent"); };
        hideBtn.onclick = (ev) => { ev.stopPropagation(); bar.remove(); };
        wb.body.appendChild(bar);
      }
      if (spec.popOut && wb.addControl) {
        wb.addControl({ index: 0, class: "wb-pop", image: POP_ICON, click: (ev) => { ev.stopPropagation(); spec.popOut(); } });
      }
    }
    return wb;
  }

  function chatSpec(ag) {
    // 0.6.5: Agent Zero window only — never mount StickLLM #app into WinBox
    // (that pulled the old thread UI onto the kiosk and distorted the desk).
    ag = ag || (appApi().deskAgent ? appApi().deskAgent() : { installed: false, running: false });
    if (ag.installed && ag.running) {
      return {
        id: CHAT, title: "Agent Zero", w: 1180, h: 800, pinned: true,
        url: urlFor("agent"), popOut: () => openOutside("agent"),
      };
    }
    return { id: CHAT, title: "Agent Zero", w: 1000, h: 720, pinned: true, mountNode: ui.agentPanel };
  }
  const POP_ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23fff' stroke-width='2.2'%3E%3Cpath d='M14 4h6v6M20 4l-9 9M18 14v6H4V6h6'/%3E%3C/svg%3E";
  function isLocal() {
    const h = location.hostname;
    return h === "127.0.0.1" || h === "localhost" || h === "::1" || h === "[::1]";
  }
  function urlFor(id, opts) {
    const api = appApi();
    return Promise.resolve(api.deskAppUrl ? api.deskAppUrl(id, opts) : "").then((u) => u || "");
  }
  // An app that refuses to be framed opens outside the desktop: a kiosk
  // Chrome window on the stick's own screen, a named tab on a paired laptop.
  function openOutside(id) {
    const pop = id === "agent" || id === CHAT ? { embed: false } : undefined;
    return urlFor(id, pop).then((u) => {
      if (!u) return;
      if (isLocal()) openBrowser(u, appTitle(id), true);
      else window.open(u, "stickllm-" + id);
    });
  }
  // Panels (Settings, Models, App Store, Agent setup) are mounted; WinBox
  // puts them back in their parking spot when the window closes.
  function mountSpec(id, node) {
    const a = SYS[id];
    return { id: id, title: a.title, w: a.w, h: a.h, mountNode: node };
  }
  function openApp(id) {
    if (!on || !wm) return null;
    // 0.6.2: opening/raising an app must bring it above any Chrome window.
    if (browserCovers()) yieldBrowser();
    const api = appApi();
    if (id === CHAT) {
      try { if (api.ensureAgentZeroStarted) api.ensureAgentZeroStarted(); } catch (e) {}
      const cur = wm.get(CHAT);
      const openChatWith = (ag) => {
        if (cur && cur.agentPanel && ag.installed && ag.running) wm.close(CHAT, true);
        const w = wm.open(chatSpec(ag));
        if (w && !(ag.installed && ag.running)) {
          w.agentPanel = true;
          startChatAgentPoll();
        }
        return w;
      };
      const ag0 = api.deskAgent ? api.deskAgent() : {};
      // Paired LAN: status may still be empty on first click — refresh before Install panel.
      if (!(ag0.installed && ag0.running) && api.refreshAgentLink) {
        Promise.resolve(api.refreshAgentLink()).then(() => {
          const ag = api.deskAgent ? api.deskAgent() : ag0;
          if (wm && wm.has(CHAT) && wm.get(CHAT) && wm.get(CHAT).agentPanel && ag.installed && ag.running) {
            wm.close(CHAT, true);
            wm.open(chatSpec(ag));
            stopChatAgentPoll();
          } else if (!wm || !wm.has(CHAT)) openChatWith(ag);
          else renderAgentPanel(ag);
        }).catch(() => openChatWith(ag0));
        if (cur && cur.agentPanel) { renderAgentPanel(ag0); return cur; }
        return openChatWith(ag0);
      }
      return openChatWith(ag0);
    }
    if (id === "settings") {
      const w = wm.open(mountSpec("settings", ui.settings));
      if (api.openSettings && !$("#settings .setScroll > section:not([hidden])")) api.openSettings("general");
      return w;
    }
    if (id === "models") {
      const w = wm.open(mountSpec("models", ui.models));
      if (!$("#sec-models:not([hidden]), #sec-downloads:not([hidden])", ui.models) && api.showSec) api.showSec("models");
      if (api.refreshModels) try { api.refreshModels(); } catch (e) {}
      return w;
    }
    if (id === "store") {
      const w = wm.open(mountSpec("store", ui.store));
      if (api.refreshApps) api.refreshApps().then(scheduleCatalog, () => {});
      return w;
    }
    if (id === "agent") {
      // 0.6.3: Agent launcher opens the main Chat (A0) window.
      return openApp(CHAT);
    }
    if (id === "browser") { openBrowser("", "Browser"); return true; }
    if (has(APPS, id)) {
      const a = APPS[id];
      return wm.open({ id: id, title: a.title, w: a.w, h: a.h, url: appHref(id) });
    }
    const c = catalogApp(id);
    if (c) {
      if (c.frame === false) { openOutside(id); return true; }
      return wm.open({ id: id, title: c.title, w: 1180, h: 780, url: urlFor(id), popOut: () => openOutside(id) });
    }
    return null;
  }
  // 0.6.2 (A3): the Agent window shows Agent Zero's page only once it
  // answers. While it installs or starts the window shows "Starting… step X
  // of 6", a bar and Retry, polls every 1.5 s and switches by itself; it
  // never shows a "refused to connect" page.
  let agentPoll = null;
  function stopAgentPoll() { if (agentPoll) { clearInterval(agentPoll); agentPoll = null; } }
  function agentWinIsPanel() { const w = wm && wm.get("agent"); return !!(w && w.agentPanel); }
  function openAgent() {
    const api = appApi();
    const go = (ag) => {
      const cur = wm.get("agent");
      if (ag.installed && ag.running) {
        stopAgentPoll();
        if (cur && cur.agentPanel) wm.close("agent", true);
        return wm.open({ id: "agent", title: "Agent", w: SYS.agent.w, h: SYS.agent.h, url: urlFor("agent"), popOut: () => openOutside("agent") });
      }
      renderAgentPanel(ag);
      const w = wm.open(mountSpec("agent", ui.agentPanel));
      if (w) w.agentPanel = true;
      stopAgentPoll();
      const tick = () => {
        if (!wm || !wm.has("agent") || !agentWinIsPanel()) { stopAgentPoll(); return; }
        if (!api.refreshAgentLink) return;
        Promise.resolve(api.refreshAgentLink()).then(() => {
          const now = api.deskAgent ? api.deskAgent() : ag;
          if (!agentWinIsPanel()) return;
          if (now.installed && now.running) openAgent();
          else renderAgentPanel(now);
        }).catch(() => {});
      };
      tick();
      agentPoll = setInterval(tick, 1500);
      return w;
    };
    const ag0 = api.deskAgent ? api.deskAgent() : { installed: false };
    if (!(ag0.installed && ag0.running) && api.refreshAgentLink) {
      Promise.resolve(api.refreshAgentLink()).then(() => go(api.deskAgent ? api.deskAgent() : ag0)).catch(() => go(ag0));
    }
    return go(ag0);
  }
  function renderAgentPanel(ag) {
    const p = ui && ui.agentPanel;
    if (!p) return;
    ag = ag || {};
    const st = String(ag.status || "");
    const working = st === "installing" || st === "starting" || (ag.installed && !ag.running && st !== "error" && st !== "pull_failed");
    const pct = Number.isFinite(Number(ag.progress)) && ag.progress !== null && ag.progress !== "" ? Math.max(0, Math.min(99, Math.round(Number(ag.progress)))) : null;
    let line;
    if (working) line = ag.message || (ag.step ? "Starting… step " + ag.step + " of " + (ag.steps || 6) : "Starting Agent Zero…");
    else if (st === "error" || st === "pull_failed") line = ag.message || "Agent Zero did not start.";
    else if (!ag.installed) line = ag.state && ag.state !== "Not installed" ? ag.state : "Agent Zero is not installed yet.";
    else line = ag.message || ag.state || "";
    p.querySelector(".apState").textContent = line;
    const bar = p.querySelector(".apBar");
    if (bar) {
      bar.hidden = !working;
      const fill = bar.querySelector("i");
      if (fill) fill.style.width = (pct !== null ? pct : 5) + "%";
      bar.classList.toggle("indet", pct === null);
    }
    const inst = p.querySelector(".apInstall");
    const retry = p.querySelector(".apRetry");
    if (inst) {
      const showInstall = !!ag.needsInstall && !ag.installed;
      const showOpen = (!!ag.installed || !!ag.preinstalled) && !ag.running && !ag.needsInstall;
      inst.hidden = !(showInstall || showOpen);
      inst.disabled = !!ag.busy;
      inst.classList.toggle("busy", !!ag.busy);
      inst.dataset.mode = showOpen ? "open" : "install";
      inst.textContent = showOpen
        ? (ag.busy ? "Starting…" : "Open Agent Zero")
        : (ag.busy ? "Installing…" : "Install Agent Zero");
    }
    if (retry) {
      retry.hidden = !ag.installed || !!ag.needsInstall || !!ag.running;
      retry.disabled = st === "installing" || st === "starting";
    }
  }
  // The Browser is a real Chrome window on the stick's screen (kiosk),
  // placed over the desktop like the other windows (stickllm-control). On a
  // paired laptop the page is already in a browser: a new tab.
  // Browser icon / unframeable apps: a real Chromium window on the stick's
  // screen (stickllm-control browser_open). app=true opens a bare app window
  // for one site; the Browser icon gets a normal window with an address bar.
  function openBrowser(url, title, app) {
    const api = appApi();
    if (!isLocal() || !api.control) { window.open(url || "about:blank", "_blank"); return; }
    const r = ui.layer.getBoundingClientRect();
    const k = window.devicePixelRatio || 1;
    const bx = window.screenX || 0, by = window.screenY || 0;
    const w = Math.min(1180, Math.round(r.width - 80)), h = Math.min(780, Math.round(r.height - 60));
    const geo = { x: Math.round((bx + (r.width - w) / 2) * k), y: Math.round((by + 30) * k), w: Math.round(w * k), h: Math.round(h * k) };
    api.control("browser_open", { url: url || "", title: title || "Browser", app: !!app, geometry: geo }).then((res) => {
      if (res && res.ok === false) {
        // No Chromium/screen (e.g. cog kiosk): fall back to a page tab.
        if ((res.error === "no_browser" || res.error === "no_display") && url) window.open(url, "_blank");
        if (api.toast) api.toast(res.message || res.error || "The browser could not start");
        return;
      }
      if (api.toast) api.toast((res && res.downloads === "vault" ? "Downloads go to the vault." : "Downloads are off while the vault is locked.") + " Drag the title bar to move it; the taskbar minimises and restores it.");
      pollBrowser();
    }).catch((e) => { if (api.toast) api.toast("Browser: " + e.message); });
  }
  // Window ops go to the compositor (stickllm-control browser_window, which
  // talks to the X11 window manager via wmctrl). The desktop taskbar height is reserved when maximising.
  function browserOp(id, op) {
    const api = appApi();
    if (!api.control || !id) return Promise.resolve(null);
    const taskbar = Math.round(48 * (window.devicePixelRatio || 1));
    return api.control("browser_window", { id: id, op: op, taskbar: taskbar }).then((res) => {
      if (res && res.ok === false && res.error === "not_found") { pollBrowser(); return res; }
      if (res && res.ok === false && api.toast) api.toast(res.message || "That window could not be changed");
      const bw = browserWins.find((x) => x.id === id);
      if (bw && res && res.window) Object.assign(bw, { minimised: res.window.minimised, focused: res.window.focused, maximised: res.window.maximised });
      renderTasks();
      setTimeout(pollBrowser, 600);
      return res;
    }).catch(() => { pollBrowser(); return null; });
  }
  // 0.6.2: Chrome windows are real X windows above the desktop page.
  function browserCovers() { return browserWins.some((x) => x && !x.minimised); }
  function yieldBrowser() {
    browserWins.filter((x) => x && !x.minimised).forEach((x) => { x.minimised = true; browserOp(x.id, "minimise"); });
  }
  let browserMenu = null;
  function hideBrowserMenu() {
    if (browserMenu) { browserMenu.remove(); browserMenu = null; }
    document.removeEventListener("mousedown", hideBrowserMenu, true);
  }
  function showBrowserMenu(btn) {
    hideBrowserMenu();
    const id = btn.dataset.ext;
    const bw = browserWins.find((x) => x.id === id) || {};
    const m = el("div", "taskMenu");
    m.setAttribute("role", "menu");
    const items = [
      bw.minimised ? ["restore", "Restore"] : ["minimise", "Minimise"],
      ["maximise", bw.maximised ? "Restore size" : "Maximise"],
      ["close", "Close"],
    ];
    items.forEach(([op, label]) => {
      const it = el("button", "taskMenuItem");
      it.type = "button";
      it.setAttribute("role", "menuitem");
      it.dataset.op = op;
      it.textContent = label;
      it.addEventListener("mousedown", (e) => e.stopPropagation());
      it.addEventListener("click", (e) => {
        e.stopPropagation();
        hideBrowserMenu();
        browserOp(id, op);
      });
      m.appendChild(it);
    });
    document.body.appendChild(m);
    const r = btn.getBoundingClientRect();
    m.style.left = Math.max(4, Math.min(r.left, window.innerWidth - m.offsetWidth - 4)) + "px";
    m.style.bottom = (window.innerHeight - r.top + 6) + "px";
    browserMenu = m;
    setTimeout(() => document.addEventListener("mousedown", hideBrowserMenu, true), 0);
  }
  // Chrome windows show on the taskbar while they run.
  let browserT = 0;
  let browserWins = [];
  window.addEventListener("stickllm-browser-changed", () => pollBrowser());
  function pollBrowser() {
    clearTimeout(browserT);
    const api = appApi();
    if (!on || !api.control || !isLocal()) return;
    api.control("browser_status").then((res) => {
      if (!on) return;
      browserWins = res && Array.isArray(res.windows) ? res.windows : [];
      renderTasks();
      if (browserWins.length) browserT = setTimeout(pollBrowser, res && res.wm ? 1500 : 4000);
    }).catch(() => {});
  }
  // Desktop-only panels built around the existing Settings sections.
  function buildPanels() {
    // Settings window: the existing settings dialog; Models/Downloads are
    // the Models app now (hidden from its nav by desktop.css).
    ui.settings = $("#settings > .modal");
    const m = el("div", "deskPanel deskModels");
    m.id = "deskModels";
    m.innerHTML = '<div class="deskTabs" role="tablist"><button type="button" class="on" data-desk-sec="models" role="tab">Models</button><button type="button" data-desk-sec="downloads" role="tab">Downloads</button></div><div class="deskScroll"></div>';
    const scroll = m.querySelector(".deskScroll");
    ui.hold.appendChild(m);
    move($("#sec-models"), scroll);
    move($("#sec-downloads"), scroll);
    m.querySelector(".deskTabs").addEventListener("click", (e) => {
      const b = e.target.closest("[data-desk-sec]");
      if (b) openSettings(b.dataset.deskSec);
    });
    ui.models = m;
    // App Store window: the catalog of the old Apps page.
    const st = el("div", "deskPanel deskStore");
    st.id = "deskStore";
    st.innerHTML = '<div class="deskPanelHead"><b>App Store</b><small>Apps install onto the vault. Installed apps get a desktop icon and a Start entry.</small></div><div class="deskScroll"></div>';
    ui.hold.appendChild(st);
    move($("#appsMenu .appsInner"), st.querySelector(".deskScroll"));
    ui.store = st;
    // Agent window while Agent Zero is not installed.
    const ag = el("div", "deskPanel deskAgentPanel");
    ag.innerHTML = '<div class="apCard"><img src="agent-zero.png?v=desk4" alt=""><h2>Agent</h2><p>Agent Zero works on tasks for you with the local model. The program installs to the StickLLM data drive (/mnt/stickllm-data/stickllm-docker); its chats, memory and settings stay in your encrypted vault.</p><p class="apState" aria-live="polite"></p><div class="apBar" hidden><i></i></div><div class="apActs"><button type="button" class="btn primary apInstall">Install Agent Zero</button><button type="button" class="btn apRetry" hidden>Retry</button><button type="button" class="btn ghost apStore">Open App Store</button></div></div>';
    ag.querySelector(".apInstall").addEventListener("click", (e) => {
      const api = appApi();
      const b = e.currentTarget;
      if (b.dataset.mode === "open") {
        if (api.ensureAgentZeroStarted) Promise.resolve(api.ensureAgentZeroStarted()).catch(() => {});
        openOutside("agent");
        startChatAgentPoll();
        return;
      }
      b.disabled = true; b.classList.add("busy"); b.textContent = "Installing…";
      if (api.installAgent) Promise.resolve(api.installAgent()).catch(() => {});
      setTimeout(() => {
        if (wm && wm.has(CHAT) && wm.get(CHAT) && wm.get(CHAT).agentPanel) startChatAgentPoll();
        else if (wm && wm.has("agent")) openAgent();
      }, 1500);
    });
    ag.querySelector(".apRetry").addEventListener("click", (e) => {
      const api = appApi();
      const b = e.currentTarget;
      b.disabled = true; b.classList.add("busy"); b.textContent = "Retrying…";
      fetch("/api/agent/start", { method: "POST", cache: "no-store", credentials: "same-origin",
        headers: api.authHeaders ? api.authHeaders({ "Content-Type": "application/json" }) : { "Content-Type": "application/json" }, body: "{}" })
        .then((r) => r.json().catch(() => ({})).then((j) => { if (!r.ok && api.toast) api.toast(j.message || "Could not restart Agent Zero"); }))
        .catch(() => {})
        .finally(() => setTimeout(() => { b.disabled = false; b.classList.remove("busy"); b.textContent = "Retry"; if (wm && wm.has("agent")) openAgent(); }, 1500));
    });
    ag.querySelector(".apStore").addEventListener("click", () => openApp("store"));
    ui.hold.appendChild(ag);
    ui.agentPanel = ag;
  }
  // ---------- enter / leave ----------
  // 0.5.6: the chat list stays a collapsible sidebar inside the Chat window.
  // The sidebar's own button collapses it, the header button brings it back
  // (Ctrl+B toggles); the state is remembered for this browser.
  const SIDE_KEY = "stickllm.desk.chatSidebar";
  function syncSideButtons(desk) {
    const appEl = $("#app");
    const collapsed = !!(appEl && appEl.classList.contains("collapsed"));
    const menu = $("#menuBtn"), col = $("#collapseBtn");
    if (menu) {
      menu.setAttribute("aria-expanded", String(!collapsed));
      menu.title = desk ? "Show chats (Ctrl+B)" : "Conversations (Ctrl+B)";
      menu.setAttribute("aria-label", desk ? "Show chats" : "Open conversations");
    }
    if (col) {
      col.setAttribute("aria-expanded", String(!collapsed));
      col.title = desk ? "Hide chats (Ctrl+B)" : "Collapse sidebar (Ctrl+B)";
      col.setAttribute("aria-label", desk ? "Hide chats" : "Collapse sidebar");
    }
  }
  function chatSidebar() {
    const appEl = $("#app");
    if (!appEl) return;
    ui.sidePrev = appEl.classList.contains("collapsed");
    appEl.classList.toggle("collapsed", store.get(SIDE_KEY) === "collapsed");
    syncSideButtons(true);
    ui.sideObs = new MutationObserver(() => {
      if (!on) return;
      store.set(SIDE_KEY, appEl.classList.contains("collapsed") ? "collapsed" : "open");
      syncSideButtons(true);
    });
    ui.sideObs.observe(appEl, { attributes: true, attributeFilter: ["class"] });
  }
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
      buildPanels();
      wm = new core.WindowManager({
        create: createWin,
        store: store,
        area: () => ({ w: window.innerWidth, h: window.innerHeight - core.TASKBAR_H }),
        onchange: renderTasks,
      });
      syncCatalog();
      ui.catObs = new MutationObserver(scheduleCatalog);
      const di = $("#deskIcons"), al = $("#agentLink");
      if (di) ui.catObs.observe(di, { childList: true, subtree: true, attributes: true });
      if (al) ui.catObs.observe(al, { attributes: true });
      if (appApi().refreshApps) appApi().refreshApps().then(scheduleCatalog, () => {});
      ui.catT = setInterval(() => { if (appApi().refreshApps) appApi().refreshApps().then(scheduleCatalog, () => {}); }, 60000);
      // 0.6.5: #app is no longer the Chat window content. Park the legacy shell
      // in deskHold so composer / New chat / chat-slide cannot paint through the
      // transparent desktop wall. Chat opens Agent Zero (or the Agent panel).
      try {
        const appEl = $("#app");
        if (appEl && ui.hold) move(appEl, ui.hold);
      } catch (e) {}
      openApp(CHAT);
      pollBrowser();
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
      if (ui.catObs) ui.catObs.disconnect();
      if (ui.pairObs) ui.pairObs.disconnect();
      if (ui.sideObs) ui.sideObs.disconnect();
      const appEl = $("#app");
      if (appEl) appEl.classList.toggle("collapsed", !!ui.sidePrev);
      syncSideButtons(false);
      clearInterval(ui.clockT);
      clearInterval(ui.catT);
      clearTimeout(browserT);
      ui.layer.remove(); ui.bar.remove(); ui.launcher.remove(); ui.hold.remove();
      if (ui.vaultPop) ui.vaultPop.remove();
    }
    ui = null;
    wm = null;
    catalog = [];
    iconSig = "";
    browserWins = [];
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
    if (now) now.textContent = "Now: " + (on ? "desktop" : "simple") + (v === "auto" ? " (auto)" : "");
  }
  document.querySelectorAll("#layoutSeg button").forEach((b) => {
    b.addEventListener("click", () => { core.writeOverride(store, b.dataset.layout); syncLayoutSeg(); evaluate(); });
  });

  // ---------- keys ----------
  window.addEventListener("keydown", (e) => {
    if (!on) return;
    const k = (e.key || "").toLowerCase();
    if (e.key === "Escape" && ui && ui.vaultPop && !ui.vaultPop.hidden) {
      e.preventDefault(); e.stopImmediatePropagation(); toggleVaultPop(false); return;
    }
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
    if (ui && ui.vaultPop && !ui.vaultPop.hidden && !ui.vaultPop.contains(e.target) && !e.target.closest("#trayMode,#trayVault")) toggleVaultPop(false);
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
    handles: (id) => on && (has(APPS, id) || has(SYS, id) || !!catalogApp(id)),
    // app.js: openSettings(sec) in the desktop picks the window.
    onSettings: (sec) => {
      if (!on || !wm) return;
      if (sec === "models" || sec === "downloads") {
        openApp("models");
        if (ui && ui.models) ui.models.querySelectorAll("[data-desk-sec]").forEach((b) => b.classList.toggle("on", b.dataset.deskSec === sec));
      } else if (sec !== "__nav") {
        if (!wm.has("settings")) openApp("settings");
        else wm.focus("settings");
      }
    },
    onSettingsClose: () => { if (wm && wm.has("settings")) wm.close("settings"); },
    vaultPrompt: () => on && toggleVaultPop(true),
    refreshCatalog: scheduleCatalog,
    openApp: (id) => openApp(id),
    openBrowser: (url, title) => openBrowser(url, title),
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
