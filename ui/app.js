(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const app = $("#app");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const TOKEN_KEY = "stickllm_pair_token";
let token = localStorage.getItem(TOKEN_KEY) || "";
let isLocalMode = false;
let sessionMode = "ephemeral";
let mainView = "chat";
let selectedAppId = "";
let loadedCtx = 0;
let lastPerf = null;
let sessionModeBusy = false;
let clearingOnLock = false; // clearOnLock() re-entry guard (0.5.4)
let activeChatId = null;
let lastRemintId = null;
let lastCatalog = [];
let hfHits = [];
let hfBusy = false;
let hfErr = "";
let hfTimer = null;
let selectedModelId = null;
/** Optimistic card badge while llama loads (cleared when that model is up, or the load fails). */
let loadingModelId = null;
let loadingModelName = "";
let loadingModelPath = "";
/** True after model_activate returns. Until then a still-healthy llama is the previous model. */
let loadActivateSettled = false;
/** Seen llama_ok drop after the click, so a later ok is a new process, not the one already serving. */
let loadSawNotOk = false;
/** Non-empty when the model that came up is not the one that was clicked. Header stays failed. */
let loadMismatchText = "";
let dlPollTimer = null;
let vaultBrowsePath = "";
let vaultPickerMount = "";
let vaultBrowseBlobPath = "";
let pickerPurpose = "vault"; // vault | models_dir | folder
let hwInfo = { vram: 24, vramEach: 24, gpuCount: 1, ram: 64, gpu: "", name: "This machine" };
// AVX / VRAM warnings from control status (v0.5.4): shown, never blocking.
let hwWarnings = [];
let hwWarnToasted = false;
const messages = [{
  role: "system",
  content: "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful.",
}];
const TRUST = {
  verified: { l: "Verified", c: "t-ok", d: "On StickLLM's verified list (sha256 pinned)" },
  community: { l: "Known publisher", c: "t-acc", d: "Official publisher, not verified by StickLLM" },
  unverified: { l: "Not verified", c: "t-warn", d: "Not on StickLLM's verified list" },
  untrusted: { l: "Untrusted", c: "t-bad", d: "Unknown source, not verified by StickLLM" },
  blocked: { l: "Blocked", c: "t-blk", d: "Hash does not match the verified hash" },
};
const ALL_TRUST = () => new Set(Object.keys(TRUST));
const state = {
  mode: "ephemeral", vaultOpen: false, web: true, theme: "dark",
  chats: [], ephemeral: [], current: null, attach: [],
  mtab: "browse", ablAck: false, kv: "f16",
  mf: { target: "this", fits: false, ctx: 8192, trust: ALL_TRUST(), abl: "include", quant: "any", lic: "any", vis: "any", q: "", sort: "fit" },
  policy: { verifiedOnly: false, hideUnc: false },
};

function authHeaders(extra = {}) {
  const h = { "X-StickLLM-Client": "ui", ...extra };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}
// A random id for this browser (not a secret, no auth power). Cookies are per
// host, not per port, so this browser's Agent tab on :5443 sends it too, and
// the gateway sends open_app to the device that sent the chat message.
function ensureDeviceCookie() {
  try {
    const m = document.cookie.match(/(?:^|;\s*)stickllm_device=([0-9a-f]{16,64})/);
    let id = m ? m[1] : (localStorage.getItem("stickllm-device-id") || "");
    if (!/^[0-9a-f]{16,64}$/.test(id)) {
      const b = new Uint8Array(16);
      crypto.getRandomValues(b);
      id = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    }
    localStorage.setItem("stickllm-device-id", id);
    document.cookie = "stickllm_device=" + id + "; Path=/; Max-Age=31536000; SameSite=Lax";
  } catch (_) {}
}
ensureDeviceCookie();
/** Another tab may have paired (or re-paired) this origin: adopt its token. */
function syncToken() {
  let saved = "";
  try { saved = localStorage.getItem(TOKEN_KEY) || ""; } catch (_) {}
  if (saved && saved !== token) token = saved;
  return token;
}
// 0.5.2: the pair cookie is HttpOnly and set by the gateway (at pairing and
// on /api/ui/apps-session), so no tab can clear or clobber it from script.
// This only refreshes it from this tab's token; an empty token never deletes it.
function rememberPairCookie() {
  syncToken();
  if (!token) return;
  primeAppsSession();
}
// Paired LAN browser: the gateway sets an HttpOnly stickllm_apps cookie
// (derived from the pairing), so app pages opened from a desktop icon or by
// open_app never depend on the shared, script-set stickllm_pair cookie, which
// any other StickLLM tab on this host can clear or overwrite.
const appsSession = { at: 0, token: "", busy: null };
function primeAppsSession(force = false) {
  if (!token || detectLocalHost()) return Promise.resolve(true);
  if (appsSession.busy) return appsSession.busy;
  if (!force && appsSession.token === token && Date.now() - appsSession.at < 5 * 60 * 1000) {
    return Promise.resolve(true);
  }
  const mine = token;
  appsSession.busy = fetch("/api/ui/apps-session", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: "{}",
    cache: "no-store",
    credentials: "same-origin",
  }).then((r) => {
    if (r.ok) { appsSession.at = Date.now(); appsSession.token = mine; }
    return r.ok;
  }).catch(() => false).finally(() => { appsSession.busy = null; });
  return appsSession.busy;
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") primeAppsSession();
});
document.addEventListener("pointerdown", (e) => {
  if (e.target && e.target.closest && e.target.closest("a.deskIcon[data-starter]")) primeAppsSession();
}, true);
function clearPairSession() {
  const mine = token;
  token = "";
  // Only drop the saved token when it is this tab's (a newer one from
  // another tab's re-pair must survive).
  try {
    const saved = localStorage.getItem(TOKEN_KEY) || "";
    if (saved && saved === mine) localStorage.removeItem(TOKEN_KEY);
    else if (saved) token = saved;
  } catch (_) {}
  appsSession.token = ""; appsSession.at = 0;
  setPairIcon();
}
window.addEventListener("storage", (e) => {
  if (e.key !== TOKEN_KEY) return;
  const v = e.newValue || "";
  if (v && v !== token) {
    token = v;
    appsSession.token = ""; appsSession.at = 0;
    primeAppsSession(true);
    hideNotPaired();
    if (!browserPaired) { startAppStatus(); startOpenAppEvents(); }
  }
  setPairIcon();
});
/** Pairing state for the link icon next to the logo: local | paired | unpaired. */
let pairUiState = detectLocalHost() ? "local" : (token ? "paired" : "unknown");
function setPairIcon(stateName) {
  if (stateName) pairUiState = stateName;
  if (detectLocalHost()) pairUiState = "local";
  for (const el of document.querySelectorAll(".pairLink")) {
    el.dataset.state = pairUiState;
    const t = pairUiState === "local" ? "Stick screen (no pairing needed)"
      : pairUiState === "paired" ? "This browser is paired"
      : pairUiState === "unpaired" ? "Not paired — click to pair this browser" : "Checking pairing…";
    el.title = t;
    el.setAttribute("aria-label", t);
  }
}
/** 401 anywhere: drop this tab's token and show the re-pair screen. */
function pairLost(msg) {
  clearPairSession();
  setPairIcon("unpaired");
  showNotPaired(msg);
}
function showNotPaired(msg) {
  if (detectLocalHost()) return;
  const box = document.getElementById("notPaired");
  if (!box) { openSettings("devices"); return; }
  box.hidden = false;
  box.removeAttribute("hidden");
  const m = document.getElementById("npMsg");
  if (m && msg) m.textContent = msg;
  const inp = document.getElementById("npCode");
  if (inp) setTimeout(() => inp.focus(), 0);
}
function hideNotPaired() {
  const box = document.getElementById("notPaired");
  if (box) { box.hidden = true; box.setAttribute("hidden", ""); }
}
async function pairWithCode(v) {
  const r = await fetch("/api/pair", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-StickLLM-Client": "ui" },
    body: JSON.stringify({ code: v }),
    credentials: "same-origin",
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.message || j.error || "Pair failed");
  token = j.token; localStorage.setItem(TOKEN_KEY, token);
  appsSession.token = token; appsSession.at = Date.now();
  setPairIcon("paired");
  hideNotPaired();
  return j;
}
async function requestKioskCode() {
  const out = document.getElementById("npMsg");
  try {
    const r = await fetch("/api/pair/request", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-StickLLM-Client": "ui" }, body: "{}",
    });
    const j = await r.json().catch(() => ({}));
    const msg = j.message || (r.ok ? "Look at the stick screen for the code." : `Request failed (${r.status})`);
    if (out) out.textContent = msg;
    toast(msg);
  } catch (e) { if (out) out.textContent = e.message; }
}
// One tab per app (0.5.3). Every app (starter, catalog add-on, Office, Agent
// Zero) opens in its own named browser tab: "stickllm-<id>". A second click
// switches to that tab instead of opening another one. That only works when
// the tab keeps its name and stays reachable from this page, so app links
// never use noopener and the opener is never cleared. appTabs keeps the
// handle; after a reload of this page window.open("", name) finds the tab
// again by name. A cross-origin page in it (an add-on, Agent Zero) cannot be
// read, which also tells "already open" apart from a fresh about:blank tab.
const appTabs = new Map();
function appTabHandle(target) {
  const w = appTabs.get(target);
  if (w && !w.closed) return w;
  appTabs.delete(target);
  return null;
}
function appTabIsBlank(w) {
  try {
    const h = String(w.location.href || "");
    return h === "" || h === "about:blank";
  } catch (e) {
    return false;
  }
}
function focusAppTab(w) {
  try { w.focus(); } catch (e) { /* the browser decides */ }
  return w;
}
// url: where a fresh tab goes. resolve(): optional promise of a better URL
// (a paired LAN browser's one-time sign-in link). force: navigate even when
// the tab is already open (Office opening a given document).
function openNamedTab(target, url, resolve, force) {
  let w = appTabHandle(target);
  if (!w) {
    try { w = window.open("", target); } catch (e) { w = null; }
    if (!w) return null;
    appTabs.set(target, w);
    if (!appTabIsBlank(w) && !force) return focusAppTab(w);
  } else if (!force) {
    return focusAppTab(w);
  }
  // Cut the opener link before the app loads (no reverse tabnabbing); the
  // tab keeps its name, so window.open("", target) still finds it later.
  try { w.opener = null; } catch (e) {}
  const go = (u) => { try { w.location.href = u || url; } catch (e) {} };
  if (resolve) Promise.resolve().then(resolve).then(go, () => go(url));
  else go(url);
  return focusAppTab(w);
}
const AGENT_TAB = "stickllm-agent-zero";
function agentPageUrl(status) {
  if (status && status.agent_url) return status.agent_url;
  const host = location.hostname || "127.0.0.1";
  if (host === "127.0.0.1" || host === "localhost" || host === "::1") {
    return "http://127.0.0.1:5099/";
  }
  return "https://" + host + ":5443/";
}
function agentIsInstalled(s) {
  return !!(s && (s.image_present || s.state === "running" || s.state === "starting" || s.state === "error"));
}
function agentInstallButtons() {
  return ["agentInstallBtn", "agentCatalogInstall"].map((id) => $("#" + id)).filter(Boolean);
}
function syncAgentDesktop(installed, href) {
  const desk = $("#deskIcons");
  if (!desk) return;
  let icon = $("#agentDeskIcon");
  if (!installed) {
    if (icon) icon.remove();
    return;
  }
  if (!icon) {
    icon = document.createElement("a");
    icon.id = "agentDeskIcon";
    icon.className = "deskIcon";
    icon.target = AGENT_TAB;
    icon.innerHTML = '<span class="deskGlyph deskGlyphLogo" aria-hidden="true"><img src="agent-zero.png?v=desk4" alt=""></span><span class="deskLabel">Agent</span>';
    desk.appendChild(icon);
  }
  icon.href = href;
}
async function refreshAgentLink() {
  const label = $("#agentLinkLabel");
  const link = $("#agentLink");
  if (!label && !link && !$("#agentCatalogInstall")) return;
  try {
    const r = await fetch("/api/agent/status", { cache: "no-store", headers: authHeaders() });
    if (r.status === 401 && !detectLocalHost() && pairUiState !== "unpaired") { ensurePaired().catch(() => {}); return; }
    if (!r.ok) return;
    const s = await r.json();
    const installed = agentIsInstalled(s);
    const href = agentPageUrl(s);
    if (link) {
      link.href = href;
      link.target = AGENT_TAB;
      link.removeAttribute("rel");
      link.hidden = !installed;
    }
    syncAgentDesktop(installed, href);
    const note = $("#agentLinkState");
    let detail = "Opens in a new tab";
    if (!s.vault_unlocked) detail = "Unlock vault on this page";
    else if (!s.settings_mounted) detail = "Unlock settings on this page";
    else if (s.state === "no_ssd") detail = "Needs a host drive";
    else if (s.needs_install || s.state === "needs_install") detail = "Not installed";
    else if (s.state === "installing") detail = "Installing";
    else if (s.state === "pull_failed") detail = "Install failed";
    else if (s.state === "starting") detail = "Starting";
    else if (s.state === "error") detail = (s.message || "Failed to start").replace(/\s+/g, " ").trim() || "Failed to start";
    else if (s.state === "low_space") detail = "Host drive is low on space";
    if (label) label.textContent = "Agent";
    if (note) note.textContent = detail;
    if (link) link.title = s.state === "error" ? detail : "";
    const deskIcon = $("#agentDeskIcon");
    if (deskIcon) deskIcon.title = s.state === "error" ? detail : "Agent";
    const message = s.message || "";
    for (const msg of [$("#agentInstallMsg"), $("#agentCatalogMsg")]) {
      if (msg) msg.textContent = message;
    }
    const show = !!(s.needs_install || s.state === "installing" || s.state === "pull_failed");
    for (const btn of agentInstallButtons()) {
      btn.hidden = !show;
      btn.disabled = s.state === "installing";
      btn.textContent = s.state === "installing" ? "Installing…" : "Install Agent Zero";
    }
    const text = s.state === "error" ? (s.message || detail) : (s.pull_log || "");
    for (const log of [$("#agentPullLog"), $("#agentCatalogPull")]) {
      if (!log) continue;
      log.hidden = !text;
      log.textContent = text;
    }
  } catch (e) { /* status is optional until the gateway is current */ }
}
async function installAgent(extra) {
  const row = $("#agentCatalogRow");
  try {
    const pre = await fetch("/api/apps", { cache: "no-store", headers: authHeaders() });
    if (pre.ok && row) {
      const doc = await pre.json();
      const warn = resourceWarningText(Number(row.dataset.diskMin), Number(row.dataset.ramMin), doc.resources);
      if (warn) toast(warn);
    }
  } catch (e) { /* a missing reading does not block install */ }
  for (const btn of agentInstallButtons()) {
    btn.disabled = true;
    btn.textContent = "Installing…";
  }
  try {
    const r = await fetch("/api/agent/install", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(extra || {}),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok && verifyGate(j, (more) => installAgent(Object.assign({}, extra || {}, more)))) {
      for (const btn of agentInstallButtons()) { btn.disabled = false; btn.textContent = "Install Agent Zero"; }
      return;
    }
    if (!r.ok) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    toast(j.message || "Installing Agent Zero");
  } catch (e) {
    toast("Install failed: " + e.message);
  }
  refreshAgentLink();
}
for (const btn of agentInstallButtons()) btn.onclick = () => installAgent();
function showApps() {
  mainView = "apps";
  const thread = $("#thread");
  const composer = $("#composer");
  const view = $("#appsView");
  if (thread) thread.hidden = true;
  if (composer) composer.hidden = true;
  if (view) view.hidden = false;
  const title = $("#chatTitle");
  if (title) title.textContent = "Apps";
  const btn = $("#appsLink");
  if (btn) { btn.classList.add("on"); btn.setAttribute("aria-current", "page"); }
  if (mobile()) toggleNav(false);
  refreshApps().catch(() => {});
}
function appsMessage(text) {
  const el = $("#appsMsg");
  if (!el) return;
  el.hidden = !text;
  el.textContent = text || "";
}
function selectApp(row) {
  if (!row) return;
  selectedAppId = row.dataset.app || "";
  $$(".appsRow").forEach((r) => {
    const on = r === row;
    r.classList.toggle("on", on);
    r.setAttribute("aria-pressed", on ? "true" : "false");
  });
  const empty = $("#appsEmpty");
  const selected = $("#appsSelected");
  if (empty) empty.hidden = true;
  if (selected) selected.hidden = false;
  const name = row.querySelector(".appName span");
  const desc = row.querySelector(".appName small");
  const installed = row.querySelector("[data-installed]");
  const state = row.querySelector("[data-state]");
  if ($("#appsSelName")) $("#appsSelName").textContent = name ? name.textContent : "";
  if ($("#appsSelDesc")) $("#appsSelDesc").textContent = desc ? desc.textContent : "";
  if ($("#appsSelLicense")) $("#appsSelLicense").textContent = row.dataset.license || "";
  if ($("#appsSelInstalled")) $("#appsSelInstalled").textContent = installed ? installed.textContent : "Not installed";
  if ($("#appsSelState")) $("#appsSelState").textContent = state ? state.textContent : "Not available yet";
  appsMessage("");
}
function gbText(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "";
  if (Math.abs(num - Math.round(num)) < 1e-9) return String(Math.round(num));
  return String(Math.round(num * 100) / 100);
}
function knownGb(value) {
  if (value === null || value === undefined || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}
function resourceWarningText(diskMin, ramMin, resources) {
  if (!resources || typeof resources !== "object") return "";
  const parts = [];
  const free = knownGb(resources.free_disk_gb);
  const ram = knownGb(resources.ram_gb);
  if (Number.isFinite(diskMin) && diskMin > 0 && free !== null && free < diskMin) {
    parts.push("Host SSD has about " + gbText(free) + " GB free, below the " + gbText(diskMin) + " GB minimum.");
  }
  if (Number.isFinite(ramMin) && ramMin > 0 && ram !== null && ram < ramMin) {
    parts.push("This machine has about " + gbText(ram) + " GB RAM, below the " + gbText(ramMin) + " GB minimum.");
  }
  if (!parts.length) return "";
  return parts.join(" ") + " You can still install.";
}
function freeVramLabel(gpu) {
  if (!gpu || gpu.available !== true || !Array.isArray(gpu.gpus) || !gpu.gpus.length) {
    return "VRAM is unavailable";
  }
  let freeMib = 0;
  for (const g of gpu.gpus) {
    const total = Number(g.memory_total_mib);
    const used = Number(g.memory_used_mib);
    if (!Number.isFinite(total) || !Number.isFinite(used)) return "VRAM is unavailable";
    freeMib += Math.max(0, total - used);
  }
  const gb = freeMib / 1024;
  const shown = gb >= 10 ? String(Math.round(gb)) : String(Math.round(gb * 10) / 10);
  return "Free VRAM: " + shown + " GB";
}
function paintResourceWarnings(resources) {
  $$(".appsRow").forEach((row) => {
    const text = resourceWarningText(Number(row.dataset.diskMin), Number(row.dataset.ramMin), resources);
    let el = row.querySelector("[data-resource-warn]");
    if (!text) {
      if (el) el.remove();
      return;
    }
    if (!el) {
      el = document.createElement("small");
      el.className = "appWarn";
      el.setAttribute("data-resource-warn", "");
      const name = row.querySelector(".appName");
      if (name) name.appendChild(el);
    }
    el.textContent = text;
  });
}
async function refreshFreeVram() {
  let label = "VRAM is unavailable";
  try {
    const r = await fetch("/api/system", { cache: "no-store", headers: authHeaders() });
    if (r.ok) label = freeVramLabel((await r.json()).gpu);
  } catch (e) { /* nvidia-smi missing: leave VRAM unavailable */ }
  $$("[data-free-vram]").forEach((el) => { el.textContent = label; });
}
async function refreshApps() {
  refreshFreeVram().catch(() => {});
  const r = await fetch("/api/apps", { cache: "no-store", headers: authHeaders() });
  if (!r.ok) return;
  const j = await r.json();
  const apps = Array.isArray(j.apps) ? j.apps : [];
  const byId = new Map(apps.map((a) => [a.id, a]));
  let installedCount = 0;
  $$(".appsRow").forEach((row) => {
    const a = byId.get(row.dataset.app);
    if (!a) return;
    const pill = row.querySelector("[data-state]");
    const sub = row.querySelector("[data-installed]");
    if (pill) pill.textContent = a.label || "Not available yet";
    if (sub) sub.textContent = a.installed ? "Installed" : "Not installed";
    if (a.installed) installedCount += 1;
    paintAppActions(row, a);
    paintVerifyBadge(row, a.verification);
  });
  paintResourceWarnings(j.resources);
  syncCatalogDesktop(apps);
  const empty = $("#appsInstalledEmpty");
  if (empty) empty.hidden = installedCount > 0;
  if (!selectedAppId) return;
  const row = $(`.appsRow[data-app="${selectedAppId}"]`);
  if (!row || !$("#appsSelected") || $("#appsSelected").hidden) return;
  const pill = row.querySelector("[data-state]");
  const sub = row.querySelector("[data-installed]");
  if ($("#appsSelInstalled")) $("#appsSelInstalled").textContent = sub ? sub.textContent : "Not installed";
  if ($("#appsSelState")) $("#appsSelState").textContent = pill ? pill.textContent : "Not available yet";
}
// Desktop icons for installed catalog apps (ONLYOFFICE Docs and the add-ons).
// Built-in starter apps keep their fixed icons in index.html; everything the
// catalog says is installed and openable gets an icon here, and loses it on
// removal. Paired LAN browsers go through the add-on's open link (a signed
// URL on the right host); the kiosk and same-origin pages follow open_url.
const catalogApps = new Map();
const DESK_APP_GLYPHS = {
  onlyoffice: { label: "Office", color: "#1d4ed8", svg: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 12h6M10 16h6"/>' },
  "tasks-md": { label: "Tasks", color: "#4f46e5", svg: '<path d="M5 7l2 2 3-3M5 13l2 2 3-3M13 8h6M13 14h6M5 19h14"/>' },
  paisa: { label: "Budget", color: "#9333ea", svg: '<path d="M12 3v18M16 7.5c-.8-1-2.2-1.5-4-1.5-2.2 0-3.5 1-3.5 2.6 0 3.8 7.5 2 7.5 6 0 1.7-1.5 2.9-4 2.9-1.9 0-3.4-.6-4.2-1.7"/>' },
  trilium: { label: "Notes", color: "#b45309", svg: '<path d="M5 4h10l4 4v12H5z"/><path d="M9 10h6M9 14h6M9 18h3"/>' },
  "node-red": { label: "Node-RED", color: "#b91c1c", svg: '<rect x="3" y="9" width="6" height="6" rx="1"/><rect x="15" y="4" width="6" height="6" rx="1"/><rect x="15" y="14" width="6" height="6" rx="1"/><path d="M9 12c3 0 3-5 6-5M9 12c3 0 3 5 6 5"/>' },
  comfyui: { label: "ComfyUI", color: "#0e7490", svg: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.5 12h3l4-5M11.5 12l4 5"/>' },
};
function deskAppOpenable(a) {
  return !!(a && a.installed && a.open_url && a.installer);
}
function syncCatalogDesktop(apps) {
  const desk = $("#deskIcons");
  catalogApps.clear();
  for (const a of apps) if (a && a.id) catalogApps.set(a.id, a);
  if (!desk) return;
  const want = new Set();
  for (const a of apps) {
    if (!deskAppOpenable(a)) continue;
    want.add(a.id);
    let icon = desk.querySelector('a.deskIcon[data-catalog-app="' + CSS.escape(a.id) + '"]');
    const g = DESK_APP_GLYPHS[a.id] || { label: a.tile || a.name || a.id, color: "#475569", svg: '<rect x="4" y="4" width="16" height="16" rx="3"/>' };
    if (!icon) {
      icon = document.createElement("a");
      icon.className = "deskIcon";
      icon.dataset.catalogApp = a.id;
      const glyph = document.createElement("span");
      glyph.className = "deskGlyph";
      glyph.setAttribute("aria-hidden", "true");
      glyph.style.background = g.color;
      glyph.innerHTML = '<svg viewBox="0 0 24 24">' + g.svg + "</svg>";
      const label = document.createElement("span");
      label.className = "deskLabel";
      label.textContent = g.label;
      icon.append(glyph, label);
      const agent = $("#agentDeskIcon");
      if (agent) desk.insertBefore(icon, agent); else desk.appendChild(icon);
    }
    icon.title = a.display_name || a.name || g.label;
    icon.setAttribute("href", a.open_url);
    icon.setAttribute("target", "stickllm-" + a.id);
    icon.dataset.openLink = a.open_link || "";
    icon.dataset.appId = a.id;
  }
  desk.querySelectorAll("a.deskIcon[data-catalog-app]").forEach((el) => {
    if (!want.has(el.dataset.catalogApp)) el.remove();
  });
}
if ($("#deskIcons")) $("#deskIcons").addEventListener("click", (e) => {
  const icon = e.target.closest('a.deskIcon[target^="stickllm-"]');
  if (!icon || icon.id === "agentDeskIcon") return;
  if (e.button || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  if (!openAppPaired(icon)) location.href = icon.href;
});
// Hash pins (docs/VERIFIED.md). Each catalog row shows Verified, Changed
// upstream or Not verified. The gateway refuses a changed upstream build
// ("blocked") and anything off the list ("unverified"); the user decides here
// with a typed confirm. Agent Zero can never skip this screen.
const UNVERIFIED_WARNING = "Not verified by StickLLM: this hasn't been checked and may be unsafe";
const VERIFY_BADGE = {
  verified: { cls: "ok", text: "Verified" },
  changed: { cls: "bad", text: "Changed upstream" },
  blocked: { cls: "bad", text: "Blocked" },
  unverified: { cls: "warn", text: "Not verified" },
};
function verifyBadgeTitle(v) {
  if (!v) return "";
  if (v.status === "verified") return (v.image ? v.image + ":" + (v.version || "") + "\n" : "") + "Pinned " + (v.manifest_digest || "");
  return v.message || "";
}
function paintVerifyBadge(row, v) {
  const host = row && row.querySelector(".appName > span");
  if (!host) return;
  let b = host.querySelector(".vbadge");
  const look = v && VERIFY_BADGE[v.status];
  if (!look) { if (b) b.remove(); return; }
  if (!b) { b = document.createElement("span"); host.appendChild(b); }
  b.className = "pill vbadge " + look.cls;
  b.dataset.verify = v.status;
  b.textContent = look.text;
  b.title = verifyBadgeTitle(v);
}
// j is the gateway's refusal. Returns true when a confirm box took over;
// retry(extra) re-sends the same install with the user's answer.
function verifyGate(j, retry) {
  if (!j) return false;
  const v = j.verification || {};
  if (j.error === "blocked") {
    confirmBox({
      title: "Changed upstream",
      text: j.message || "This app changed upstream since StickLLM verified it.",
      extra: "The new build stays blocked until StickLLM verifies it." + (v.version ? " Last verified: " + v.version + " (" + String(v.manifest_digest || "").slice(0, 19) + "…)." : ""),
      word: "VERIFIED",
      ok: "Install verified version",
      cb: () => retry({ verified_version: true }),
    });
    return true;
  }
  if (j.error === "unverified") {
    confirmBox({
      title: "Not verified by StickLLM",
      text: UNVERIFIED_WARNING + ".",
      extra: "Install only if you trust where it comes from.",
      word: "INSTALL",
      ok: "Install anyway",
      cb: () => retry({ accept_unverified: true }),
    });
    return true;
  }
  return false;
}
// Rows with an installer (ONLYOFFICE and the starter add-ons) carry their
// own Install / Open / Remove controls. Open goes to a named tab, never a popup.
const APP_BUSY_STATES = new Set(["installing", "removing", "starting"]);
function paintAppActions(row, a) {
  const box = row.querySelector("[data-actions-for]");
  if (!box) return;
  const install = box.querySelector('[data-app-act="install"]');
  const remove = box.querySelector('[data-app-act="uninstall"]');
  const open = box.querySelector("[data-app-open]");
  const live = !!a.installer;
  const busy = APP_BUSY_STATES.has(String(a.state || ""));
  box.hidden = !live;
  if (install) { install.hidden = !live || !!a.installed; install.disabled = busy; }
  if (remove) { remove.hidden = !live || !a.installed; remove.disabled = busy; }
  if (open) {
    open.hidden = !live || !a.installed;
    if (a.open_url) open.setAttribute("href", a.open_url);
    open.dataset.openLink = a.open_link || "";
  }
  const msg = row.querySelector("[data-app-msg]");
  if (msg && live) {
    const text = a.installed && a.running ? "" : (a.message || "");
    if (!msg.dataset.sticky) { msg.textContent = text; msg.hidden = !text; }
  }
}
function appRowMessage(id, text) {
  const row = $(`.appsRow[data-app="${id}"]`);
  const msg = row ? row.querySelector("[data-app-msg]") : null;
  if (!msg) return;
  msg.textContent = text || "";
  msg.hidden = !text;
  msg.dataset.sticky = text ? "1" : "";
  if (text) setTimeout(() => { msg.dataset.sticky = ""; }, 20000);
}
// Desktop icon or Apps-page Open: the app's own tab, reused. A paired LAN
// browser signs in to an add-on through its one-time open link; the kiosk
// and same-origin pages (Office at /apps/docs/) follow the plain link.
function openAppPaired(a) {
  const box = a.closest("[data-actions-for]");
  const id = box ? box.dataset.actionsFor : (a.dataset.appId || a.dataset.catalogApp || a.dataset.starter || "");
  const link = a.dataset.openLink || "";
  const target = a.getAttribute("target") || ("stickllm-" + id);
  const href = a.href;
  let resolve = null;
  if (id && link && !detectLocalHost() && token) {
    resolve = async () => {
      try {
        const r = await fetch(link, {
          method: "POST", cache: "no-store",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ id }),
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.url) return j.url;
        appRowMessage(id, j.message || "Could not sign this browser in to the app. Try Open again.");
      } catch (err) { /* follow the plain link; the app page explains pairing */ }
      return href;
    };
  }
  return !!openNamedTab(target, href, resolve);
}
async function appsActFor(id, action, btn, extra) {
  if (!id) return;
  if (action === "uninstall" && btn && btn.dataset.confirm !== "1") {
    btn.dataset.confirm = "1";
    btn.textContent = "Click again to remove";
    setTimeout(() => { btn.dataset.confirm = ""; btn.textContent = "Remove"; }, 5000);
    return;
  }
  if (btn) { btn.disabled = true; btn.dataset.confirm = ""; if (action === "uninstall") btn.textContent = "Remove"; }
  try {
    const r = await fetch("/api/apps/" + action, {
      method: "POST",
      cache: "no-store",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(Object.assign({ id }, extra || {})),
    });
    const j = await r.json().catch(() => ({}));
    appRowMessage(id, j.message || (r.ok ? "" : "Nothing was changed."));
    if (!r.ok && verifyGate(j, (more) => appsActFor(id, action, btn, Object.assign({}, extra || {}, more)))) return;
    if (r.ok && j.started === true) {
      [3, 10, 20, 40, 60, 120, 240, 480].forEach((sec) => setTimeout(() => refreshApps().catch(() => {}), sec * 1000));
    }
  } catch (e) {
    appRowMessage(id, "Nothing was changed.");
  } finally {
    if (btn) btn.disabled = false;
    refreshApps().catch(() => {});
  }
}
async function appsAct(action, extra) {
  if (!selectedAppId) return;
  const installBtn = $("#appsInstall");
  const removeBtn = $("#appsUninstall");
  if (installBtn) installBtn.disabled = true;
  if (removeBtn) removeBtn.disabled = true;
  try {
    const r = await fetch("/api/apps/" + action, {
      method: "POST",
      cache: "no-store",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(Object.assign({ id: selectedAppId }, extra || {})),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok && verifyGate(j, (more) => appsAct(action, Object.assign({}, extra || {}, more)))) {
      appsMessage(j.message || "");
      return;
    }
    // ONLYOFFICE installs in the background: started, not installed yet.
    const succeeded = r.ok && j.ok === true && (action !== "install" || j.installed === true || j.started === true);
    if (!succeeded) {
      appsMessage(j.message || (action === "install"
        ? "No installer yet. This app was not installed."
        : "This app was not installed from the Apps page. Nothing was removed."));
      return;
    }
    appsMessage(j.message || "");
    if (j.started === true) {
      [5, 15, 30, 60, 120, 240].forEach((sec) => setTimeout(() => refreshApps().catch(() => {}), sec * 1000));
    }
  } catch (e) {
    appsMessage(action === "install"
      ? "No installer yet. This app was not installed."
      : "Nothing was removed.");
  } finally {
    if (installBtn) installBtn.disabled = false;
    if (removeBtn) removeBtn.disabled = false;
    refreshApps().catch(() => {});
  }
}
if ($("#appsLink")) $("#appsLink").onclick = () => showApps();
function openAppsFromHash() {
  if ((location.hash || "") === "#apps") showApps();
}
openAppsFromHash();
window.addEventListener("hashchange", openAppsFromHash);
function toggleAppsMenu(force) {
  const menu = $("#appsMenu");
  if (!menu) return;
  const open = typeof force === "boolean" ? force : menu.hidden;
  menu.hidden = !open;
  const btn = $("#appsMenuBtn");
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
}
if ($("#appsMenuBtn")) {
  $("#appsMenuBtn").onclick = (ev) => {
    ev.stopPropagation();
    toggleAppsMenu();
  };
}
// A click on the desktop, including an app icon, closes the menu. The icon's link still opens.
document.addEventListener("click", (ev) => {
  const menu = $("#appsMenu");
  if (!menu || menu.hidden) return;
  if (menu.contains(ev.target)) return;
  const btn = $("#appsMenuBtn");
  if (btn && (ev.target === btn || btn.contains(ev.target))) return;
  toggleAppsMenu(false);
});
if ($("#appsList")) $("#appsList").addEventListener("click", (e) => {
  if (e.target.closest("#agentCatalogInstall") || e.target.closest("#agentCatalogRow")) return;
  const act = e.target.closest("[data-app-act]");
  if (act) {
    e.preventDefault();
    const box = act.closest("[data-actions-for]");
    appsActFor(box ? box.dataset.actionsFor : "", act.dataset.appAct, act);
    return;
  }
  const open = e.target.closest("[data-app-open]");
  if (open) {
    if (e.button || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    if (!openAppPaired(open)) location.href = open.href;
    return;
  }
  const row = e.target.closest(".appsRow");
  if (row) selectApp(row);
});
if ($("#appsInstall")) $("#appsInstall").onclick = () => appsAct("install");
if ($("#appsUninstall")) $("#appsUninstall").onclick = () => appsAct("uninstall");
async function pairStatus() {
  const r = await fetch("/api/pair/status", { cache: "no-store" });
  return r.json();
}
async function control(action, params = {}) {
  const r = await fetch("/api/control", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ action, params }),
  });
  if (r.status === 401) {
    pairLost("This browser is no longer paired with the stick.");
    throw new Error("Pair required");
  }
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status} (no JSON)` }));
  if (!r.ok) {
    const e = new Error(j.message && j.error ? `${j.error}: ${j.message}` : (j.error || j.message || `HTTP ${r.status}`));
    e.status = r.status;
    throw e;
  }
  return j;
}

let tt;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(tt); tt = setTimeout(() => (t.hidden = true), 2800);
}

function setTheme(t) {
  state.theme = t; document.documentElement.dataset.theme = t;
  $$("#themeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.theme === t));
}
$("#themeBtn").onclick = () => setTheme(state.theme === "dark" ? "light" : "dark");
$$("#themeSeg button").forEach((b) => (b.onclick = () => setTheme(b.dataset.theme)));

function heroModeLine(m) {
  return m === "vault"
    ? "Everything runs on this stick. Chats are saved encrypted in your vault."
    : "Everything runs on this stick. Ephemeral — lost at reboot.";
}
function applyModeUi(m) {
  state.mode = m; sessionMode = m;
  $$("[data-mode]").forEach((b) => {
    const on = b.dataset.mode === m;
    b.classList.toggle("on", on); b.setAttribute("aria-checked", on);
  });
  $("#modeHint").textContent = m === "vault"
    ? "Chats are saved in your encrypted vault."
    : "Nothing is written to disk. Chats are lost at reboot.";
  $("#chatWhere").textContent = m === "vault"
    ? "Vault: saved encrypted on the host SSD."
    : "Ephemeral: in memory only, gone at reboot.";
  const note = $("#composerNote");
  if (micState === "idle" && note) {
    const cur = String(note.textContent || "");
    if (!cur.startsWith("Sent ") && cur !== "The recording was empty") note.textContent = "";
  }
  // Keep empty-state hero in sync when mode toggles without a new chat.
  const heroP = $("#thread .empty p");
  if (heroP) heroP.textContent = heroModeLine(m);
}

async function setSessionMode(m) {
  const next = m === "vault" ? "vault" : "ephemeral";
  const prev = sessionMode;
  if (sessionModeBusy) return;
  sessionModeBusy = true;
  try {
    if (next === "vault") {
      let vault = {};
      try { vault = await control("vault_status"); } catch (_) {}
      const st = String(vault.status || "").toLowerCase();
      // A locked vault reads "absent" before its first unlock after boot
      // (usb_settings "present-locked"); vaultIsAbsent() knows that.
      if (vaultIsAbsent(vault) || (!st && !vault.usb_settings)) {
        applyModeUi(prev);
        toast("No vault yet — create or attach one in Storage");
        openSettings("storage");
        return;
      }
      if (!(st === "unlocked" || vault.mounted)) {
        applyModeUi(prev);
        toast("Unlock the vault first");
        await focusVaultUnlock();
        return;
      }
      state.vaultOpen = true;
      setVaultChrome(true);
    }
    const r = await fetch("/api/session-mode", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ mode: next }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    applyModeUi(next);
    if (next === "ephemeral") {
      // Leaving Vault mode locks the vault server-side: same clear as a lock.
      if (prev === "vault" || state.vaultOpen) clearOnLock();
      state.vaultOpen = false;
      setVaultChrome(false);
    }
    toast(next === "vault" ? "Vault mode" : "Ephemeral mode");
    renderConvs();
    if (next === "vault") loadVaultChats().catch(() => {});
  } catch (e) {
    applyModeUi(prev);
    toast("Mode switch failed: " + e.message);
  } finally {
    sessionModeBusy = false;
  }
}
$$("[data-mode]").forEach((b) => (b.onclick = () => setSessionMode(b.dataset.mode)));

// Health and control report the vault as {status, mounted}; older gateways
// sent a bare "unlocked"/"locked" string. Accept both.
function vaultIsOpen(v) {
  if (typeof v === "string") return v.toLowerCase() === "unlocked";
  if (!v || typeof v !== "object") return false;
  return String(v.status || "").toLowerCase() === "unlocked" || !!v.mounted;
}

// "absent" = no vault created or attached yet. Say so instead of "locked".
// Before the first unlock after boot the big vault is not bound yet, so the
// status reads "absent" even though the stick's settings vault knows where it
// is (usb_settings "present-locked"). That is a locked vault, not a missing
// one; treating it as missing made "No vault set up" flash during unlock.
// While an unlock is running we never say "No vault set up" either.
let vaultUnlocking = false;
function vaultIsAbsent(v) {
  if (vaultUnlocking) return false;
  if (typeof v === "string") return v.toLowerCase() === "absent";
  if (!v || typeof v !== "object") return false;
  const usb = String(v.usb_settings || "").toLowerCase();
  if (usb === "present-locked" || usb === "unlocked") return false;
  return !v.mounted && String(v.status || "").toLowerCase() === "absent";
}

// Inline message under the unlock form (errors must not vanish with a toast).
function unlockMessage(text) {
  const el = $("#unlockMsg");
  if (!el) return;
  el.textContent = text || "";
  el.hidden = !text;
}

// Take the user to the passcode box. If the form is hidden (the page thinks
// the vault is open, or there is none) say why instead of failing silently.
async function focusVaultUnlock() {
  openSettings("storage");
  const form = $("#unlockForm");
  if (form && form.hidden) {
    try { await refreshStorage(); } catch (_) {}
  }
  if (!form || form.hidden) {
    const msg = state.vaultOpen
      ? "The vault is already unlocked."
      : "The unlock form is not available. Choose or create a vault below first.";
    toast(msg);
    unlockMessage(state.vaultOpen ? "" : msg);
    return false;
  }
  setTimeout(() => $("#vaultPass")?.focus(), 50);
  return true;
}

// Bumped on every vault open/locked change and when an unlock starts. A
// health/status answer requested before that is stale: applying it repainted
// "No vault set up" (and the Ephemeral tab, and a clear) just after unlock.
let vaultEpoch = 0, vaultLocking = false;
const vaultBusy = () => vaultUnlocking || vaultLocking;
function setVaultChrome(open, absent = false) {
  if (!!open !== !!state.vaultOpen) vaultEpoch += 1;
  // Open -> locked from anywhere (another browser, the kiosk lock combo, a
  // lock in Settings): clear the screen too, not only the chrome (0.5.4).
  if (!open && state.vaultOpen && !vaultUnlocking && !clearingOnLock) clearOnLock();
  state.vaultOpen = open;
  // The mode tabs follow the vault: Vault is highlighted only while it is
  // unlocked, Ephemeral whenever it is locked (first load included).
  if (!open && sessionMode === "vault") applyModeUi("ephemeral");
  const none = !open && !!absent;
  $("#vaultCard")?.classList.toggle("open", open);
  if ($("#vcState")) $("#vcState").textContent = open ? "Vault unlocked" : (none ? "No vault set up" : "Vault locked");
  if ($("#unlockForm")) $("#unlockForm").hidden = open;
  if (open) unlockMessage("");
  if ($("#lockBtn2")) $("#lockBtn2").hidden = !open;
  if ($("#lockBtn")) $("#lockBtn").hidden = !open;
  if ($("#popVault")) $("#popVault").textContent = open ? "Unlocked" : (none ? "Not set up" : "Locked");
}

// Lock means nothing from any chat stays readable on this screen: the
// transcript, the chat list, drafts, attachments, the in-memory history, saved
// chat titles and open app tabs (vault data) all go. Ephemeral chats too.
function clearOnLock() {
  if (clearingOnLock) return;
  clearingOnLock = true;
  vaultEpoch += 1;
  try {
    try { if (sendAbort) sendAbort.abort(); } catch (_) {}
    try { if (typeof stopSpeak === "function") stopSpeak(); } catch (_) {}
    state.vaultOpen = false;
    state.chats = [];
    state.ephemeral = [];
    state.current = null;
    state.attach = [];
    activeChatId = null;
    for (const w of appTabs.values()) { try { if (w && !w.closed) w.close(); } catch (_) {} }
    appTabs.clear();
    $$("textarea").forEach((t) => { t.value = ""; });
    try { if (typeof renderAttach === "function") renderAttach(); } catch (_) {}
    applyModeUi("ephemeral");
    setVaultChrome(false);
    newChat();
    try { renderSaved(); } catch (_) {}
  } finally {
    clearingOnLock = false;
  }
}

async function lockVault() {
  // Screen first, so nothing stays readable while the lock call runs.
  clearOnLock();
  vaultLocking = true;
  try {
    const res = await control("vault_lock");
    toast(res.ok !== false ? "Vault locked" : ("Lock failed: " + (res.error || "unknown")));
    setVaultChrome(false);
  } catch (e) { toast("Lock failed: " + e.message); }
  finally { vaultLocking = false; vaultEpoch += 1; }
  try {
    await fetch("/api/session-mode", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ mode: "ephemeral" }),
    });
  } catch (_) {}
}
$("#lockBtn").onclick = () => lockVault();
$("#lockBtn2").onclick = () => lockVault();

const mobile = () => matchMedia("(max-width:820px)").matches;
function toggleNav(force) {
  if (mobile()) {
    const open = force ?? !app.classList.contains("navOpen");
    app.classList.toggle("navOpen", open); $("#scrim").hidden = !open;
  } else app.classList.toggle("collapsed", force === undefined ? undefined : !force);
}
$("#menuBtn").onclick = () => toggleNav();
$("#collapseBtn").onclick = () => (mobile() ? toggleNav(false) : app.classList.add("collapsed"));
$("#scrim").onclick = () => toggleNav(false);

function md(t) {
  return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .split(/\n\n/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
}
function msgHtml(m, i) {
  const src = m.src?.length
    ? `<details class="sources"><summary>${m.src.length} web source${m.src.length > 1 ? "s" : ""}</summary>${m.src.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>`).join("")}</details>`
    : "";
  const cls = m.r === "system" ? "system" : m.r;
  const av = m.r === "ai" ? "S" : m.r === "system" ? "!" : "";
  const pics = (m.imgs || []).map((u) => `<img class="msgImg" alt="" src="${esc(u)}">`).join("");
  const warn = m.warn ? `<div class="attWarn">${esc(m.warn)}</div>` : "";
  const speak = voiceMode && m.r === "ai" && !m.pending && String(m.t || "").trim()
    ? `<div class="msgTools"><button type="button" class="iconBtn sm speakBtn" data-speak="${i}" title="Read aloud" aria-label="Read aloud"><svg viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 010 7"/></svg></button></div>`
    : "";
  const undo = m.appUndo && !m.pending
    ? `<div class="msgTools"><button type="button" class="appUndoBtn" data-appundo="${i}" title="Undo this change in ${esc(APPAGENT_NAMES[m.appUndo] || m.appUndo)}">Undo</button></div>`
    : "";
  const parts = m.r === "ai" ? splitThink(m.t) : { answer: m.t || "", think: "" };
  const think = m.r === "ai" && !m.pending ? [m.think, parts.think].filter(Boolean).join("\n\n") : "";
  const why = think ? `<details class="reasoning"><summary>Show reasoning</summary>${md(think)}</details>` : "";
  const wait = `<span class="typing"><i></i><i></i><i></i></span>${m.thinking ? '<span class="thinkNote">Thinking…</span>' : ""}`;
  return `<div class="msg ${cls}"><div class="av">${av}</div><div class="body">${pics}${m.pending ? wait : why + md(parts.answer)}${warn}${src}${speak}${undo}</div></div>`;
}
function renderThread(opts) {
  if (!(opts && opts.keepSpeech) && typeof stopSpeak === "function") stopSpeak();
  const th = $("#thread"), c = state.current;
  if (mainView !== "apps") $("#chatTitle").textContent = c ? c.title : "New chat";
  if (!c || !c.msgs.length) {
    th.innerHTML = `<div class="empty"><span class="logo lg"></span><h2>What can I help with?</h2>
      <p>${esc(heroModeLine(state.mode))}</p>
      <div class="sugg"><button>Summarize a long article I paste in</button><button>Write a bash script to rename photos by date</button>
      <button>Explain how LUKS encryption works</button><button>Draft a polite follow-up email</button></div></div>`;
    $$(".sugg button", th).forEach((b) => (b.onclick = () => { $("#input").value = b.textContent; send(); }));
    return;
  }
  th.innerHTML = `<div class="msgs">${c.msgs.map((m, i) => msgHtml(m, i)).join("")}</div>`;
  th.scrollTop = th.scrollHeight;
}
function paintStream(text) {
  const th = $("#thread");
  if (!th) return;
  const bodies = th.querySelectorAll(".msg.ai .body");
  const body = bodies[bodies.length - 1];
  if (!body) return;
  const typing = body.querySelector(".typing");
  if (typing) typing.remove();
  let slot = body.querySelector(".streamText");
  if (!slot) {
    slot = document.createElement("div");
    slot.className = "streamText";
    body.prepend(slot);
  }
  slot.innerHTML = md(String(text || ""));
  th.scrollTop = th.scrollHeight;
}
// 0.5.5: thinking models (Qwen3.5) put reasoning in reasoning_content, in
// <think>…</think>, an unclosed <think> (still streaming), or before an orphan
// </think> (the template opened it). Only the answer is shown; the rest is
// "think" for the collapsed Show reasoning box.
function splitThink(text) {
  let s = String(text || "");
  const think = [];
  s = s.replace(/<think>([\s\S]*?)<\/think>/gi, (_, t) => { think.push(t); return ""; });
  const open = s.search(/<think>/i);
  if (open >= 0) { think.push(s.slice(open + 7)); s = s.slice(0, open); }
  const last = s.toLowerCase().lastIndexOf("</think>");
  if (last >= 0) {
    think.unshift(s.slice(0, last).replace(/<\/think>/gi, ""));
    s = s.slice(last + 8);
  }
  return { answer: s, think: think.map((t) => t.trim()).filter(Boolean).join("\n\n") };
}
function stripThink(text) {
  return splitThink(text).answer;
}
function dropEmptyPlaceholder(text) {
  const raw = String(text || "");
  if (raw.trim() === "(empty response)") return "";
  return raw;
}
function renderConvs() {
  const list = $("#convList"); let html = "";
  if (state.ephemeral.length) {
    html += '<div class="convGroup">This session</div>';
    html += state.ephemeral.map((c) =>
      `<button class="conv ${state.current === c ? "on" : ""}" data-e="${c.id}"><span>${esc(c.title)}</span><span class="tag">temp</span></button>`
    ).join("");
  }
  if (state.mode === "vault" && state.vaultOpen && state.chats.length) {
    html += '<div class="convGroup">Saved in vault</div>';
    html += state.chats.map((c) => {
      const on = state.current && String(state.current.id) === String(c.id) ? "on" : "";
      const id = esc(c.id);
      return `<div class="convRow ${on}"><button type="button" class="conv" data-v="${id}"><span>${esc(c.title || c.id)}</span></button><button type="button" class="convDel" data-del="${id}" title="Delete this chat" aria-label="Delete this chat"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V5h6v2M8 7l1 13h6l1-13"/></svg></button></div>`;
    }).join("");
  } else if (state.mode === "vault" && !state.vaultOpen) {
    html += '<div class="convGroup">Saved chats</div><div class="convEmpty">Locked in the vault. <button class="link" id="unlockLink">Unlock</button></div>';
  } else if (!state.ephemeral.length) {
    html += '<div class="convEmpty">No chats yet</div>';
  }
  list.innerHTML = html;
  $$("[data-e]", list).forEach((b) => (b.onclick = () => {
    openChat(state.ephemeral.find((c) => String(c.id) === b.dataset.e));
    if (mobile()) toggleNav(false);
  }));
  $$("[data-v]", list).forEach((b) => (b.onclick = () => {
    openVaultChat(b.dataset.v);
    if (mobile()) toggleNav(false);
  }));
  $$("[data-del]", list).forEach((b) => (b.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    deleteVaultChat(b.dataset.del).catch((err) => toast(err.message));
  }));
  const ul = $("#unlockLink"); if (ul) ul.onclick = () => { focusVaultUnlock().catch(() => {}); };
}
function leaveApps() {
  if (mainView !== "apps") return;
  toggleAppsMenu(false);
  mainView = "chat";
  const view = $("#appsView");
  if (view) view.hidden = true;
  const thread = $("#thread");
  const composer = $("#composer");
  if (thread) thread.hidden = false;
  if (composer) composer.hidden = false;
  const btn = $("#appsLink");
  if (btn) { btn.classList.remove("on"); btn.removeAttribute("aria-current"); }
}
function openChat(c) { leaveApps(); state.current = c; activeChatId = c?.id || null; renderThread(); renderConvs(); }
function newChat() {
  leaveApps();
  state.current = null; activeChatId = null;
  messages.length = 1;
  messages[0] = { role: "system", content: "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful." };
  renderThread(); renderConvs(); $("#input").focus();
}
$("#newChatBtn").onclick = () => { newChat(); if (mobile()) toggleNav(false); };

async function ensurePaired(force = false) {
  try {
    syncToken();
    const st = await fetch("/api/pair/status", { cache: "no-store", headers: authHeaders() }).then((r) => r.json());
    if (st.local) { isLocalMode = true; setPairIcon("local"); return true; }
    if (!st.require_pair) { setPairIcon("paired"); return true; }
    // /api/health is public, so "the stick is paired" says nothing about this
    // browser: this_paired is computed from this request's Bearer/cookie.
    if (st.this_paired && !force) { setPairIcon("paired"); primeAppsSession(true); return true; }
    if (token) clearPairSession();
    setPairIcon("unpaired");
    showNotPaired(st.paired
      ? "The stick is paired with another browser. Re-pair this browser."
      : "Not paired — re-pair this browser.");
    return false;
  } catch (_) { return true; }
}

function formatCtxK(n) {
  const v = Math.round(Number(n));
  if (!Number.isFinite(v) || v <= 0) return "";
  if (v % 1024 === 0) return `${v / 1024}K`;
  if (v > 1024) return `${Math.round((v / 1024) * 10) / 10}K`;
  return String(v);
}
function contextUsedTokens(data, promptTok, genTok) {
  const usage = data?.usage || {};
  const total = Number(usage.total_tokens);
  if (Number.isFinite(total) && total > 0) return total;
  const promptAll = Number(usage.prompt_tokens);
  const completion = Number(usage.completion_tokens);
  if ((Number.isFinite(promptAll) && promptAll > 0) || (Number.isFinite(completion) && completion > 0)) {
    return (Number.isFinite(promptAll) && promptAll > 0 ? promptAll : 0)
      + (Number.isFinite(completion) && completion > 0 ? completion : 0);
  }
  const t = data?.timings || data?.llama_timings || {};
  const cacheN = Number(t.cache_n);
  const used = (Number.isFinite(cacheN) && cacheN > 0 ? cacheN : 0)
    + (Number.isFinite(promptTok) && promptTok > 0 ? promptTok : 0)
    + (Number.isFinite(genTok) && genTok > 0 ? genTok : 0);
  return used > 0 ? used : null;
}
function formatPerfBits(stats) {
  if (!stats) return "";
  const bits = [];
  if (stats.genTps != null) bits.push(`${stats.genTps.toFixed(1)} tok/s`);
  if (stats.promptTps != null) bits.push(`prompt ${stats.promptTps.toFixed(1)} tok/s`);
  if (stats.genTok != null) bits.push(`${stats.genTok} tok`);
  if (stats.ms != null) bits.push(`${(stats.ms / 1000).toFixed(1)}s`);
  if (stats.est) bits.push("~est");
  const ctx = loadedCtx > 0 ? loadedCtx : Number(stats.ctx);
  const label = formatCtxK(ctx);
  if (label) {
    const used = Number(stats.usedTok);
    if (Number.isFinite(used) && used > 0 && ctx > 0) {
      const pct = Math.max(0, Math.min(100, Math.round((100 * used) / ctx)));
      bits.push(`ctx ${label} · ${pct}%`);
    } else {
      bits.push(`ctx ${label}`);
    }
  }
  return bits.join(" · ");
}
function updatePerfStrip(stats) {
  lastPerf = stats || null;
  const text = formatPerfBits(stats);
  // Bottom line under composer — primary place.
  const bottom = $("#composerPerf");
  if (bottom) {
    bottom.textContent = text;
    bottom.hidden = !text;
  }
  // Keep a copy on the yellow TEST banner too.
  const top = $("#testPerf");
  if (top) {
    top.textContent = text;
    top.hidden = !text;
  }
}
function perfFromChatResponse(data, wallMs, replyText) {
  const t = data?.timings || data?.llama_timings || {};
  const genTps = Number(t.predicted_per_second ?? t.tokens_per_second ?? t.eval_per_second);
  const promptTps = Number(t.prompt_per_second ?? t.prompt_tokens_per_second);
  const genTok = Number(t.predicted_n ?? t.n_predicted ?? data?.usage?.completion_tokens);
  const promptTok = Number(t.prompt_n ?? t.n_prompt ?? data?.usage?.prompt_tokens);
  const predMs = Number(t.predicted_ms ?? t.eval_ms);
  if (Number.isFinite(genTps) && genTps > 0) {
    return {
      genTps,
      promptTps: Number.isFinite(promptTps) && promptTps > 0 ? promptTps : null,
      genTok: Number.isFinite(genTok) ? genTok : null,
      promptTok: Number.isFinite(promptTok) ? promptTok : null,
      usedTok: contextUsedTokens(data, promptTok, genTok),
      ctx: loadedCtx,
      ms: Number.isFinite(predMs) ? predMs : wallMs,
      est: false,
    };
  }
  // Fallback: rough estimate if llama timings absent ( ~4 chars/token ).
  const approxTok = Math.max(1, Math.round(String(replyText || "").length / 4));
  const sec = Math.max(0.05, wallMs / 1000);
  return {
    genTps: approxTok / sec,
    promptTps: null,
    genTok: Number.isFinite(genTok) ? genTok : approxTok,
    promptTok: Number.isFinite(promptTok) ? promptTok : null,
    usedTok: contextUsedTokens(data, promptTok, genTok),
    ctx: loadedCtx,
    ms: wallMs,
    est: true,
  };
}

let sendBusy = false;
let sendAbort = null;
let sendGen = 0;
let sendFlight = null;
let userStopGen = 0;
const CHAT_TOKENS = 1024;
const CHAT_TOKENS_RETRY = 4096;
// Two short spoken sentences. Voice off keeps the normal budget.
const VOICE_CHAT_TOKENS = 80;
const BUDGET_NOTE = "The model used its token budget and returned no answer.";
function textOfMessage(value) {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map((p) => (typeof p === "string" ? p : (p && p.text) || "")).join("").trim();
  }
  return "";
}
function answerFromChat(data) {
  const msg = data?.choices?.[0]?.message;
  if (!msg || typeof msg !== "object") return "";
  const content = textOfMessage(msg.content).replace(/<think>[\s\S]*?<\/think>/gi, "").replace(/<think>[\s\S]*$/i, "").trim();
  if (content) return content;
  return textOfMessage(msg.reasoning_content != null ? msg.reasoning_content : msg.reasoning);
}
function setSending(on) {
  sendBusy = on;
  const sendBtn = $("#sendBtn");
  const stopBtn = $("#stopBtn");
  if (sendBtn) sendBtn.hidden = !!on;
  if (stopBtn) stopBtn.hidden = !on;
}
function requestChatStop() {
  return fetch("/api/chat/stop", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: "{}",
  }).catch(() => {});
}
function stopReply() {
  userStopGen = sendGen;
  requestChatStop();
  stopSpeak();
  if (sendAbort) {
    try { sendAbort.abort(); } catch (_) {}
  }
  // A send that returned before its cleanup left this red Stop button up
  // with nothing left to abort. Restore Send unless a reply is still running.
  if (!sendFlight) setSending(false);
}
function dropApiUserTurn() {
  const last = messages[messages.length - 1];
  if (last && last.role === "user") messages.pop();
}
async function takeChat(gen, abort, body) {
  let lastMsg = "Still answering.";
  for (let i = 0; i < 20; i++) {
    if (gen !== sendGen || abort.signal.aborted || userStopGen === gen) {
      const err = new Error("bail");
      err.name = gen !== sendGen ? "Superseded" : "VoiceBail";
      throw err;
    }
    let r;
    try {
      r = await fetch("/api/chat", {
        method: "POST",
        signal: abort.signal,
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
      });
    } catch (e) {
      if (gen !== sendGen || (e && e.name === "AbortError") || userStopGen === gen) {
        const err = new Error("bail");
        err.name = gen !== sendGen ? "Superseded" : "VoiceBail";
        throw err;
      }
      throw e;
    }
    if (r.status === 409 && i < 19) {
      try {
        const err = await r.json();
        lastMsg = err.message || err.error || lastMsg;
      } catch (_) {}
      await new Promise((resolve) => setTimeout(resolve, 200));
      continue;
    }
    if (r.status === 401) {
      const err = new Error("bail");
      err.name = "PairRequired";
      throw err;
    }
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try {
        const err = await r.json();
        msg = err.message || err.error || msg;
      } catch (_) {}
      throw new Error(typeof msg === "string" ? msg : "The model did not answer.");
    }
    const data = await r.json();
    if (gen !== sendGen) {
      const err = new Error("bail");
      err.name = "Superseded";
      throw err;
    }
    if (data?.stopped || userStopGen === gen) {
      const err = new Error("bail");
      err.name = "VoiceBail";
      throw err;
    }
    return data;
  }
  throw new Error(lastMsg);
}
async function takeChatStream(gen, abort, body, onShown, opts) {
  const onThink = opts && opts.onThink;
  let lastMsg = "Still answering.";
  for (let i = 0; i < 20; i++) {
    if (gen !== sendGen || abort.signal.aborted || userStopGen === gen) {
      const err = new Error("bail");
      err.name = gen !== sendGen ? "Superseded" : "VoiceBail";
      throw err;
    }
    let r;
    try {
      r = await fetch("/api/chat", {
        method: "POST",
        signal: abort.signal,
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ ...body, stream: true }),
      });
    } catch (e) {
      if (gen !== sendGen || (e && e.name === "AbortError") || userStopGen === gen) {
        const err = new Error("bail");
        err.name = gen !== sendGen ? "Superseded" : "VoiceBail";
        throw err;
      }
      throw e;
    }
    if (r.status === 409 && i < 19) {
      try {
        const err = await r.json();
        lastMsg = err.message || err.error || lastMsg;
      } catch (_) {}
      await new Promise((resolve) => setTimeout(resolve, 200));
      continue;
    }
    if (r.status === 401) {
      const err = new Error("bail");
      err.name = "PairRequired";
      throw err;
    }
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try {
        const err = await r.json();
        msg = err.message || err.error || msg;
      } catch (_) {}
      throw new Error(typeof msg === "string" ? msg : "The model did not answer.");
    }
    const ctype = (r.headers.get("content-type") || "").toLowerCase();
    if (!ctype.includes("text/event-stream")) {
      const data = await r.json();
      if (gen !== sendGen) {
        const err = new Error("bail");
        err.name = "Superseded";
        throw err;
      }
      if (data?.stopped || userStopGen === gen) {
        return { shown: "", content: "", reasoning: "", stopped: true, web: null, attachments: null, usage: null };
      }
      const content = textOfMessage(data?.choices?.[0]?.message?.content);
      const reasoning = textOfMessage(data?.choices?.[0]?.message?.reasoning_content != null ? data.choices[0].message.reasoning_content : data?.choices?.[0]?.message?.reasoning);
      const answer = dropEmptyPlaceholder(stripThink(content)).trim();
      const think = [stripThink(reasoning).trim(), splitThink(content).think].filter(Boolean).join("\n\n");
      const shown = answer;
      if (shown && onShown) onShown(shown);
      return {
        shown,
        think,
        content,
        reasoning,
        stopped: false,
        web: data?.stickllm_web || null,
        attachments: data?.stickllm_attachments || null,
        usage: data?.usage || null,
      };
    }
    const reader = r.body && r.body.getReader ? r.body.getReader() : null;
    if (!reader) throw new Error("The model did not answer.");
    const dec = new TextDecoder();
    let buf = "";
    let content = "";
    let reasoning = "";
    let web = null;
    let attachments = null;
    let usage = null;
    let stopped = false;
    let errText = "";
    const applyBlock = (block) => {
      const line = block.split("\n").map((l) => l.trim()).filter((l) => l.startsWith("data:")).pop();
      if (!line) return;
      const payload = line.slice(5).trim();
      if (!payload || payload === "[DONE]") return;
      let ev;
      try { ev = JSON.parse(payload); } catch (_) { return; }
      if (ev.stickllm_web) web = ev.stickllm_web;
      if (ev.stickllm_attachments) attachments = ev.stickllm_attachments;
      if (ev.usage) usage = ev.usage;
      if (ev.done) {
        // The gateway repeats the full reply on the last event. Appending it
        // doubles the text and makes the speech buffer look new, so the first
        // sentence is thrown away and only spoken after the stream ends.
        if (!content && ev.content) content = String(ev.content);
        if (!reasoning && ev.reasoning) reasoning = String(ev.reasoning);
      } else {
        if (ev.content) content += String(ev.content);
        if (ev.reasoning) reasoning += String(ev.reasoning);
      }
      const answer = dropEmptyPlaceholder(stripThink(content));
      // 0.5.5: the bubble shows (and voice speaks) the answer only, never the
      // reasoning; while there is only reasoning it says "Thinking…".
      const shown = answer;
      if (shown.trim() && shown.trim() !== "(empty response)" && onShown) onShown(shown);
      else if (onThink && (reasoning.trim() || splitThink(content).think)) onThink();
      if (ev.stopped) stopped = true;
      if (ev.error && ev.done) errText = String(ev.error);
    };
    while (true) {
      if (gen !== sendGen || abort.signal.aborted || userStopGen === gen) {
        try { reader.cancel(); } catch (_) {}
        const err = new Error("bail");
        err.name = gen !== sendGen ? "Superseded" : "VoiceBail";
        throw err;
      }
      const step = await reader.read();
      if (step.done) break;
      buf += dec.decode(step.value, { stream: true });
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        applyBlock(buf.slice(0, cut));
        buf = buf.slice(cut + 2);
        if (!buf.includes("\n\n")) break;
        await new Promise((resolve) => setTimeout(resolve, 0));
        if (gen !== sendGen || abort.signal.aborted || userStopGen === gen) {
          try { reader.cancel(); } catch (_) {}
          const err = new Error("bail");
          err.name = gen !== sendGen ? "Superseded" : "VoiceBail";
          throw err;
        }
      }
    }
    if (buf.trim()) applyBlock(buf);
    if (errText && !stripThink(content).trim() && !stripThink(reasoning).trim()) throw new Error(errText);
    const answer = dropEmptyPlaceholder(stripThink(content)).trim();
    const think = [stripThink(reasoning).trim(), splitThink(content).think].filter(Boolean).join("\n\n");
    const shown = answer;
    return { shown, think, content, reasoning, stopped, web, attachments, usage };
  }
  throw new Error(lastMsg);
}
function messagesForRequest(voiceOn) {
  if (!voiceOn) return messages;
  const brief = "Answer in one or two plain spoken sentences. No headings, no bullet lists, no markdown. Keep the response short.";
  let added = false;
  const out = [];
  for (const m of messages) {
    if (!added && m && m.role === "system" && typeof m.content === "string") {
      added = true;
      out.push({ role: "system", content: m.content + "\n\n" + brief });
    } else {
      out.push(m);
    }
  }
  if (!added) out.unshift({ role: "system", content: brief });
  return out;
}
// ---- App agent: requests aimed at an open app (ONLYOFFICE slides, Node-RED) go to
// stickllm-appagent (/appagent/act through the gateway) instead of the chat model.
// The composer "App" picker chooses the target; "@office ..." / "@nodered ..." picks
// it for one message; opening a .pptx in Office selects ONLYOFFICE automatically.
const APPAGENT_NAMES = { onlyoffice: "ONLYOFFICE slides", nodered: "Node-RED", slides: "Test slides" };
const APPAGENT_PREFIX = /^@(onlyoffice|office|slides|pptx|nodered|node-red)\b[:,]?\s*/i;
const APPAGENT_ALIAS = { onlyoffice: "onlyoffice", office: "onlyoffice", pptx: "onlyoffice", slides: "onlyoffice", nodered: "nodered", "node-red": "nodered" };
let appAgentApps = [];
let appAgentAuto = false;
let appAgentBusy = false;
function appAgentSession() {
  let id = "";
  try { id = localStorage.getItem("stickllm-appagent-session") || ""; } catch (_) {}
  if (!/^[a-z0-9]{8,32}$/.test(id)) {
    id = "ui" + Math.random().toString(36).slice(2, 12);
    try { localStorage.setItem("stickllm-appagent-session", id); } catch (_) {}
  }
  return id;
}
function appAgentRoute(raw) {
  const text = String(raw || "").trim();
  if (!text) return null;
  const m = text.match(APPAGENT_PREFIX);
  if (m) {
    const app = APPAGENT_ALIAS[m[1].toLowerCase()];
    const rest = text.slice(m[0].length).trim();
    return rest && appAgentApps.includes(app) ? { app, text: rest } : null;
  }
  const pick = $("#appTarget");
  const app = pick && !pick.hidden ? pick.value : "";
  return app ? { app, text } : null;
}
function appAgentReply(app, j) {
  const name = APPAGENT_NAMES[app] || app;
  const out = [`**${name}:** ${String(j.understanding || "").trim() || "(no summary)"}`];
  const res = Array.isArray(j.results) ? j.results : [];
  if (res.length) {
    out.push(res.slice(0, 20).map((r) => {
      const why = r.ok ? "" : " — " + String(r.out || "failed").slice(0, 160);
      return `${r.ok ? "✓" : "✗"} \`${String(r.cmd || "").slice(0, 160)}\`${why}`;
    }).join("\n"));
  } else {
    out.push(j.plan_err ? "No change: " + String(j.plan_err).slice(0, 200) : "Nothing was changed.");
  }
  return out.join("\n\n");
}
function setAppTarget(app, auto) {
  const pick = $("#appTarget");
  if (!pick || pick.hidden) return;
  if (app && !appAgentApps.includes(app)) return;
  pick.value = app || "";
  appAgentAuto = !!(app && auto);
  pick.classList.toggle("on", !!app);
  $("#input").placeholder = app ? `Tell ${APPAGENT_NAMES[app] || app} what to do` : "Message StickLLM";
}
async function loadAppAgentApps() {
  const pick = $("#appTarget");
  if (!pick) return;
  try {
    const r = await fetch("/appagent/apps", { headers: authHeaders(), credentials: "same-origin" });
    const list = r.ok ? await r.json() : [];
    appAgentApps = (Array.isArray(list) ? list : []).map((a) => a && a.name).filter((n) => n && n !== "slides");
  } catch (_) { appAgentApps = []; }
  const cur = pick.value;
  pick.innerHTML = `<option value="">Chat</option>` +
    appAgentApps.map((n) => `<option value="${esc(n)}">${esc(APPAGENT_NAMES[n] || n)}</option>`).join("");
  pick.hidden = !appAgentApps.length;
  setAppTarget(appAgentApps.includes(cur) ? cur : "", appAgentAuto);
}
// 0.5.5: after the app agent deploys or undoes, reload that app's open tab
// (the kiosk's Node-RED editor does not show flows changed over the Admin
// API until it reloads). Only a tab this page opened (appTabs) can be
// reloaded, and it is not focused. The event is for in-page app views.
const APPAGENT_TAB_IDS = { nodered: "node-red" };
function reloadAgentAppTab(app) {
  const id = APPAGENT_TAB_IDS[app] || app;
  try { window.dispatchEvent(new CustomEvent("stickllm-app-changed", { detail: { app, id } })); } catch (e) {}
  const link = appTabLink(id);
  const w = appTabHandle(link ? link.target : "stickllm-" + id);
  if (!w || !link || appTabIsBlank(w)) return false;
  try { w.location.href = new URL(link.href, location.href).href; return true; } catch (e) { return false; }
}
async function sendToApp(app, text) {
  if (appAgentBusy) return;
  if (!(await ensurePaired())) return;
  appAgentBusy = true;
  const inp = $("#input");
  inp.value = "";
  autosize();
  if (!state.current) {
    const chat = { id: Date.now(), title: text.slice(0, 40), msgs: [] };
    state.ephemeral.unshift(chat); state.current = chat;
  }
  const c = state.current;
  c.msgs.push({ r: "user", t: text });
  const pend = { r: "ai", pending: true };
  c.msgs.push(pend);
  renderThread(); renderConvs();
  try {
    const r = await fetch("/appagent/act", {
      method: "POST", credentials: "same-origin",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ app, request: text, session: appAgentSession() }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || j.message || `The app agent answered ${r.status}`);
    pend.t = appAgentReply(app, j);
    if ((j.results || []).some((x) => x.ok)) { pend.appUndo = app; reloadAgentAppTab(app); }
  } catch (e) {
    pend.t = `**${APPAGENT_NAMES[app] || app}:** ${e.message || e}`;
    pend.warn = "Nothing was sent to the chat model.";
  } finally {
    pend.pending = false;
    appAgentBusy = false;
    renderThread();
  }
}
async function appAgentUndo(i) {
  const c = state.current, m = c && c.msgs[i];
  if (!m || !m.appUndo || appAgentBusy) return;
  const app = m.appUndo;
  if (!(await ensurePaired())) return;
  appAgentBusy = true;
  let line;
  try {
    const r = await fetch("/appagent/undo", {
      method: "POST", credentials: "same-origin",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ app, session: appAgentSession() }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `The app agent answered ${r.status}`);
    line = `**${APPAGENT_NAMES[app] || app}:** ${j.ok ? "Undone." : "Nothing to undo."} ${String(j.message || "").slice(0, 200)}`;
    if (j.ok) { m.appUndo = ""; reloadAgentAppTab(app); }
  } catch (e) {
    line = `**${APPAGENT_NAMES[app] || app}:** undo failed: ${e.message || e}`;
  } finally {
    appAgentBusy = false;
  }
  c.msgs.push({ r: "ai", t: line.trim() });
  renderThread();
}
if ($("#appTarget")) {
  $("#appTarget").onchange = (e) => setAppTarget(e.target.value, false);
  loadAppAgentApps();
  // Pairing may finish after load: look again (at most every 15 s) while no app is listed.
  let appAgentLooked = Date.now();
  $("#input").addEventListener("focus", () => {
    if (appAgentApps.length || Date.now() - appAgentLooked < 15000) return;
    appAgentLooked = Date.now();
    loadAppAgentApps();
  });
}
$("#thread").addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-appundo]");
  if (!b) return;
  e.preventDefault();
  appAgentUndo(Number(b.dataset.appundo));
});
// /apps/docs/ (same origin, another tab) says when a slides editor opens or closes.
try {
  const ch = new BroadcastChannel("stickllm-appagent");
  ch.onmessage = (e) => {
    const d = e.data || {};
    if (d.app !== "onlyoffice") return;
    const pick = $("#appTarget");
    const go = () => {
      if (d.open && (!pick.value || appAgentAuto)) setAppTarget("onlyoffice", true);
      else if (!d.open && appAgentAuto && pick.value === "onlyoffice") setAppTarget("", false);
    };
    if (pick && pick.hidden && d.open) loadAppAgentApps().then(go); else if (pick) go();
  };
} catch (_) {}

async function send() {
  {
    const route = appAgentRoute($("#input").value);
    if (route && !state.attach.length) return sendToApp(route.app, route.text);
  }
  unlockSpeech();
  const gen = ++sendGen;
  const prev = sendFlight;
  let resolveDone;
  const done = new Promise((resolve) => { resolveDone = resolve; });
  const abort = new AbortController();
  const flight = { gen, abort, done };
  sendFlight = flight;
  sendAbort = abort;
  const job = (async () => {
    try {
      await runSend(gen, abort, prev);
    } finally {
      resolveDone();
      if (sendFlight === flight) sendFlight = null;
    }
  })();
  return job;
}
async function runSend(gen, abort, prev) {
  setSending(true);
  speakHalted = false;
  stopSpeak();
  if (prev && prev.abort) {
    try { prev.abort.abort(); } catch (_) {}
  }
  await requestChatStop();
  if (prev && prev.done) {
    try { await prev.done; } catch (_) {}
  }
  const inpEarly = $("#input");
  const tookMic = !sendFromMic && micHot();
  const typedBesideMic = tookMic && !composerFromMic ? (inpEarly ? inpEarly.value : "") : "";
  if (tookMic && composerFromMic && inpEarly) {
    inpEarly.value = "";
    composerFromMic = false;
  }
  if (tookMic) await finishMic("stop");
  else if (!sendFromMic && finishPromise) await finishPromise;
  if (gen !== sendGen || userStopGen === gen) {
    setSending(false);
    return;
  }
  if (tookMic && !typedBesideMic && !composerFromMic) {
    setSending(false);
    return;
  }
  const holdVoice = voiceMode;
  if (holdVoice) voiceHold = true;
  const inp = $("#input");
  const text = inp.value.trim();
  const imgs = state.attach.filter((a) => a.kind !== "file").slice(0, PHOTO_MAX);
  const docs = state.attach.filter((a) => a.kind === "file");
  if (docs.some((a) => a.status === "converting")) {
    if (holdVoice) { voiceHold = false; resumeVoiceListen(); }
    toast("Still converting a file");
    setSending(false);
    return;
  }
  const readyDocs = docs.filter((a) => a.status === "ready" || a.status === "truncated");
  if (!text && !imgs.length && !readyDocs.length) {
    if (holdVoice) { voiceHold = false; resumeVoiceListen(); }
    setSending(false);
    return;
  }
  inp.value = "";
  autosize();
  let pend = null;
  let pushedUser = false;
  try {
    if (!(await ensurePaired()) || gen !== sendGen || userStopGen === gen) {
      if (gen === sendGen) {
        inp.value = text;
        autosize();
      }
      return;
    }
    if (!state.current) {
      const chat = { id: Date.now(), title: (text || "Image").slice(0, 40), msgs: [] };
      state.ephemeral.unshift(chat); state.current = chat;
    }
    const c = state.current;
    const docBlock = readyDocs.map((a) => a.text).filter(Boolean).join("\n\n");
    const shown = text || (imgs.length ? "What is in this image?" : readyDocs.map((a) => a.name).join(", "));
    const pageImgs = [];
    if (modelVision) {
      for (const doc of readyDocs) {
        for (const im of doc.images || []) {
          if (pageImgs.length >= PAGE_IMAGE_MAX) break;
          if (im.dataUrl) pageImgs.push(im.dataUrl);
        }
      }
    }
    const photoUrls = imgs.map((x) => x.dataUrl);
    c.msgs.push({ r: "user", t: shown, imgs: [...photoUrls, ...pageImgs] });
    pend = { r: "ai", pending: true }; c.msgs.push(pend);
    const apiText = [docBlock, text].filter(Boolean).join("\n\n") || "What is in this image?";
    const allImgs = (modelVision ? [...photoUrls, ...pageImgs] : [])
      .filter((url) => typeof url === "string" && url.startsWith("data:image/") && url.length <= 90000)
      .slice(0, PHOTO_MAX + PAGE_IMAGE_MAX);
    const content = allImgs.length
      ? [
          { type: "text", text: apiText },
          ...allImgs.map((url) => ({ type: "image_url", image_url: { url } })),
        ]
      : apiText;
    messages.push({ role: "user", content });
    pushedUser = true;
    state.attach = [];
    renderAttach();
    renderThread(); renderConvs();
    const t0 = performance.now();
    const base = {
      model: "stickllm",
      messages: messagesForRequest(holdVoice),
      web: state.web ? "on" : "off",
    };
    {
      const t = tuneNow();
      base.temperature = t.temp;
      base.top_p = t.top_p;
      base.top_k = Math.round(t.top_k);
      base.repeat_penalty = t.repeat_penalty;
      base.max_tokens = holdVoice ? VOICE_CHAT_TOKENS : Math.max(64, Math.min(4096, Math.round(t.max_tokens) || CHAT_TOKENS));
    }
    if (holdVoice) base.chat_template_kwargs = { enable_thinking: false };
    const onShown = (shown) => {
      if (gen !== sendGen || userStopGen === gen) return;
      pend.t = shown;
      paintStream(shown);
      // The bubble is the answer. Speak each finished sentence of this reply.
      if (holdVoice) feedSpeech(shown);
    };
    const onThink = () => {
      if (pend.thinking || gen !== sendGen || userStopGen === gen) return;
      pend.thinking = true;
      const ty = $$("#thread .msg.ai .body .typing").pop();
      if (ty && !ty.nextElementSibling) ty.insertAdjacentHTML("afterend", '<span class="thinkNote">Thinking…</span>');
    };
    let acc = await takeChatStream(gen, abort, base, onShown, { onThink });
    if (acc.stopped || userStopGen === gen) {
      const err = new Error("bail");
      err.name = "VoiceBail";
      throw err;
    }
    let reply = acc.shown;
    if (!reply && gen === sendGen && userStopGen !== gen) {
      resetSpeechFeed();
      acc = await takeChatStream(gen, abort, {
        ...base,
        max_tokens: holdVoice ? VOICE_CHAT_TOKENS : CHAT_TOKENS_RETRY,
        chat_template_kwargs: { enable_thinking: false },
      }, onShown, { onThink });
      if (acc.stopped || userStopGen === gen) {
        const err = new Error("bail");
        err.name = "VoiceBail";
        throw err;
      }
      reply = acc.shown;
    }
    if (gen !== sendGen) {
      const err = new Error("bail");
      err.name = "Superseded";
      throw err;
    }
    if (acc.attachments?.truncated && acc.attachments.note) {
      const userMsg = c.msgs[c.msgs.length - 2];
      if (userMsg) userMsg.warn = acc.attachments.note;
    }
    const wallMs = performance.now() - t0;
    const webInfo = acc.web;
    let src = [];
    if (webInfo?.used && webInfo.results?.length) {
      src = webInfo.results.slice(0, 3).map((x) => x.url).filter(Boolean);
    }
    const perfData = acc.usage ? { usage: acc.usage } : {};
    if (!reply) {
      pend.pending = false;
      pend.r = "system";
      pend.t = BUDGET_NOTE;
      if (src.length) pend.src = src;
      updatePerfStrip(perfFromChatResponse(perfData, wallMs, ""));
      return;
    }
    if (holdVoice) {
      const answer = dropEmptyPlaceholder(stripThink(acc.content)).trim();
      if (answer) {
        feedSpeech(answer);
        flushSpeech();
      }
    }
    messages.push({ role: "assistant", content: reply });
    pend.pending = false; pend.thinking = false; pend.t = reply; if (acc.think) pend.think = acc.think; if (src.length) pend.src = src;
    updatePerfStrip(perfFromChatResponse(perfData, wallMs, reply));
    if (sessionMode === "vault" && state.vaultOpen) saveCurrentChat(true).catch(() => {});
  } catch (e) {
    const superseded = e && (e.name === "Superseded" || (gen !== sendGen));
    const stopped = e && (e.name === "VoiceBail" || e.name === "AbortError" || userStopGen === gen);
    if (e && e.name === "PairRequired") {
      pairLost("This browser is no longer paired with the stick.");
      if (pend) {
        pend.pending = false;
        pend.r = "system";
        pend.t = "Pair required — enter the code from the stick screen.";
      }
      if (pushedUser) dropApiUserTurn();
    } else if (superseded || stopped) {
      if (pend && pend.pending) {
        pend.pending = false;
        pend.r = "system";
        pend.t = "Stopped.";
      }
      if (pushedUser) dropApiUserTurn();
    } else if (pend) {
      pend.pending = false;
      pend.r = "system";
      pend.t = "Error: " + (e && e.message ? e.message : "The model did not answer.");
    } else if (gen === sendGen) {
      inp.value = text;
      autosize();
    }
  } finally {
    if (gen === sendGen) {
      if (sendAbort === abort) sendAbort = null;
      setSending(false);
      renderThread({ keepSpeech: true }); renderConvs();
      const box = $("#input");
      if (box) box.focus();
    }
  }
  if (gen !== sendGen) return;
  if (voiceMode && !speakQ.length && !speakPumping && !speakAudio) {
    voiceHold = false;
    resumeVoiceListen();
  }
}
$("#composer").onsubmit = (e) => { e.preventDefault(); send(); };
const autosize = () => { const i = $("#input"); i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 200) + "px"; };
$("#input").addEventListener("input", () => { composerFromMic = false; autosize(); });
$("#input").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.repeat) return;
  e.preventDefault();
  send();
});
if ($("#stopBtn")) $("#stopBtn").onclick = () => stopReply();
$("#webToggle").onclick = () => {
  state.web = !state.web;
  $("#webToggle").setAttribute("aria-pressed", state.web);
  $("#webDefault").checked = state.web;
};
$("#webDefault").onchange = (e) => {
  state.web = e.target.checked;
  $("#webToggle").setAttribute("aria-pressed", state.web);
};

$("#statusChip").onclick = (e) => {
  e.stopPropagation();
  const p = $("#statusPop"); p.hidden = !p.hidden;
  $("#statusChip").setAttribute("aria-expanded", !p.hidden);
};
document.addEventListener("click", (e) => {
  if (!$("#statusPop").contains(e.target) && e.target !== $("#statusChip"))
    $("#statusPop").hidden = true;
});

let lastFocus;
function openSettings(sec = "general") {
  lastFocus = document.activeElement; $("#settings").hidden = false; $("#statusPop").hidden = true;
  if (mobile()) toggleNav(false);
  showSec(sec, !mobile() || sec !== "__nav");
  if (sec === "models" || sec === "downloads") refreshModels().catch((e) => toast(e.message));
  if (sec === "storage") refreshStorage().catch((e) => toast(e.message));
  if (sec === "devices" || sec === "network" || sec === "system" || sec === "about")
    refreshStatus().catch(() => {});
  if (sec === "chats") renderSaved();
}
function showSec(sec, open = true) {
  $$(".sec").forEach((s) => (s.hidden = s.id !== "sec-" + sec));
  $$(".setNav [data-sec]").forEach((b) => {
    b.classList.toggle("on", b.dataset.sec === sec);
    b.setAttribute("aria-current", b.dataset.sec === sec ? "page" : "false");
  });
  $("#secTitle").innerHTML = $("#sec-" + sec).dataset.title;
  $(".modal:not(.small):not(.fp)")?.classList.toggle("secOpen", open);
  $(".setScroll").scrollTop = 0;
}
function closeSettings() { $("#settings").hidden = true; lastFocus?.focus?.(); }
$$("[data-open]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openSettings(b.dataset.open); }));
$$(".setNav [data-sec]").forEach((b) => (b.onclick = () => {
  showSec(b.dataset.sec);
  if (b.dataset.sec === "models" || b.dataset.sec === "downloads") refreshModels().catch((e) => toast(e.message));
  if (b.dataset.sec === "storage") refreshStorage().catch(() => {});
}));
$$("[data-sec-go]").forEach((b) => (b.onclick = () => {
  showSec(b.dataset.secGo);
  if (b.dataset.secGo === "models") refreshModels().catch((e) => toast(e.message));
}));
$("#setClose").onclick = closeSettings;
$("#setBack").onclick = () => $(".modal:not(.small):not(.fp)")?.classList.remove("secOpen");
$("#settings").onclick = (e) => { if (e.target.id === "settings") closeSettings(); };

let cfCb;
function confirmBox({ title, text, word, ok = "Delete", extra, cb }) {
  $("#cfTitle").textContent = title; $("#cfText").textContent = text; $("#cfWord").textContent = word;
  $("#cfOk").textContent = ok; $("#cfOk").disabled = true; $("#cfInput").value = "";
  $("#cfExtra").hidden = !extra; $("#cfExtra").textContent = extra || "";
  cfCb = cb; $("#confirm").hidden = false; setTimeout(() => $("#cfInput").focus(), 20);
}
$("#cfInput").oninput = () => ($("#cfOk").disabled = $("#cfInput").value.trim() !== $("#cfWord").textContent);
$("#cfInput").onkeydown = (e) => { if (e.key === "Enter" && !$("#cfOk").disabled) $("#cfOk").click(); };
$("#cfCancel").onclick = () => ($("#confirm").hidden = true);
$("#cfOk").onclick = () => { $("#confirm").hidden = true; cfCb?.(); };

function fmtBytes(n) {
  if (!n || n < 0) return "—";
  const gb = n / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  return `${(n / 1024 ** 2).toFixed(0)} MB`;
}

function isAbliterated(m) {
  if (m.abliterated || m.abl) return true;
  const blob = `${m.name || ""} ${m.repo || ""} ${m.file || ""} ${m.id || ""}`.toLowerCase();
  return /abliterat|uncensor|jailbreak/.test(blob);
}
function modelTrust(m) {
  const t = String(m.trust || m.trust_level || "").toLowerCase();
  if (TRUST[t]) return t;
  if (m.hash_ok === false || m.blocked) return "blocked";
  if (m.source === "host_ssd" || m.source === "local") return "unverified";
  // Verified = sha256 on StickLLM's list (catalog.toml). A Hugging Face LFS
  // hash alone (lfs_sha256) is integrity, not review.
  if (m.verified === true || (m.sha256 && m.pinned !== false)) return "verified";
  return "unverified";
}
function modelGb(m) {
  const gbRaw = m.approx_size_gb ?? m.size_gb ?? (m.bytes != null ? m.bytes / 1e9 : null);
  return gbRaw != null && gbRaw !== "" ? Number(gbRaw) : 0;
}
function modelQuant(m) {
  return String(m.quant || m.q || "Q4_K_M");
}
function fitGb(n) {
  const v = Number(n) || 0;
  return (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + " GB";
}
function hardwareDetectedLine() {
  const n = Math.max(0, Number(hwInfo.gpuCount) || 0);
  const name = hwInfo.gpu ? hwInfo.gpu : "GPU";
  const ram = `${Number(hwInfo.ram).toFixed(1)} GB`;
  if (n > 1) {
    const each = Number(hwInfo.vramEach) || 0;
    const split = each ? ` (${n}× ${fitGb(each)})` : "";
    return `Detected: ${n}× ${name} · ${fitGb(hwInfo.vram)} VRAM${split} · RAM ${ram}`;
  }
  return `Detected: ${hwInfo.gpu ? hwInfo.gpu + " " : ""}${fitGb(hwInfo.vram)} VRAM · RAM ${ram}`;
}
function hardwarePool() {
  if (state.mf.target === "custom") {
    const vram = +$("#cVram")?.value || 0;
    return { vram, vramEach: vram, gpuCount: 1, ram: +$("#cRam")?.value || 0, gpu: "" };
  }
  return hwInfo;
}
function fitOf(m) {
  const hw = hardwarePool();
  const gb = modelGb(m) || Number(m.min_vram_gb || 0) || 4;
  const kvMul = { f16: 1, q8: 0.53, q4: 0.28 }[state.kv] || 1;
  const kv = Math.max(0.5, (gb / 8) * (state.mf.ctx / 8192) * kvMul);
  const need = gb + kv + 1;
  const pool = Number(hw.vram) || 0;
  const each = Number(hw.vramEach) || pool;
  const cards = Math.max(1, Number(hw.gpuCount) || 1);
  const size = fitGb(need);
  if (cards > 1 && each > 0 && need <= each) return { k: "gpu", need, kv, label: `Fits on 1 GPU · ${size}`, cls: "fit-ok" };
  if (need <= pool) return { k: "gpu", need, kv, label: cards > 1 ? `Fits on ${cards} GPUs · ${size}` : `Fits in VRAM · ${size}`, cls: "fit-ok" };
  if (need <= pool + (Number(hw.ram) || 0) - 8) return { k: "offload", need, kv, label: `Partial · ${fitGb(pool)} in VRAM`, cls: "fit-warn" };
  return { k: "no", need, kv, label: `Won't fit · needs ${size}`, cls: "fit-no" };
}
function visionTag(m, id) {
  if (!modelSees(m)) return "";
  const ready = !!(m.mmproj || m.mmproj_ready);
  const qst = queueState("mmproj:" + id);
  if (ready) return `<span class="pill acc" title="This model's mmproj is on disk">vision</span>`;
  if (qst === "active" || qst === "pending") return `<span class="pill warn" title="Downloading this model's mmproj">vision…</span>`;
  return `<button type="button" class="pill visionOff" data-mmproj="${esc(id)}" title="Download this model's mmproj from Hugging Face">vision</button>`;
}
function modelSees(m) {
  if (m && m.vision) return true;
  const s = `${m?.name || ""} ${m?.id || ""} ${m?.architecture || ""} ${m?.file || ""}`.toLowerCase();
  return /(?:^|[^a-z0-9])(?:vl|vision)(?:[^a-z0-9]|$)|qwen\d*(?:\.\d+)?-?vl|llava|moondream|minicpm-?v|internvl|pixtral|smolvlm|glm-?4v|kimi-?vl|idefics/.test(s);
}
function modelVisible(m) {
  const f = state.mf;
  const trust = modelTrust(m);
  if (state.mtab === "local" ? !m.installed : false) return false;
  if (state.policy.verifiedOnly && trust !== "verified") return false;
  if (state.policy.hideUnc && isAbliterated(m)) return false;
  if (!f.trust.has(trust)) return false;
  if (f.abl === "only" && !isAbliterated(m)) return false;
  if (f.abl === "exclude" && isAbliterated(m)) return false;
  if (f.quant !== "any" && modelQuant(m).toUpperCase() !== f.quant.toUpperCase()) return false;
  // GGUF only — llama.cpp does not run safetensors
  if (String(m.format || "GGUF").toLowerCase() === "safetensors") return false;
  if (f.vis === "only" && !modelSees(m)) return false;
  if (f.lic === "commercial" && m.license_noncommercial) return false;
  if (f.lic === "noncommercial" && !m.license_noncommercial) return false;
  if (f.q && !m.hf && !(String(m.name || "") + " " + String(m.id || "")).toLowerCase().includes(f.q.toLowerCase())) return false;
  if (f.fits && fitOf(m).k === "no") return false;
  return true;
}
function updateVramBar(m) {
  const gb = modelGb(m) || 0;
  const fit = fitOf(m || {});
  const total = Math.max(1, hwInfo.vram || 24);
  const wPct = Math.min(100, (gb / total) * 100);
  const kvPct = Math.min(100 - wPct, (fit.kv / total) * 100);
  const freePct = Math.max(0, 100 - wPct - kvPct);
  if ($("#vW")) $("#vW").style.width = wPct + "%";
  if ($("#vKV")) $("#vKV").style.width = kvPct + "%";
  if ($("#vFree")) $("#vFree").style.width = freePct + "%";
  if ($("#lW")) $("#lW").textContent = gb ? gb.toFixed(1) + " GB" : "—";
  if ($("#lKV")) $("#lKV").textContent = fit.kv.toFixed(1) + " GB";
  if ($("#lFree")) $("#lFree").textContent = Math.max(0, total - gb - fit.kv).toFixed(1) + " GB";
  if ($("#vramTotal")) $("#vramTotal").textContent = `of ${total} GB`;
  if ($("#vramWarn")) $("#vramWarn").hidden = fit.k !== "no";
}
function browseSource() {
  const q = (state.mf.q || "").trim();
  if (state.mtab === "browse" && q.length >= 2) return hfHits;
  return lastCatalog;
}
function showLoadTune() {
  if (state.mtab === "local") return true;
  const m = findModel(selectedModelId);
  return !!(m && m.installed);
}
function renderModelsList() {
  const list = $("#modelList");
  if (!list) return;
  $$(".tabs [data-tab]").forEach((b) => {
    const on = b.dataset.tab === state.mtab;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on);
  });
  const localN = lastCatalog.filter((m) => m.installed).length;
  if ($("#localCount")) $("#localCount").textContent = String(localN);
  if ($("#localTune")) $("#localTune").hidden = !showLoadTune();
  if ($("#hfTokenBox")) $("#hfTokenBox").hidden = state.mtab !== "browse";
  if ($("#mfTarget")) $("#mfTarget").value = state.mf.target;
  if ($("#customHw")) $("#customHw").hidden = state.mf.target !== "custom";
  if ($("#hwLine")) {
    $("#hwLine").textContent = state.mf.target === "custom"
      ? "Enter VRAM and RAM"
      : hardwareDetectedLine();
  }
  if ($("#hwWarn")) {
    $("#hwWarn").textContent = hwWarnings.join(" ");
    $("#hwWarn").hidden = !hwWarnings.length;
  }
  if ($("#mfFits")) $("#mfFits").checked = state.mf.fits;
  if ($("#mfCtx")) $("#mfCtx").value = String(state.mf.ctx);
  if ($("#mfQuant")) $("#mfQuant").value = state.mf.quant;
  if ($("#mfSort")) $("#mfSort").value = state.mf.sort;
  $$("#mfTrust input").forEach((i) => { i.checked = state.mf.trust.has(i.dataset.t); });
  $$("#mfAbl button").forEach((b) => b.classList.toggle("on", b.dataset.v === state.mf.abl));
  $$("#mfLic button").forEach((b) => b.classList.toggle("on", b.dataset.v === state.mf.lic));
  $$("#mfVis button").forEach((b) => b.classList.toggle("on", b.dataset.v === state.mf.vis));
  const rules = [
    state.policy.verifiedOnly && "only Verified models",
    state.policy.hideUnc && "uncensored models hidden",
  ].filter(Boolean);
  if ($("#policyBanner")) {
    $("#policyBanner").hidden = !rules.length;
    if (rules.length) {
      $("#policyBanner").innerHTML = `<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></svg><span><b>Machine policy:</b> ${rules.join(" · ")}.</span>`;
    }
  }
  const source = browseSource();
  const searching = state.mtab === "browse" && (state.mf.q || "").trim().length >= 2;
  if ($("#browseNote")) {
    $("#browseNote").textContent = searching
      ? (hfBusy ? "Searching Hugging Face…" : "Hugging Face · GGUF only")
      : "Pinned catalog · type to search Hugging Face";
  }
  if (searching && hfBusy && !hfHits.length) {
    list.innerHTML = '<div class="emptyCards">Searching Hugging Face…</div>';
    syncModelActions();
    return;
  }
  if (searching && hfErr && !hfHits.length) {
    list.innerHTML = `<div class="emptyCards">${esc(hfErr)}</div>`;
    syncModelActions();
    return;
  }
  if (!source.length && !searching) {
    list.innerHTML = '<div class="emptyCards">No catalog entries. Pair this browser, then Refresh.</div>';
    syncModelActions();
    return;
  }
  let rows = source.filter(modelVisible);
  const order = { gpu: 0, offload: 1, no: 2 };
  rows.sort((a, b) => {
    if (state.mf.sort === "running") {
      const rank = (m) => (m.running ? 0 : m.active ? 1 : 2);
      return (rank(a) - rank(b)) || String(a.name || a.id).localeCompare(String(b.name || b.id));
    }
    if (state.mf.sort === "size") return modelGb(b) - modelGb(a);
    if (state.mf.sort === "name") return String(a.name || a.id).localeCompare(String(b.name || b.id));
    return (order[fitOf(a).k] - order[fitOf(b).k]) || (Number(!!b.recommended) - Number(!!a.recommended));
  });
  if ($("#modelCount")) {
    $("#modelCount").textContent = `${rows.length} model${rows.length === 1 ? "" : "s"}${searching ? " from Hugging Face" : state.mtab === "browse" ? " in catalog" : " on this stick"} · fit at ${state.mf.ctx / 1024}k context`;
  }
  list.innerHTML = rows.map((m) => {
    const id = m.id;
    const name = m.name || id;
    const q = modelQuant(m);
    const gb = modelGb(m);
    const gbTxt = gb ? (gb >= 10 ? gb.toFixed(1) : gb.toFixed(2)) + " GB" : "?";
    const have = !!m.installed;
    const run = !!m.running;
    // Optimistic id → Loading on click; only that card (never leave others stuck).
    const loading = !run && (loadingModelId === id || (!loadingModelId && !!m.active));
    const rec = !!m.recommended;
    const sel = id === selectedModelId;
    const trust = modelTrust(m);
    const t = TRUST[trust];
    const fit = fitOf(m);
    const where = String(m.path || m.location || "").includes("vault") || sessionMode === "vault" ? "vault/SSD" : "stick";
    let actions = "";
    const delBtn = m.deletable
      ? `<button class="btn sm danger ghost" data-delf="${esc(id)}" type="button" title="Permanently delete model files">Delete</button>`
      : "";
    if (trust === "blocked") {
      actions = delBtn;
    } else if (have) {
      actions = `<span class="pill ok">installed</span><button class="btn sm primary" data-load="${esc(id)}" type="button" ${fit.k === "no" && m.runnable === false ? "disabled" : ""}>${run ? "Running" : loading ? "Loading…" : "Load"}</button>${delBtn}`;
    } else if (queueState(id) === "active" || dlActiveId === id) {
      actions = `<span class="pill warn">downloading</span>`;
    } else if (queueState(id) === "pending") {
      actions = `<span class="pill">queued</span>`;
    } else if (queueState(id) === "paused") {
      actions = `<span class="pill">paused</span>`;
    } else if (queueState(id) === "failed") {
      actions = `<button class="btn sm" data-dl="${esc(id)}" type="button">Retry</button>`;
    } else {
      actions = `<button class="btn sm ${fit.k === "no" ? "" : "primary"}" data-dl="${esc(id)}" type="button">Download</button>`;
    }
    return `<article class="mcard ${trust === "blocked" ? "blocked" : ""} ${sel ? "sel" : ""}" data-id="${esc(id)}" tabindex="0">
      <div class="mcTop">
        <div class="mcName"><b>${esc(name)}</b><small>${esc(q)} · ${have ? gbTxt + " on disk" : "~" + gbTxt}${have ? " · on " + where : ""}${rec ? " · recommended" : ""}</small></div>
        ${run ? '<span class="pill ok">running</span>' : ""}${loading ? '<span class="pill warn">loading</span>' : ""}${rec ? '<span class="pill acc">recommended</span>' : ""}
      </div>
      <div class="tags"><span class="trust ${t.c}" title="${t.d}">${t.l}</span>${visionTag(m, id)}${isAbliterated(m) ? '<span class="pill abl">⚠ uncensored</span>' : ""}<span class="pill cap">GGUF</span></div>
      <div class="mcFoot">
        <span class="fit ${fit.cls}" title="Needs ~${fit.need.toFixed(1)} GB">${fit.label}</span>
        <span class="grow"></span>${actions}
      </div>
    </article>`;
  }).join("") || `<div class="emptyCards">${state.mf.vis === "only" ? "No vision models match. Search for a VL model, such as Qwen2.5-VL." : 'No models match these filters. <button class="link" id="mfReset2" type="button">Reset filters</button>'}</div>`;
  $("#mfReset2") && ($("#mfReset2").onclick = resetModelFilters);
  $$("#modelList .mcard").forEach((c) => {
    const pick = (e) => {
      if (e.target.closest("button")) return;
      selectedModelId = c.dataset.id;
      renderModelsList();
    };
    c.onclick = pick;
    c.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(e); } };
  });
  $$("#modelList [data-dl]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); selectedModelId = b.dataset.dl; $("#dlModel").click(); }));
  $$("#modelList [data-mmproj]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); downloadMmproj(b.dataset.mmproj); }));
  $$("#modelList [data-load]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    const id = b.dataset.load;
    const m = findModel(id);
    // Paint Loading on this card immediately (before activate network call).
    beginModelLoadUi(id, m?.name || id);
    // Yield a frame so the badge/status line paint before the long activate await.
    paintSoon().then(() => $("#activate").click());
  }));
  $$("#modelList [data-delf]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    selectedModelId = b.dataset.delf;
    askDeleteModel(findModel(b.dataset.delf));
  }));
  syncModelActions();
}
function syncModelActions() {
  const m = findModel(selectedModelId);
  if (!m) {
    if ($("#selHint")) $("#selHint").textContent = "Select a model";
    updateVramBar({});
    return;
  }
  if ($("#selHint")) {
    const speed = m.offload_caption ? ` — ${m.offload_caption}` : "";
    $("#selHint").textContent = `Selected: ${m.name || m.id}${speed}`;
  }
  if ($("#dlModel")) $("#dlModel").hidden = !!m.installed;
  if ($("#activate")) {
    $("#activate").hidden = !m.installed || (m.runnable === false && !m.running && !m.active);
    const failed = lastLlama && (lastLlama.stopped || Number(lastLlama.n_restarts || 0) >= 2);
    $("#activate").textContent = m.running ? "Reload with these settings" : (failed ? "Load model" : (m.active ? "Loading…" : "Load model"));
  }
  if ($("#delModel")) $("#delModel").hidden = !m.deletable;
  const max = Number(m.ctx_max || m.ctxMax || 32768);
  if ($("#ctx")) {
    $("#ctx").max = max;
    if (+$("#ctx").value > max) $("#ctx").value = max;
    if ($("#ctxVal")) paintCtxVal();
    try { syncPresetHighlight(); } catch (_) {}
  }
  updateVramBar(m);
}
function findModel(id) {
  return hfHits.find((x) => x.id === id) || lastCatalog.find((x) => x.id === id);
}
function resetModelFilters() {
  state.mf = { ...state.mf, fits: false, trust: ALL_TRUST(), abl: "include", quant: "any", lic: "any", vis: "any", q: "", sort: "fit" };
  if ($("#mfSearch")) $("#mfSearch").value = "";
  hfHits = [];
  hfErr = "";
  renderModelsList();
}
function friendlyModelLabel(raw, pathHint) {
  let s = String(raw || "").trim();
  if (!s || /^none\b/i.test(s) || /^loading/i.test(s)) {
    s = String(pathHint || "").split(/[/\\]/).pop() || "";
  }
  s = s.replace(/\.gguf$/i, "");
  if (!s) return "";
  // Keep quant tokens readable; turn other separators into spaces for the chip/popover.
  return s.replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
}
// Single flight: a slow control "status" must never pile up requests
// (each one is a thread in the root control daemon).
let modelsFlight = null;
function refreshModels() {
  if (modelsFlight) return modelsFlight;
  modelsFlight = refreshModelsNow().finally(() => { modelsFlight = null; });
  return modelsFlight;
}
async function refreshModelsNow() {
  if (!(await ensurePaired())) return;
  const st = await control("status");
  if (st.llama_service) lastLlama = st.llama_service;
  if (st.offload && st.offload.caption && lastLlama && !lastLlama.caption) lastLlama.caption = st.offload.caption;
  lastCatalog = st.catalog || [];
  const probe = st.probe || {};
  const gpuCount = Number(st.gpu_count || (Array.isArray(st.gpus) ? st.gpus.length : 0) || hwInfo.gpuCount) || 1;
  const vram = Number(st.vram_gb || probe.vram_gb || hwInfo.vram) || 24;
  hwInfo = {
    vram,
    vramEach: Number(st.vram_each_gb) || (gpuCount > 1 ? vram / gpuCount : vram),
    gpuCount,
    ram: Number(st.ram_gb || hwInfo.ram) || 64,
    gpu: String(st.gpu || probe.gpu || hwInfo.gpu || ""),
    name: "This machine",
  };
  hwWarnings = Array.isArray(st.hw_warnings) ? st.hw_warnings.filter((w) => typeof w === "string" && w) : [];
  if (hwWarnings.length && !hwWarnToasted) {
    hwWarnToasted = true;
    toast(hwWarnings[0]);
  }
  if ($("#recGpuLabel")) {
    $("#recGpuLabel").textContent = gpuCount > 1 ? `Recommended for these ${gpuCount} GPUs` : "Recommended for this GPU";
  }
  const run = lastCatalog.find((m) => m.running || m.active) || lastCatalog.find((m) => m.installed);
  // Do not clear a click just because some other model is still healthy.
  if (!selectedModelId && run && !loadingModelId) selectedModelId = run.id;
  if (!selectedModelId && lastCatalog[0]) selectedModelId = lastCatalog[0].id;
  let name = st.loaded?.name || run?.name || "none";
  if (loadingModelId) name = requestedLoadName();
  else if (loadMismatchText) name = "Load failed";
  if ($("#runName")) $("#runName").textContent = name;
  if ($("#recName")) $("#recName").textContent = String(probe.recommend_id || probe.recommend || "—");
  const pill = $("#runPill");
  if (pill) {
    const activeLoading = !!loadingModelId || (!loadMismatchText && lastCatalog.some((m) => m.active && !m.running));
    if (loadingModelId) {
      pill.textContent = "loading"; pill.className = "pill warn";
    } else if (loadMismatchText) {
      pill.textContent = "failed"; pill.className = "pill";
    } else if (st.llama_ok || st.llama?.status === "ok" || run?.running) {
      pill.textContent = "running"; pill.className = "pill ok";
    } else if (activeLoading) {
      pill.textContent = "loading"; pill.className = "pill warn";
    } else {
      pill.textContent = "not loaded"; pill.className = "pill";
    }
  }
  if ($("#modelDir")) {
    $("#modelDir").textContent = st.models_dir_preferred || st.download_dir || (st.models_dirs && st.models_dirs[0]) || "…";
  }
  const tok = $("#hfToken");
  if (tok && !hfDirty && document.activeElement !== tok && typeof st.hf_token === "string") {
    tok.value = st.hf_token;
  }
  hfHint(st);
  applyDownloadView(st);
  renderModelsList();
  if (downloadStillGoing(st) && !dlPollTimer) startDlPoll();
}
let dlQueue = [];
let dlActiveId = "";
function queueState(id) {
  const hit = dlQueue.find((q) => q.id === id);
  return hit ? hit.state : "";
}
function applyDownloadView(st) {
  if (Array.isArray(st?.download_queue)) dlQueue = st.download_queue;
  const d = st?.download || {};
  const live = ["downloading", "verifying", "starting"].includes(d.state);
  dlActiveId = live ? (d.id || "") : "";
  renderDownload(d);
  renderQueuePanel();
}
function queueStatusLine(q) {
  const labels = { active: "Downloading", pending: "Queued", paused: "Paused", failed: "Failed" };
  const label = labels[q.state] || q.state || "Queued";
  const pct = q.percent == null ? "" : ` · ${Math.round(Number(q.percent))}%`;
  const size = q.bytes ? ` · ${fmtBytes(q.bytes_done)} / ${fmtBytes(q.bytes)}` : "";
  const err = q.error ? ` — ${q.error}` : "";
  return `${label}${pct}${size}${err}`;
}
function renderQueuePanel() {
  const box = $("#queueList");
  if (!box) return;
  if (!dlQueue.length) {
    box.innerHTML = '<div class="row"><div><b>Queue empty</b><small>Downloads you start from Models show up here.</small></div></div>';
    return;
  }
  box.innerHTML = dlQueue.map((q) => {
    const id = esc(q.id);
    const start = q.state === "active" ? "" : `<button class="btn sm primary" data-qact="start" data-qid="${id}" type="button">Start</button>`;
    const stop = q.state === "active" || q.state === "pending" ? `<button class="btn sm" data-qact="stop" data-qid="${id}" type="button">Stop</button>` : "";
    const del = `<button class="btn sm danger ghost" data-qact="remove" data-qid="${id}" type="button">Delete</button>`;
    return `<div class="row"><div><b>${esc(q.name || q.file || q.id)}</b><small>${esc(queueStatusLine(q))}</small></div><div class="qActions">${stop}${start}${del}</div></div>`;
  }).join("");
  $$("#queueList [data-qact]").forEach((b) => {
    b.onclick = () => onQueueAction(b.dataset.qact, b.dataset.qid);
  });
}
async function sendQueue(action, id) {
  try {
    const res = await control(action, { id });
    applyDownloadView(res);
    renderModelsList();
    if (!dlPollTimer) startDlPoll();
    toast(res.note || "Updated");
  } catch (e) { toast(e.message); }
}
function onQueueAction(act, id) {
  const q = dlQueue.find((item) => item.id === id);
  const name = q?.name || "this model";
  if (act === "remove") {
    confirmBox({
      title: "Remove from the download queue?",
      text: `${name} stops if it is downloading. The partial file stays on disk.`,
      word: "REMOVE",
      ok: "Remove",
      cb: () => sendQueue("queue_remove", id),
    });
    return;
  }
  sendQueue(act === "stop" ? "queue_stop" : "queue_start", id);
}
function renderDownload(d) {
  const box = $("#dlBox");
  const state_ = d?.state || "idle";
  const waiting = dlQueue.filter((q) => q.state === "pending" || q.state === "failed" || q.state === "paused");
  const active = ["downloading", "verifying", "starting", "failed", "done"].includes(state_);
  if (!active && !waiting.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const label = state_ === "done" ? "Downloaded " : state_ === "failed" ? "Failed " : "Downloading ";
  $("#dlName").textContent = active ? label + (d.name || d.id || "model") : "Download queue";
  const pct = d.percent == null ? (state_ === "done" ? 100 : active ? 2 : 0) : Number(d.percent);
  $("#dlFill").style.width = Math.max(active ? 2 : 0, Math.min(100, pct)) + "%";
  $("#dlPct").textContent = active ? Math.round(pct) + "%" : "";
  $("#dlMeta").textContent = active ? (d.note || `${fmtBytes(d.bytes_done)} / ${fmtBytes(d.bytes_total)}`) : "";
  const qEl = $("#dlQueue");
  if (qEl) {
    qEl.innerHTML = waiting.map((q) => {
      const tag = q.state === "failed" ? "failed" : q.state === "paused" ? "paused" : "up next";
      const size = q.bytes ? ` · ${fmtBytes(q.bytes)}` : "";
      const err = q.error ? ` — ${q.error}` : "";
      return `<div class="${q.state === "failed" ? "bad" : ""}">${tag}: ${esc(q.name || q.file || q.id)}${size}${esc(err)}</div>`;
    }).join("");
  }
}
function downloadStillGoing(st) {
  const s = st?.download?.state;
  const queued = (st?.download_queue || dlQueue).some((q) => q.state === "pending" || q.state === "active");
  return queued || ["downloading", "verifying", "starting"].includes(s);
}
function startDlPoll() {
  stopDlPoll();
  dlPollTimer = setInterval(async () => {
    try {
      const st = await control("status");
      applyDownloadView(st);
      if (!downloadStillGoing(st)) {
        stopDlPoll();
        lastCatalog = st.catalog || lastCatalog;
        renderModelsList();
      } else if (st.catalog) {
        lastCatalog = st.catalog;
        renderModelsList();
      }
    } catch (_) {}
  }, 1500);
}
function stopDlPoll() { if (dlPollTimer) { clearInterval(dlPollTimer); dlPollTimer = null; } }

// Models > Preset / Advanced. A preset is ctx + KV type + temperature; the
// highlight follows the knobs, so moving one away from a preset shows "Custom".
const TUNE_PRESETS = {
  fast: { ctx: 4096, kv: "q8", temp: 0.7 },
  balanced: { ctx: 8192, kv: "f16", temp: 0.7 },
  long: { ctx: 32768, kv: "q4", temp: 0.6 },
};
const TUNE_KEY = "stickllm_tune";
const LLAMA_CTX_FLOOR = 32768; // stickllm-llama-start raises smaller values (Agent Zero)
function tuneNow() {
  const num = (sel, d) => { const el = $(sel); const v = el ? Number(el.value) : NaN; return Number.isFinite(v) ? v : d; };
  return {
    ctx: num("#ctx", 8192), kv: state.kv || "f16", temp: num("#temp", 0.7),
    top_p: num("#topp", 0.9), top_k: num("#topk", 40), repeat_penalty: num("#rep", 1.1), max_tokens: num("#maxtok", CHAT_TOKENS),
  };
}
function paintCtxVal() {
  const v = +$("#ctx").value;
  $("#ctxVal").textContent = v.toLocaleString();
  const note = $("#ctxNote");
  if (note) note.hidden = v >= LLAMA_CTX_FLOOR;
}
function syncPresetHighlight() {
  const t = tuneNow();
  const max = +$("#ctx").max || 32768;
  let hit = "";
  for (const [k, p] of Object.entries(TUNE_PRESETS)) {
    if (t.ctx === Math.min(p.ctx, max) && t.kv === p.kv && Math.abs(t.temp - p.temp) < 0.001) { hit = k; break; }
  }
  $$("#presets button").forEach((x) => {
    const on = x.dataset.preset === hit;
    x.classList.toggle("on", on);
    x.setAttribute("aria-checked", on ? "true" : "false");
  });
  const c = $("#presetCustom");
  if (c) c.hidden = !!hit;
  return hit;
}
function saveTune() {
  try { localStorage.setItem(TUNE_KEY, JSON.stringify(tuneNow())); } catch (_) {}
}
function setKv(kv) {
  state.kv = ["f16", "q8", "q4"].includes(kv) ? kv : "f16";
  $$("#kvSeg button").forEach((x) => x.classList.toggle("on", x.dataset.kv === state.kv));
}
function applyTune(t) {
  if (!t) return;
  const set = (sel, v) => { const el = $(sel); if (el && v != null && Number.isFinite(Number(v))) el.value = v; };
  set("#ctx", Math.min(Number(t.ctx) || 8192, +$("#ctx").max || 32768));
  set("#temp", t.temp); set("#topp", t.top_p); set("#topk", t.top_k); set("#rep", t.repeat_penalty); set("#maxtok", t.max_tokens);
  if (t.kv) setKv(t.kv);
  if ($("#tempVal")) $("#tempVal").textContent = $("#temp").value;
  if ($("#toppVal")) $("#toppVal").textContent = $("#topp").value;
  paintCtxVal();
  syncPresetHighlight();
}
function applyPreset(name) {
  const p = TUNE_PRESETS[name];
  if (!p) return;
  applyTune({ ...tuneNow(), ctx: p.ctx, kv: p.kv, temp: p.temp });
  saveTune();
  renderModelsList();
}
$("#ctx").addEventListener("input", () => { paintCtxVal(); syncPresetHighlight(); saveTune(); });
$("#ctx").addEventListener("change", () => renderModelsList());
$$("#presets button").forEach((b) => (b.onclick = () => {
  applyPreset(b.dataset.preset);
  toast("Preset " + (b.querySelector("b")?.textContent || b.dataset.preset) + " · applies on next Load");
}));
$("#probeBtn").onclick = async () => {
  try { toast("Probing GPU…"); await control("model_probe"); await refreshModels(); toast("Probe done"); }
  catch (e) { toast(e.message); }
};
$("#refreshCatalog").onclick = () => refreshModels().then(() => toast("Catalog refreshed")).catch((e) => toast(e.message));
let loadPollTimer = null;
let loadTickTimer = null;
let loadStartedAt = 0;
let loadSizeGb = 8;
let loadShownPct = 1;
let loadFailed = false;
let loadTickLabel = "";
let loadTickPhase = "Starting llama…";
let lastLlama = null;
function stopLoadPoll() { if (loadPollTimer) { clearInterval(loadPollTimer); loadPollTimer = null; } }
function expectedLoadMs() {
  const gb = Math.max(1, Number(loadSizeGb) || 8);
  const per = loadBackendHint() === "ram" ? 35000 : 10000;
  return Math.max(20000, gb * per);
}
function loadPctFromClock() {
  if (!loadStartedAt) return 1;
  const t = Math.max(0, Date.now() - loadStartedAt);
  const pct = 92 * (1 - Math.exp(-t / expectedLoadMs()));
  return Math.max(1, Math.min(92, pct));
}
function shownLoadPct() {
  const clock = loadPctFromClock();
  loadShownPct = Math.max(loadShownPct || 1, clock);
  return loadShownPct;
}
function stopLoadTick() {
  if (loadTickTimer) { clearInterval(loadTickTimer); loadTickTimer = null; }
}
function startLoadTick() {
  if (loadTickTimer) return;
  loadTickTimer = setInterval(() => {
    if (!loadStartedAt) return;
    setChipLoad(true, 0, loadTickLabel, loadTickPhase, false);
  }, 1000);
}
function loadBackendHint() {
  const b = String($("#chipMeta")?.textContent || "").toUpperCase();
  if (b.includes("CUDA") || b.includes("GPU")) return "gpu";
  if (b.includes("VULKAN")) return "gpu";
  if (b.includes("CPU")) return "ram";
  return "auto";
}
function modelSizeGb(m) {
  const gb = m?.approx_size_gb ?? m?.size_gb ?? (m?.bytes != null ? Number(m.bytes) / 1e9 : null);
  const n = Number(gb);
  if (n > 0.2) return n;
  return guessSizeGb(m?.name || m?.id);
}
function guessSizeGb(name) {
  const s = String(name || "");
  const b = s.match(/(\d+(?:\.\d+)?)\s*B\b/i);
  if (!b) return 8;
  const p = Number(b[1]);
  if (p >= 60) return 40;
  if (p >= 30) return 20;
  if (p >= 12) return 10;
  if (p >= 6) return 5;
  return 2.5;
}
function llamaUnitBusy(health) {
  const svc = health && health.llama_service;
  if (!svc || typeof svc !== "object") return false;
  if (svc.process_alive) return true;
  const active = String(svc.active_state || "").toLowerCase();
  const sub = String(svc.sub_state || "").toLowerCase();
  return active === "activating" || sub === "start" || sub === "auto-restart";
}
function llamaView(health) {
  const svc = lastLlama || {};
  const load = (health && health.llama_load) || {};
  const restarts = Number(svc.n_restarts || 0);
  const fails = Number(svc.fail_count || load.fail_count || 0);
  const alive = !!svc.process_alive;
  const stopped = !!(svc.stopped || svc.result === "start-limit-hit");
  const crashed = !alive && (restarts >= 1 || fails >= 1 || !!svc.error || !!load.error);
  const giveUp = !alive && (stopped || restarts >= 2 || fails >= 2);
  const caption = svc.caption || load.caption || "";
  const error = (svc.error || load.error || "").trim();
  let pct = 0;
  if (!crashed && alive && Number.isFinite(Number(svc.progress_pct))) {
    pct = Math.max(1, Math.min(90, Number(svc.progress_pct) || 1));
  }
  return { crashed, giveUp, alive, caption, error, pct, restarts, fails };
}
function loadPhaseText(view) {
  if (view.crashed || view.giveUp) {
    const err = view.error || "GPU load failed";
    return view.giveUp ? err : err;
  }
  if (view.caption) return view.caption;
  if (!view.alive) return "Starting llama…";
  return "Loading weights…";
}
function sameModelPath(a, b) {
  const norm = (p) => String(p || "").replace(/\\/g, "/").replace(/\/+$/, "");
  const na = norm(a);
  const nb = norm(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  const ba = na.split("/").pop();
  const bb = nb.split("/").pop();
  return !!ba && ba === bb;
}
function requestedLoadName() {
  if (loadingModelName) return loadingModelName;
  const m = findModel(loadingModelId);
  return m?.name || loadingModelId || "model";
}
function requestedLoadPath() {
  if (loadingModelPath) return loadingModelPath;
  const m = findModel(loadingModelId);
  return String(m?.path || "");
}
/** llama_ok is the model that was clicked, not whichever server was already up. */
function loadFinishedOk(j) {
  if (!j?.llama_ok || !loadingModelId) return false;
  const runPath = String(j.connect?.running_model || "").trim();
  const envPath = String(j.connect?.model_path || "").trim();
  const gotId = String(j.connect?.model_id || "").trim();
  const wantPath = requestedLoadPath();
  if (runPath && wantPath && sameModelPath(runPath, wantPath)) return true;
  if (runPath && gotId === loadingModelId && envPath && sameModelPath(runPath, envPath)) return true;
  if (!runPath && loadSawNotOk && loadActivateSettled) {
    if (gotId && gotId === loadingModelId) return true;
    if (wantPath && sameModelPath(envPath, wantPath)) return true;
  }
  return false;
}
/** New process is healthy, and it is a different model than the click. */
function loadFinishedWrong(j) {
  if (!j?.llama_ok || !loadActivateSettled || !loadingModelId) return false;
  if (loadFinishedOk(j)) return false;
  const runPath = String(j.connect?.running_model || "").trim();
  const envPath = String(j.connect?.model_path || "").trim();
  const gotId = String(j.connect?.model_id || "").trim();
  const wantPath = requestedLoadPath();
  const processMatchesEnv = !!(runPath && envPath && sameModelPath(runPath, envPath));
  if (!processMatchesEnv && !loadSawNotOk) return false;
  if (processMatchesEnv && gotId && gotId !== loadingModelId) return true;
  if (processMatchesEnv && wantPath && runPath && !sameModelPath(runPath, wantPath)) return true;
  if (loadSawNotOk && gotId && gotId !== loadingModelId) return true;
  return false;
}
function runningModelLabel(j) {
  const runPath = String(j?.connect?.running_model || "").trim();
  const fromRun = friendlyModelLabel("", runPath);
  if (fromRun) return fromRun;
  return friendlyModelLabel(j?.connect?.model, j?.connect?.model_path) || "another model";
}
function phaseForRequestedLoad(view, j) {
  if (view.crashed || view.giveUp) return view.error || "GPU load failed";
  const planModel = String(j?.llama_load?.model || "").trim();
  const wantPath = requestedLoadPath();
  const captionOk = !!(view.caption && planModel && wantPath && sameModelPath(planModel, wantPath));
  if (captionOk) return view.caption;
  if (!view.alive) return "Starting llama…";
  return "Loading weights…";
}
function finishLoadSuccess(name) {
  if (!loadingModelId) return;
  const ready = name && name !== "none" ? name : requestedLoadName();
  stopLoadPoll();
  loadingModelId = null;
  loadingModelName = "";
  loadingModelPath = "";
  loadMismatchText = "";
  loadActivateSettled = false;
  loadSawNotOk = false;
  if ($("#chipModel")) $("#chipModel").textContent = ready;
  setChipLoad(false, 100, ready);
  if ($("#runName")) $("#runName").textContent = ready;
  if ($("#popModel")) {
    $("#popModel").textContent = ready;
    $("#popModel").title = "";
  }
  renderModelsList();
  toast("Model ready: " + ready);
}
function showLoadMismatch(actual) {
  if (!loadingModelId) return;
  const got = actual || "another model";
  const wanted = requestedLoadName();
  stopLoadPoll();
  loadingModelId = null;
  loadingModelName = "";
  loadingModelPath = "";
  loadActivateSettled = false;
  loadSawNotOk = false;
  loadMismatchText = `Load failed — running ${got}, not ${wanted}`;
  setChipLoad(true, 0, wanted, loadMismatchText, true);
  if ($("#chipModel")) $("#chipModel").textContent = "Load failed";
  if ($("#runName")) $("#runName").textContent = "Load failed";
  if ($("#popModel")) {
    $("#popModel").textContent = loadMismatchText;
    $("#popModel").title = got;
  }
  renderModelsList();
  toast(loadMismatchText);
}
let healthFails = 0;
function startLoadPoll() {
  stopLoadPoll();
  let ticks = 0;
  let modelErr = "";
  loadPollTimer = setInterval(async () => {
    ticks += 1;
    try {
      await refreshStatus();
      if (!loadingModelId) {
        stopLoadPoll();
        return;
      }
      // Never await a slow control status here: health drives the chip.
      if (!modelsFlight) refreshModels().then(() => { modelErr = ""; }).catch((e) => { modelErr = (e && e.message) || "control error"; });
      if (!loadingModelId) return;
      if (!loadActivateSettled && ticks * 2 >= 60) {
        const secs = ticks * 2;
        setLoadStatusLine(true, 1, requestedLoadName(),
          modelErr ? `Control service error: ${modelErr} — still waiting (${secs}s)`
            : `Waiting for the stick's control service (${secs}s)…`, false);
      }
      if (ticks > 450) {
        stopLoadPoll();
        loadingModelId = null;
        loadingModelName = "";
        setChipLoad(false, 0, null);
        renderModelsList();
        toast("Still loading — check Models");
      }
    } catch (_) {}
  }, 2000);
}
function showFewerLayers(on) {
  const show = !!on;
  for (const id of ["fewerLayers", "fewerLayersBar"]) {
    const b = $("#" + id);
    if (!b) continue;
    b.hidden = !show;
    if (show) b.removeAttribute("hidden");
    else b.setAttribute("hidden", "");
  }
}
function setLoadStatusLine(loading, pct, name, phase, failed) {
  const box = $("#loadStatus");
  if (!box) return;
  if (!loading) {
    box.hidden = true;
    box.setAttribute("hidden", "");
    box.classList.remove("failed");
    showFewerLayers(false);
    return;
  }
  box.hidden = false;
  box.removeAttribute("hidden");
  box.classList.toggle("failed", !!failed);
  const label = name && name !== "none" ? name : "";
  const phaseText = phase || "Loading weights…";
  if ($("#loadStatusText")) {
    const already = label && phaseText.includes(label);
    $("#loadStatusText").textContent = label && !already ? `${phaseText} — ${label}` : phaseText;
  }
  const n = failed ? 0 : Math.max(1, Math.min(92, Number(pct) || 1));
  if ($("#loadStatusFill")) $("#loadStatusFill").style.width = n + "%";
  if ($("#loadStatusPct")) $("#loadStatusPct").textContent = failed ? "" : (Math.round(n) + "%");
}
function setChipLoad(loading, pct, name, phase, failed) {
  const chip = $("#statusChip");
  const bar = $("#chipLoad");
  const fill = $("#chipLoadFill");
  // While a click is in flight, never paint connect.model / the baked 3B over it.
  if (loading && !failed && loadingModelId) {
    const want = requestedLoadName();
    if (want) name = want;
  }
  if (!loading) {
    loadStartedAt = 0;
    loadShownPct = 1;
    loadFailed = false;
    stopLoadTick();
  } else if (failed) {
    loadFailed = true;
    stopLoadTick();
  } else if (loadFailed) {
    return;
  } else {
    pct = shownLoadPct();
    if (name) loadTickLabel = name;
    if (phase) loadTickPhase = phase;
    startLoadTick();
  }
  setLoadStatusLine(loading, pct, name, phase, failed);
  if (!chip) return;
  chip.classList.toggle("loading", !!loading && !failed);
  chip.classList.toggle("failed", !!failed);
  chip.classList.remove("indeterminate");
  chip.classList.toggle("ready", !loading && !!name && name !== "none");
  if (bar) bar.hidden = !loading || !!failed;
  if (fill && loading && !failed) fill.style.width = Math.max(1, Math.min(92, Number(pct) || 1)) + "%";
  if ($("#chipModel")) {
    if (failed) {
      $("#chipModel").textContent = String(phase || "").startsWith("Load failed") ? "Load failed" : "GPU load failed";
    } else if (loading) {
      const label = name && name !== "none" ? name : "model";
      const n = Math.max(1, Math.min(92, Math.round(Number(pct) || 1)));
      $("#chipModel").textContent = `loading ${label} ${n}%`;
    }
  }
  $("#statusChip .dot")?.classList.toggle("ok", !loading);
  $("#statusChip .dot")?.classList.toggle("busy", !!loading);
}
/** Paint Loading UI before any network await (card badge + chip + under-composer line). */
function beginModelLoadUi(id, name) {
  const m = findModel(id) || lastCatalog.find((x) => x.id === id);
  loadingModelId = id;
  loadingModelName = name || m?.name || id || "model";
  loadingModelPath = String(m?.path || "");
  loadActivateSettled = false;
  loadSawNotOk = false;
  loadMismatchText = "";
  selectedModelId = id;
  loadSizeGb = modelSizeGb(m);
  loadShownPct = 1;
  loadFailed = false;
  loadTickLabel = loadingModelName;
  loadTickPhase = "Starting llama…";
  loadStartedAt = Date.now();
  renderModelsList();
  if ($("#runName")) $("#runName").textContent = loadingModelName;
  if ($("#runPill")) { $("#runPill").textContent = "loading"; $("#runPill").className = "pill warn"; }
  if ($("#popModel")) {
    $("#popModel").textContent = `loading — ${loadingModelName}`;
    $("#popModel").title = loadingModelPath || "";
  }
  setChipLoad(true, 1, loadingModelName, "Starting llama…");
  toast("Loading " + loadingModelName + "…");
}
function paintSoon() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

$("#activate").onclick = async () => {
  const m = findModel(selectedModelId);
  if (!m) return toast("Select a model");
  const name = m.name || m.id;
  try {
    // Synchronous UI first — do not wait for activate round-trip.
    beginModelLoadUi(m.id, name);
    startLoadPoll();
    await paintSoon();
    const res = await control("model_activate", { id: m.id, ctx_size: +$("#ctx").value, kv_type: { f16: "f16", q8: "q8_0", q4: "q4_0" }[state.kv] || "f16" });
    loadActivateSettled = true;
    if (!res.ok && res.error) throw new Error(res.error);
    if (res.id && String(res.id) !== String(m.id)) {
      showLoadMismatch(res.name || res.id);
      return;
    }
    if (res.running || res.load_state === "running") {
      finishLoadSuccess(res.name || name);
    } else {
      const view = llamaView(null);
      setChipLoad(true, 1, name, phaseForRequestedLoad(view, null), view.crashed);
      showFewerLayers(view.giveUp);
    }
    await refreshModels(); await refreshStatus();
  } catch (e) {
    stopLoadPoll();
    const wanted = loadingModelId ? requestedLoadName() : (m.name || m.id);
    loadingModelId = null;
    loadingModelName = "";
    loadingModelPath = "";
    loadMismatchText = `Load failed — ${wanted} did not start` + (e && e.message && e.message !== "Pair required" ? ` (${e.message})` : "");
    setChipLoad(true, 0, wanted, loadMismatchText, true);
    if ($("#chipModel")) $("#chipModel").textContent = "Load failed";
    if ($("#runName")) $("#runName").textContent = "Load failed";
    if ($("#popModel")) $("#popModel").textContent = loadMismatchText;
    renderModelsList();
    toast(e.message || loadMismatchText);
    // The list may be stale (vault locked / drive unmounted since it was drawn).
    refreshModels().then(() => renderModelsList()).catch(() => {});
  }
};

async function retryFewerLayers() {
  try {
    const res = await control("llama_fewer_layers", {});
    const n = res.n_gpu_layers || "?";
    toast("Retrying with " + n + " GPU layers");
    const m = lastCatalog.find((x) => x.id === selectedModelId) || lastCatalog.find((x) => x.active);
    beginModelLoadUi(m?.id || selectedModelId || "", m?.name || "model");
    loadActivateSettled = true;
    startLoadPoll();
  } catch (e) {
    toast(e.message);
  }
}
if ($("#fewerLayers")) $("#fewerLayers").onclick = () => retryFewerLayers();
if ($("#fewerLayersBar")) $("#fewerLayersBar").onclick = () => retryFewerLayers();

$("#dlModel").onclick = async () => {
  const m = findModel(selectedModelId);
  if (!m) return;
  if (isAbliterated(m) && !state.ablAck) {
    askAblAck(() => $("#dlModel").click());
    return;
  }
  const trust = modelTrust(m);
  if (trust === "blocked") {
    toast("Blocked: this file does not match StickLLM's verified hash.");
    return;
  }
  if (trust !== "verified") {
    confirmBox({
      title: "Download a model that is not verified?",
      text: UNVERIFIED_WARNING + ".",
      extra: (TRUST[trust] ? TRUST[trust].l + ": " + TRUST[trust].d + ". " : "") + "StickLLM still checks the download against Hugging Face's own hash when it has one.",
      word: "DOWNLOAD", ok: "Download anyway",
      cb: () => doModelDownload(m, { accept_unverified: true }),
    });
    return;
  }
  await doModelDownload(m);
};
async function downloadMmproj(id) {
  const m = findModel(id);
  if (!m) return;
  try {
    const res = await control("mmproj_download", {
      id: "mmproj:" + id,
      repo: m.hf_repo || m.repo || "",
      path: m.path || m.local_path || "",
      file: m.mmproj_file || "",
      bytes: m.mmproj_bytes || 0,
    });
    if (res.ok === false) throw new Error(res.error || "Could not download mmproj");
    applyDownloadView(res);
    renderModelsList();
    if (!res.already) startDlPoll();
    toast(res.note || (res.already ? "This model's mmproj is already next to it" : "Downloading this model's mmproj"));
  } catch (e) { toast(e.message); }
}
async function doModelDownload(m, extra) {
  try {
    const dest = ($("#modelDir")?.textContent || "").trim();
    const params = { id: m.id };
    if (m.repo && m.file) {
      params.repo = m.repo;
      params.file = m.file;
      if (m.sha256 || m.lfs_sha256) params.sha256 = m.sha256 || m.lfs_sha256;
      if (m.bytes) params.bytes = m.bytes;
      if (m.name) params.name = m.name;
    }
    if (dest && dest !== "…" && dest.startsWith("/")) params.dest = dest;
    Object.assign(params, extra || {});
    const res = await control("model_download", params);
    if (res.download_dir && $("#modelDir")) $("#modelDir").textContent = res.download_dir;
    applyDownloadView(res);
    renderModelsList();
    startDlPoll();
    toast(res.note || (res.started ? "Download started" : "Added to the download queue"));
  } catch (e) { toast(e.message); }
}
let ablCb = null;
function askAblAck(cb) {
  ablCb = cb;
  if ($("#ablChk")) $("#ablChk").checked = false;
  if ($("#ablOk")) $("#ablOk").disabled = true;
  if ($("#ablAck")) $("#ablAck").hidden = false;
  setTimeout(() => $("#ablChk")?.focus(), 20);
}
if ($("#ablChk")) $("#ablChk").onchange = (e) => { if ($("#ablOk")) $("#ablOk").disabled = !e.target.checked; };
if ($("#ablCancel")) $("#ablCancel").onclick = () => { if ($("#ablAck")) $("#ablAck").hidden = true; };
if ($("#ablOk")) $("#ablOk").onclick = () => {
  state.ablAck = true;
  if ($("#ablAck")) $("#ablAck").hidden = true;
  ablCb?.();
};
function askDeleteModel(m) {
  if (!m?.deletable) return toast("This model cannot be deleted (baked-in or protected)");
  const label = m.name || m.id;
  const where = m.path || m.local_path || "";
  const whereLine = where ? ` Files under ${where} will be removed.` : "";
  confirmBox({
    title: "Delete model files?",
    text: `Permanently delete “${label}” from this machine?${whereLine} This cannot be undone.`,
    word: "ARE YOU SURE",
    ok: "Delete files",
    cb: async () => {
      try {
        const res = await control("model_delete", { id: m.id, confirm: "ARE YOU SURE" });
        if (res?.ok === false) throw new Error(res.error || "delete failed");
        if (selectedModelId === m.id) selectedModelId = null;
        toast(`Deleted ${label}`);
        await refreshModels();
      } catch (e) { toast(e.message); }
    },
  });
}
$("#delModel").onclick = () => {
  askDeleteModel(lastCatalog.find((x) => x.id === selectedModelId));
};

async function refreshStorage() {
  if (!(await ensurePaired())) return;
  const ep = vaultEpoch;
  const st = await control("status");
  if (ep !== vaultEpoch || vaultBusy()) return; // stale: the vault changed meanwhile
  const v = st.vault || {};
  const open = vaultIsOpen(v);
  setVaultChrome(open, vaultIsAbsent(v));
  if ($("#vcSub")) {
    $("#vcSub").textContent = v.blob || v.root || v.path || (vaultIsAbsent(v) ? "No vault attached yet" : (open ? "" : "Enter the passcode to unlock"));
  }
  const wipe = Number(v.wipe_after_failed_unlocks || 0);
  if ($("#wipeN") && document.activeElement !== $("#wipeN")) $("#wipeN").value = String(wipe);
  await refreshDrivesLive();
  await refreshMovableLive();
}
async function refreshDrivesLive() {
  try {
    const res = await control("vault_devices");
    // Backend returns devices[] with selectable flags (+ separate mountable[]).
    const devices = Array.isArray(res.devices) ? res.devices : [];
    const sel = Array.isArray(res.selectable)
      ? res.selectable
      : devices.filter((d) => d && d.selectable);
    const mountable = Array.isArray(res.mountable) ? res.mountable : [];
    const blocked = Array.isArray(res.blocked_disks) ? res.blocked_disks : [];
    const box = $("#drives");
    if (!sel.length && !mountable.length && !blocked.length) {
      box.innerHTML = '<div class="row"><small>No browsable mounts. Mount a clear host volume, or unlock encrypted disks in the host OS.</small></div>';
      return;
    }
    let html = "";
    for (const d of sel) {
      const path = d.mount_path || d.path || "";
      const free = d.free_gb != null
        ? `${d.free_gb} GiB free`
        : (d.avail ? `${d.avail} free` : "");
      const warn = d.warn ? `<small class="muted">${esc(d.warn)}</small>` : "";
      html += `<button class="drive" data-path="${esc(path)}" type="button">
        <div class="dh"><b>${esc(d.label || path)}</b></div>
        <small class="mono">${esc(path)}</small>
        <small>${esc(free)} · ${esc(d.kind || d.fstype || d.fs || "")}</small>
        ${warn}
        <div><span class="pill ok">mounted</span></div></button>`;
    }
    for (const d of mountable) {
      const dev = d.device || d.path || "";
      const sz = d.size_gb != null ? `${d.size_gb} GiB · ` : "";
      html += `<div class="drive">
        <div class="dh"><b>${esc(d.label || dev)}</b></div>
        <small class="mono">${esc(dev)}</small>
        <small>${esc(sz)}${esc(d.fstype || "")} · never formats</small>
        <div><button class="btn sm" data-mountdev="${esc(dev)}" type="button">Mount</button></div></div>`;
    }
    for (const d of blocked) {
      const path = d.path || d.device || "";
      const sz = d.size_gb != null ? `${d.size_gb} GiB · ` : "";
      html += `<div class="drive blocked" aria-disabled="true">
        <div class="dh"><b>${esc(d.model || path || "Disk")}</b></div>
        <small class="mono">${esc(path)}</small>
        <small>${esc(sz)}${esc(d.reason || "Not mountable")}</small>
        <div><span class="pill">unavailable</span></div></div>`;
    }
    box.innerHTML = html;
    $$("#drives [data-path]").forEach((el) => (el.onclick = () => {
      vaultPickerMount = el.dataset.path;
      vaultBrowsePath = el.dataset.path;
      $("#vaultPath").value = el.dataset.path;
      pickerPurpose = "vault";
      if ($("#fpTitle")) $("#fpTitle").textContent = "Choose folder / vault";
      openLivePicker(el.dataset.path);
    }));
    $$("[data-mountdev]").forEach((b) => (b.onclick = async (e) => {
      e.stopPropagation();
      try {
        toast("Mounting…");
        const res = await control("vault_mount", {
          device: b.dataset.mountdev,
          confirm: "MOUNT-HOST",
        });
        if (res && res.ok === false) {
          throw new Error(res.error || res.stderr || "Mount failed");
        }
        await refreshDrivesLive();
        const mp = res.mount_path || "";
        toast(res.already_mounted ? (`Already mounted${mp ? " at " + mp : ""}`) : (`Mounted${mp ? " at " + mp : ""}`));
      } catch (err) { toast("Mount failed: " + (err.message || err)); }
    }));
  } catch (e) {
    $("#drives").innerHTML = `<div class="row"><small>${esc(e.message)}</small></div>`;
  }
}
function renderPickerSide() {
  const side = $("#fpSide");
  if (!side) return;
  const cur = vaultBrowsePath || "—";
  side.innerHTML =
    '<div class="fpSideLab">Search</div>' +
    '<button class="fpDrive" type="button" id="fpSideSearchVault"><span><b>Search for vault</b><small>stickllm-vault.img on mounts</small></span></button>' +
    '<button class="fpDrive" type="button" id="fpSideSearchModels"><span><b>Search for models</b><small>.gguf folders on this volume</small></span></button>' +
    '<div class="fpSideLab" style="margin-top:12px">Current</div>' +
    '<div class="row"><small class="mono">' + esc(cur) + "</small></div>";
  const sv = $("#fpSideSearchVault");
  const sm = $("#fpSideSearchModels");
  if (sv) sv.onclick = () => searchForVault({ inPicker: true });
  if (sm) sm.onclick = () => searchForModels({ inPicker: true });
}
async function openLivePicker(startPath) {
  $("#picker").hidden = false;
  $("#fpFileTools").hidden = true;
  if ($("#fpSearchVault")) $("#fpSearchVault").hidden = false;
  if ($("#fpSearchModels")) $("#fpSearchModels").hidden = false;
  vaultBrowsePath = startPath;
  await browseLive(startPath);
}
async function browseLive(path) {
  try {
    const res = await control("vault_list_dirs", { path });
    vaultBrowsePath = res.path || path;
    const parent = res.parent || "";
    $("#fpUp").disabled = !parent;
    $("#fpBackB").disabled = true; $("#fpFwd").disabled = true;
    $("#fpCrumbs").innerHTML = `<button class="crumbBtn" type="button">${esc(vaultBrowsePath)}</button>`;
    setFpCols();
    renderPickerSide();
    const dirs = res.dirs || res.entries || [];
    const files = res.files || [];
    let rows = "";
    for (const d of dirs) {
      const name = typeof d === "string" ? d : d.name;
      const p = typeof d === "string" ? (vaultBrowsePath.replace(/\/$/, "") + "/" + name) : (d.path || vaultBrowsePath + "/" + name);
      rows += `<div class="fpRow" data-dir="${esc(p)}" role="option"><span class="fpName dir"><span class="nm">${esc(name)}</span></span><span class="muted">folder</span><span class="muted">—</span></div>`;
    }
    for (const f of files) {
      const name = typeof f === "string" ? f : f.name;
      const p = typeof f === "string" ? (vaultBrowsePath.replace(/\/$/, "") + "/" + name) : (f.path || vaultBrowsePath + "/" + name);
      const isVault = /stickllm-vault\.img$/i.test(name);
      const isModel = /\.gguf$/i.test(name);
      if (!isVault && !isModel) continue;
      rows += `<div class="fpRow" data-file="${esc(p)}" data-kind="${isVault ? "vault" : "model"}" role="option"><span class="fpName ${isVault ? "vault" : "model"}"><span class="nm">${esc(name)}</span>${isVault ? '<span class="pill acc">vault</span>' : '<span class="pill">model</span>'}</span><span class="muted">file</span><span class="muted">—</span></div>`;
    }
    $("#fpList").innerHTML = rows || '<div class="fpEmpty">Empty / no vault or model files here</div>';
    $("#fpSel").textContent = vaultBrowsePath;
    $("#fpOk").disabled = false; $("#fpOk").textContent = "Use this folder";
    $$("#fpList [data-dir]").forEach((r) => {
      r.ondblclick = () => browseLive(r.dataset.dir);
      r.onclick = () => {
        $$("#fpList .fpRow").forEach((x) => x.classList.remove("sel"));
        r.classList.add("sel");
        $("#fpSel").textContent = r.dataset.dir;
        $("#fpOk").dataset.path = r.dataset.dir;
        $("#fpOk").dataset.kind = "folder";
      };
    });
    $$("#fpList [data-file]").forEach((r) => {
      r.onclick = () => {
        $$("#fpList .fpRow").forEach((x) => x.classList.remove("sel"));
        r.classList.add("sel");
        $("#fpSel").textContent = r.dataset.file;
        $("#fpOk").dataset.path = r.dataset.file;
        $("#fpOk").dataset.kind = r.dataset.kind;
        $("#fpOk").textContent = r.dataset.kind === "vault" ? "Open vault" : "Use folder";
      };
      r.ondblclick = () => { r.click(); $("#fpOk").click(); };
    });
    $("#fpOk").dataset.path = vaultBrowsePath;
    $("#fpOk").dataset.kind = "folder";
    vaultBrowseBlobPath = (files || []).map((f) => typeof f === "string" ? f : f.name).some((n) => /stickllm-vault\.img$/i.test(n))
      ? vaultBrowsePath.replace(/\/$/, "") + "/stickllm-vault.img" : "";
  } catch (e) {
    $("#fpList").innerHTML = `<div class="fpEmpty">${esc(e.message)}</div>`;
  }
}
function mountRootForSearch() {
  const cur = (vaultBrowsePath || vaultPickerMount || "").trim();
  if (cur.startsWith("/")) return cur;
  const vp = ($("#vaultPath")?.value || "").trim();
  if (vp.startsWith("/")) return vp;
  const first = $("#drives [data-path]");
  return first ? first.dataset.path : "";
}
function setFpCols(name = "Name", mid = "Modified", size = "Size") {
  const cols = $(".fpCols");
  if (!cols) return;
  cols.innerHTML = `<span>${esc(name)}</span><span>${esc(mid)}</span><span>${esc(size)}</span>`;
}
function modelKindLabel(kind) {
  switch (String(kind || "")) {
    case "gguf_dir": return "GGUF";
    case "models_dir": return "models/";
    case "ollama": return "Ollama";
    case "huggingface": return "HF cache";
    case "lm_studio": return "LM Studio";
    case "gpt4all": return "GPT4All";
    case "comfyui": return "ComfyUI";
    case "webui": return "WebUI";
    default: return "folder";
  }
}
/** Search-hit row: name + secondary path under it; mid/size only for real metadata. */
function fpHitRowHtml({
  name, pathHint = "", kindClass = "", pill = "", pillClass = "",
  mid = "—", size = "—", attrs = "",
}) {
  const sub = pathHint
    ? `<span class="fpSub muted" title="${esc(pathHint)}">${esc(pathHint)}</span>`
    : "";
  const pillHtml = pill
    ? `<span class="pill ${pillClass}">${esc(pill)}</span>`
    : "";
  return (
    `<div class="fpRow fpHit" ${attrs} role="option">` +
      `<span class="fpName ${kindClass}">` +
        `<span class="nmCol"><span class="nm">${esc(name)}</span>${sub}</span>` +
        pillHtml +
      `</span>` +
      `<span class="muted fpMeta">${esc(mid)}</span>` +
      `<span class="muted fpSize">${esc(size)}</span>` +
    `</div>`
  );
}
function fmtVaultSize(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v <= 0) return "";
  if (v >= 1e9) return `${(v / 1e9).toFixed(v >= 1e10 ? 0 : 1)} GB`;
  if (v >= 1e6) return `${Math.round(v / 1e6)} MB`;
  return `${v} B`;
}
async function searchForVault({ inPicker = false } = {}) {
  try {
    toast("Searching…");
    const res = await control("vault_find");
    let hits = res.hits || res.found || [];
    if (!hits.length && Array.isArray(res.candidates) && res.candidates.length) {
      hits = res.candidates;
    }
    if (!hits.length && res.best) hits = [res.best];
    if (!hits.length && !res.blob && !res.path && !res.best) {
      const note = res.note || "No stickllm-vault.img found";
      if (inPicker) {
        setFpCols();
        $("#fpList").innerHTML = `<div class="fpEmpty">${esc(note)}</div>`;
      } else {
        const box = $("#findHits");
        if (box) { box.hidden = false; box.innerHTML = `<div class="row"><small>${esc(note)}</small></div>`; }
      }
      toast(note);
      return;
    }
    const list = hits.length
      ? hits
      : [{ blob: res.blob || res.path || res.best?.blob, path: res.blob || res.path || res.best?.blob }];
    if (inPicker) {
      setFpCols("Name", "Kind", "Size");
      let rows = "";
      for (const h of list.slice(0, 20)) {
        const blob = h.blob || h.path || "";
        const folder = h.root || String(blob).replace(/\/stickllm-vault\.img$/i, "");
        const name = String(blob).split("/").pop() || "stickllm-vault.img";
        const sz = fmtVaultSize(h.size);
        rows += fpHitRowHtml({
          name,
          pathHint: folder,
          kindClass: "vault",
          pill: "vault",
          pillClass: "acc",
          mid: "vault",
          size: sz || "—",
          attrs: `data-file="${esc(blob)}" data-kind="vault" data-folder="${esc(folder)}"`,
        });
      }
      $("#fpList").innerHTML = rows || '<div class="fpEmpty">No vault files found</div>';
      $("#fpCrumbs").innerHTML = '<button class="crumbBtn" type="button">Search results — vault</button>';
      $$("#fpList [data-file]").forEach((r) => {
        r.onclick = () => {
          $$("#fpList .fpRow").forEach((x) => x.classList.remove("sel"));
          r.classList.add("sel");
          $("#fpSel").textContent = r.dataset.file;
          $("#fpOk").dataset.path = r.dataset.file;
          $("#fpOk").dataset.kind = "vault";
          $("#fpOk").textContent = "Open vault";
          $("#fpOk").disabled = false;
        };
        r.ondblclick = () => { r.click(); $("#fpOk").click(); };
      });
      toast(`Found ${list.length} vault file(s)`);
      return;
    }
    const best = res.best || list[0];
    const blob = best.blob || best.path || "";
    const box = $("#findHits");
    if (box) {
      box.hidden = false;
      box.innerHTML = `<div class="row"><div><b class="mono">${esc(blob)}</b><small>Found vault</small></div>
        <button class="btn sm" id="hitOpenVault" type="button">Attach</button></div>`;
      $("#hitOpenVault").onclick = async () => {
        try {
          const folder = String(blob).replace(/\/stickllm-vault\.img$/i, "");
          await control("vault_attach", { path: folder });
          $("#vcSub").textContent = blob; $("#vaultPath").value = folder;
          toast("Attached — unlock with passcode"); $("#vaultPass").focus();
        } catch (e) { toast(e.message); }
      };
    }
    toast(`Found ${list.length} vault file(s)`);
  } catch (e) { toast(e.message); }
}
async function searchForModels({ inPicker = false } = {}) {
  try {
    const base = mountRootForSearch();
    if (!base) {
      toast("Open a mounted drive first, then Search for models");
      return;
    }
    toast("Searching…");
    const res = await control("vault_find_models", { path: base });
    if (res.ok === false) throw new Error(res.error || "find models failed");
    const hits = res.models || res.hits || res.roots || [];
    const jump = res.best?.path || res.jump_dir || res.start_dir || "";
    const mode = String(res.collapse_mode || "");
    // Remembered for Load; Change… remains the download write target.
    refreshModels().catch(() => {});
    if (inPicker) {
      if (!hits.length) {
        // No list to show — jump into best folder if we have one.
        if (jump) {
          try { await browseLive(jump); } catch (_) {}
        } else {
          setFpCols();
          $("#fpList").innerHTML = '<div class="fpEmpty">No .gguf models found on this volume</div>';
        }
        toast(res.note || "No .gguf models found");
        return;
      }
      setFpCols("Name", "Kind", "GGUF");
      let rows = "";
      for (const m of hits.slice(0, 40)) {
        const p = m.path || m.dir || "";
        const name = m.name || (p.split("/").pop() || p);
        const folder = m.dir || (/\.gguf$/i.test(p) ? p.replace(/\/[^/]+$/, "") : p);
        const pathHint = m.relative || folder || p;
        const n = Number(m.gguf_count);
        const size = Number.isFinite(n) && n > 0 ? `${n} GGUF` : "—";
        const pill = mode === "multi_root" ? "library" : "models";
        rows += fpHitRowHtml({
          name,
          pathHint,
          kindClass: "model",
          pill,
          mid: modelKindLabel(m.kind),
          size,
          attrs: `data-dir="${esc(folder || p)}" title="${esc(folder || p)}"`,
        });
      }
      $("#fpList").innerHTML = rows;
      const crumb = mode === "multi_root"
        ? "Model libraries (load from any · Change… sets download)"
        : "Models library (collapsed · Change… sets download)";
      $("#fpCrumbs").innerHTML = `<button class="crumbBtn" type="button">${esc(crumb)}</button>`;
      $$("#fpList [data-dir]").forEach((r) => {
        r.ondblclick = () => browseLive(r.dataset.dir);
        r.onclick = () => {
          $$("#fpList .fpRow").forEach((x) => x.classList.remove("sel"));
          r.classList.add("sel");
          $("#fpSel").textContent = r.dataset.dir;
          $("#fpOk").dataset.path = r.dataset.dir;
          $("#fpOk").dataset.kind = "folder";
          $("#fpOk").textContent = pickerPurpose === "models_dir" ? "Use as download folder" : "Use this folder";
          $("#fpOk").disabled = false;
        };
      });
      toast(res.note || `Found ${hits.length} model library(ies) — remembered for Load`);
      return;
    }
    const box = $("#findHits");
    if (box) {
      box.hidden = false;
      if (!hits.length) {
        box.innerHTML = '<div class="row"><small>No .gguf models found on scanned mounts.</small></div>';
      } else {
        box.innerHTML = hits.slice(0, 12).map((m) =>
          `<div class="row"><div><b>${esc(m.name || m.path)}</b><small class="mono">${esc(m.path || m.dir || "")}</small></div></div>`
        ).join("") + '<div class="row"><small class="muted">Remembered for Load. Downloads use Models › Change… only.</small></div>';
      }
    }
    if (jump && $("#picker") && !$("#picker").hidden) await browseLive(jump).catch(() => {});
    toast(hits.length ? (res.note || `Found ${hits.length} library(ies)`) : (res.note || "No models found"));
  } catch (e) { toast(e.message); }
}
$("#fpUp").onclick = async () => {
  try {
    const cur = await control("vault_list_dirs", { path: vaultBrowsePath });
    if (cur.parent) await browseLive(cur.parent);
  } catch (e) { toast(e.message); }
};
$("#fpCancel").onclick = () => ($("#picker").hidden = true);
$("#fpClose").onclick = () => ($("#picker").hidden = true);
$("#picker").onclick = (e) => { if (e.target.id === "picker") $("#picker").hidden = true; };
$("#fpOk").onclick = async () => {
  const path = $("#fpOk").dataset.path || vaultBrowsePath;
  const kind = $("#fpOk").dataset.kind || "folder";
  const purpose = pickerPurpose;
  $("#picker").hidden = true;
  if (purpose === "models_dir" && kind !== "vault") {
    try {
      const res = await control("set_models_dir", { path });
      if (!res.ok) throw new Error(res.error || "set models folder failed");
      if ($("#modelDir")) $("#modelDir").textContent = res.path || path;
      toast("Models will download to " + (res.path || path));
      await refreshModels().catch(() => {});
    } catch (e) { toast(e.message); }
    pickerPurpose = "vault";
    return;
  }
  if (kind === "vault") {
    try {
      const folder = path.replace(/\/stickllm-vault\.img$/i, "");
      const res = await control("vault_attach", { path: folder });
      if (!res.ok) throw new Error(res.error || "attach failed");
      $("#vcSub").textContent = res.blob || path;
      $("#vaultPath").value = folder;
      toast("Vault attached — enter passcode to unlock");
      $("#vaultPass").focus();
      await refreshStorage();
    } catch (e) { toast(e.message); }
  } else {
    $("#vaultPath").value = path;
    toast("Folder selected for vault create");
  }
  pickerPurpose = "vault";
};
$("#fpNew").onclick = async () => {
  const name = prompt("New folder name", "stickllm");
  if (!name) return;
  try {
    const res = await control("vault_mkdir", { path: vaultBrowsePath, name: name.trim() });
    if (!res.ok) throw new Error(res.error || "mkdir failed");
    await browseLive(res.path || vaultBrowsePath);
    toast("Folder created");
  } catch (e) { toast(e.message); }
};
$("#fpBackB").onclick = null; $("#fpFwd").onclick = null;

$("#refreshDrives").onclick = () => refreshDrivesLive().then(() => toast("Drives refreshed"));
$("#actClaim").onclick = () => {
  confirmBox({
    title: "Use free space on the stick?",
    text: "Creates a StickLLM data partition on this StickLLM USB stick only. Your own drives are never partitioned.",
    word: "USE-STICK-SPACE", ok: "Use free space",
    cb: async () => {
      try { toast("Claiming…"); await control("usb_claim"); toast("Claim finished"); await refreshStorage(); }
      catch (e) { toast(e.message); }
    },
  });
};
if ($("#actFindVault")) $("#actFindVault").onclick = () => searchForVault({ inPicker: false });
if ($("#actFindModels")) $("#actFindModels").onclick = () => searchForModels({ inPicker: false });
if ($("#fpSearchVault")) $("#fpSearchVault").onclick = () => searchForVault({ inPicker: true });
if ($("#fpSearchModels")) $("#fpSearchModels").onclick = () => searchForModels({ inPicker: true });
async function openFolderPicker(purpose, title) {
  pickerPurpose = purpose || "vault";
  const start = ($("#modelDir")?.textContent || "").trim();
  const fallback = ($("#vaultPath").value || vaultBrowsePath || "").trim();
  const path = (purpose === "models_dir" && start.startsWith("/")) ? start : (fallback || start);
  const applyTitle = () => {
    if ($("#fpTitle")) $("#fpTitle").textContent = title || (purpose === "models_dir" ? "Choose models folder" : "Choose folder / vault");
  };
  if (path && path.startsWith("/") && path !== "…") {
    await openLivePicker(path);
    applyTitle();
    return;
  }
  await refreshDrivesLive();
  const first = $("#drives [data-path]");
  if (first) {
    await openLivePicker(first.dataset.path);
    applyTitle();
  } else toast("Mount a drive or claim stick DATA first");
}
$("#pickVault").onclick = () => openFolderPicker("vault", "Choose folder / vault");
$("#pickCreate").onclick = () => openFolderPicker("vault", "Choose folder for new vault");
if ($("#pickModelDir")) {
  $("#pickModelDir").disabled = false;
  $("#pickModelDir").removeAttribute("title");
  $("#pickModelDir").onclick = () => openFolderPicker("models_dir", "Choose models folder");
}

$("#unlockForm").onsubmit = async (e) => {
  e.preventDefault();
  const pass = $("#vaultPass").value || "";
  if (!pass) { unlockMessage("Enter the vault passcode."); return toast("Enter the vault passcode"); }
  if (vaultUnlocking) return;
  unlockMessage("");
  vaultUnlocking = true;
  vaultEpoch += 1;
  if ($("#vcState")) $("#vcState").textContent = "Unlocking…";
  try {
    const payload = { passcode: pass };
    const bind = ($("#vaultPath").value || "").trim();
    if (bind) payload.path = bind;
    $("#vaultPass").value = "";
    const res = await control("vault_unlock", payload);
    if (!res.ok) throw new Error(res.error || res.stderr || "unlock failed");
    vaultUnlocking = false;
    setVaultChrome(true);
    toast("Vault unlocked");
    await setSessionMode("vault");
    await refreshStorage();
  } catch (err) {
    vaultUnlocking = false;
    setVaultChrome(false);
    unlockMessage("Unlock failed: " + err.message);
    toast("Unlock failed: " + err.message);
  } finally {
    vaultUnlocking = false;
  }
};

$("#createVault").onclick = () => {
  const path = ($("#vaultPath").value || "").trim();
  const size = String($("#vaultSize").value || "32");
  const p1 = $("#np1").value, p2 = $("#np2").value;
  if (!path) return toast("Choose a folder first");
  if (p1.length < 8) return toast("Passcode must be at least 8 characters");
  if (p1 !== p2) return toast("Passcodes don't match");
  confirmBox({
    title: "Create vault?",
    text: `Creates a ${size} GiB encrypted file in ${path}. Never formats your drive.`,
    word: "CREATE-VAULT", ok: "Create vault",
    cb: async () => {
      try {
        const res = await control("vault_setup", {
          path, size_gb: size, confirm: "CREATE-VAULT",
          recovery_confirm: "SHOW-ONCE", passcode: p1, passcode2: p2, space_confirm: "SPACE-OK",
        });
        $("#np1").value = $("#np2").value = "";
        if (!res.ok) throw new Error(res.error || res.stderr || "setup failed");
        const phrase = res.recovery_phrase || "(no phrase in response — check stick logs)";
        confirmBox({
          title: "Save your recovery phrase",
          text: "This is the only time it's shown. Write it down.",
          extra: phrase, word: "SAVED", ok: "Finish setup",
          cb: async () => {
            $("#np1").value = $("#np2").value = "";
            setVaultChrome(true);
            toast("Vault created");
            await setSessionMode("vault");
            await refreshStorage();
          },
        });
      } catch (e) { toast(e.message); }
    },
  });
};
$("#growBtn").onclick = () => {
  const gb = String($("#growGb").value || "8");
  confirmBox({
    title: "Grow vault?", text: `Expand blob by ${gb} GiB.`, word: "GROW-VAULT", ok: "Grow",
    cb: async () => {
      try {
        const res = await control("vault_grow", { add_gb: gb, confirm: "GROW-VAULT" });
        if (!res.ok) throw new Error(res.error || "grow failed");
        toast("Vault grown"); await refreshStorage();
      } catch (e) { toast(e.message); }
    },
  });
};
$("#wipeBtn").onclick = () => {
  const n = String($("#wipeN").value || "0");
  if (n === "0") {
    control("vault_set_wipe", { n: "0", confirm: "OFF" }).then(() => toast("Wipe-after-N off")).catch((e) => toast(e.message));
    return;
  }
  confirmBox({
    title: "Enable auto-wipe?",
    text: `After ${n} wrong passcodes the vault key header is destroyed.`,
    word: "WIPE-OK", ok: "Enable",
    cb: async () => {
      try {
        await control("vault_set_wipe", { n, confirm: "WIPE-OK" });
        toast(`Wipe after ${n} tries enabled`);
      } catch (e) { toast(e.message); }
    },
  });
};
async function refreshMovableLive() {
  const box = $("#movable");
  if (!state.vaultOpen) {
    box.innerHTML = '<div class="row"><small>Unlock the vault to move models off the stick.</small></div>';
    return;
  }
  try {
    const res = await control("vault_list_movable");
    const models = res.models || [];
    if (!models.length) { box.innerHTML = '<div class="row"><small>No USB models to move.</small></div>'; return; }
    box.innerHTML = models.map((m, i) =>
      `<div class="row"><div><b>${esc(m.name)}</b><small>${fmtBytes(m.size)}${m.in_vault ? " · already in vault" : ""}</small></div>
      ${m.in_vault ? "" : `<button class="btn sm" data-mv="${i}" type="button">Move to vault</button>`}</div>`
    ).join("");
    $$("[data-mv]").forEach((b) => (b.onclick = async () => {
      const m = models[+b.dataset.mv];
      confirmBox({
        title: "Move model into vault?",
        text: `${m.name} — source removed after SHA-256 verify.`,
        word: "MOVE-MODEL", ok: "Move",
        cb: async () => {
          try {
            await control("vault_move_model", { path: m.path, confirm: "MOVE-MODEL" });
            toast("Moved"); await refreshMovableLive();
          } catch (e) { toast(e.message); }
        },
      });
    }));
  } catch (e) { box.innerHTML = `<div class="row"><small>${esc(e.message)}</small></div>`; }
}
$("#refreshMovable").onclick = () => refreshMovableLive();

async function loadVaultChats() {
  const r = await fetch("/api/chats", { headers: authHeaders() });
  const j = await r.json();
  if (!r.ok || j.ok === false) throw new Error(j.error || "list failed");
  state.chats = (j.chats || []).map((c) => ({ ...c, msgs: [] }));
  renderConvs(); renderSaved();
}
async function openVaultChat(id) {
  try {
    const r = await fetch(`/api/chats/${encodeURIComponent(id)}`, { headers: authHeaders() });
    const j = await r.json();
    if (!r.ok || j.ok === false) throw new Error(j.error || "load failed");
    activeChatId = j.id || id;
    messages.length = 0;
    const c = { id: activeChatId, title: j.title || id, msgs: [] };
    for (const m of j.messages || []) {
      if (m.role === "system") { messages.push(m); continue; }
      messages.push(m);
      c.msgs.push({ r: m.role === "assistant" ? "ai" : m.role, t: m.content });
    }
    if (!messages.some((x) => x.role === "system")) {
      messages.unshift({ role: "system", content: "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful." });
    }
    leaveApps();
    state.current = c; renderThread(); renderConvs(); closeSettings();
  } catch (e) { toast(e.message); }
}
async function saveCurrentChat(quiet) {
  if (sessionMode !== "vault" || !state.vaultOpen) {
    if (!quiet) toast("Switch to Vault mode to save");
    return;
  }
  const title = (messages.find((m) => m.role === "user")?.content || "Chat").slice(0, 60);
  const r = await fetch("/api/chats", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ id: activeChatId || undefined, title, messages }),
  });
  const j = await r.json();
  if (!r.ok || j.ok === false) throw new Error(j.error || "save failed");
  activeChatId = j.id;
  if (state.current) { state.current.id = j.id; state.current.title = j.title || title; }
  if (!quiet) toast("Saved to vault");
  loadVaultChats().catch(() => {});
}
async function deleteVaultChat(id) {
  const cid = String(id || "").trim();
  if (!cid) return;
  if (!confirm("Delete this chat?")) return;
  const wasOpen = !!(state.current && String(state.current.id) === cid);
  const r = await fetch("/api/chats", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ delete: true, id: cid }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || "delete failed");
  state.chats = state.chats.filter((c) => String(c.id) !== cid);
  if (wasOpen) newChat();
  else renderConvs();
  renderSaved();
  try { await loadVaultChats(); } catch (_) {}
  toast("Deleted");
}
function renderSaved() {
  const box = $("#savedChats");
  if (!state.vaultOpen) {
    box.innerHTML = '<div class="row"><small>Unlock the vault to see saved chats.</small></div>';
    return;
  }
  if (!state.chats.length) {
    box.innerHTML = '<div class="row"><small>No saved chats.</small></div>';
    return;
  }
  box.innerHTML = state.chats.map((c) =>
    `<div class="row"><div><b>${esc(c.title || c.id)}</b><small>${c.messages || 0} messages</small></div>
    <div class="inline"><button class="btn sm" data-oc="${esc(c.id)}" type="button">Open</button>
    <button class="btn sm danger ghost" data-dc="${esc(c.id)}" type="button">Delete</button></div></div>`
  ).join("");
  $$("[data-oc]").forEach((b) => (b.onclick = () => openVaultChat(b.dataset.oc)));
  $$("[data-dc]").forEach((b) => (b.onclick = () => {
    deleteVaultChat(b.dataset.dc).catch((e) => toast(e.message));
  }));
}
$("#saveChat").onclick = () => saveCurrentChat(false).catch((e) => toast(e.message));

function detectLocalHost() {
  const h = String(location.hostname || "").toLowerCase();
  return h === "127.0.0.1" || h === "localhost" || h === "::1";
}
function pushSystemMsg(text) {
  state.current = state.current || { id: Date.now(), title: "System", msgs: [] };
  if (!state.ephemeral.includes(state.current) && !state.chats.includes(state.current))
    state.ephemeral.unshift(state.current);
  state.current.msgs.push({ r: "system", t: text });
  renderThread();
}
function formatPairCode(code) {
  const c = String(code || "").trim();
  return c.length === 6 ? c.slice(0, 3) + " " + c.slice(3) : c;
}
function showPairCodeOnStick(code) {
  const c = String(code || "").trim();
  // The pair code is only ever painted on the stick's own screen.
  if (!detectLocalHost() || !/^\d{4,8}$/.test(c)) return;
  if ($("#pairCodeShow")) $("#pairCodeShow").textContent = formatPairCode(c);
  pushSystemMsg(
    `New PAIR CODE: ${c} — open the LAN URL on phone/desktop and enter this code. Previous paired browsers were unpaired.`
  );
}
function pairDigits(raw) {
  const c = String(raw || "").trim().replace(/\s/g, "");
  return /^\d{4,8}$/.test(c) ? c : "";
}
/** Paint the F9 banner from the latest code. Does not consume remint id. */
function paintF9PairCode(connect) {
  if (!detectLocalHost() || !$("#pairCodeShow")) return "";
  const c = connect || {};
  const digits = pairDigits(c.remint_code) || pairDigits(c.pair_code);
  if (!digits) return "";
  const shown = String($("#pairCodeShow").textContent || "").replace(/\s/g, "");
  if (shown !== digits) $("#pairCodeShow").textContent = formatPairCode(digits);
  return digits;
}
/** Stick kiosk: a LAN browser pressed "Show a new code on the stick". */
let lastPairRequestId = null;
function handlePairRequest(c) {
  const req = c && c.pair_request;
  const id = req && String(req.id || "");
  if (lastPairRequestId === null) { lastPairRequestId = id || ""; if (!id || Date.now() / 1000 - Number(req.at || 0) > 60) return; }
  if (!id || id === lastPairRequestId) return;
  lastPairRequestId = id;
  const who = req.ip ? ` (${req.ip})` : "";
  if (req.needs_confirm) {
    const box = $("#kioskPairReq");
    if (box) {
      $("#kioskPairReqText").textContent = `A browser${who} asks to pair. A new code unpairs the browser that is paired now.`;
      box.hidden = false; box.removeAttribute("hidden");
    }
    pushSystemMsg(`A browser${who} asks to pair. Press F9 (or Make new code) to show a new code — that unpairs the current browser.`);
    toast("Pair request from a browser");
    return;
  }
  const digits = pairDigits(c.pair_code) || pairDigits(c.remint_code);
  if (digits) {
    openSettings("devices");
    paintF9PairCode(c);
    pushSystemMsg(`PAIR CODE: ${digits} — a browser${who} asked to pair. Enter this code there.`);
    toast("Pair code " + formatPairCode(digits));
  } else {
    issuePairHotkey();
  }
}
/** Stick kiosk: chat line when a LAN browser mints a new code. */
function announceRemintFromConnect(connect) {
  if (!detectLocalHost()) return;
  const c = connect || {};
  try { handlePairRequest(c); } catch (_) {}
  const rid = String(c.remint_id || "").trim();
  const digits = paintF9PairCode(c);
  if (lastRemintId === null) {
    lastRemintId = rid;
    return;
  }
  if (!rid || rid === lastRemintId) return;
  if (!digits) return;
  lastRemintId = rid;
  pushSystemMsg(
    `New PAIR CODE: ${digits} — open the LAN URL on phone/desktop and enter this code. Previous paired browsers were unpaired.`
  );
  toast("New pair code — enter it on the LAN browser");
}
async function remintPairCode() {
  const r = await fetch("/api/pair/remint", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: "{}", cache: "no-store",
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.message || j.error || `remint ${r.status}`);
  return j;
}
async function issuePairHotkey() {
  // Keyboard-first path for HDMI kiosk (no mouse): open Pairing + mint/show code.
  openSettings("devices");
  if (!detectLocalHost()) {
    // Kiosk only: a LAN browser can neither see nor make a pair code.
    applyPairKioskUi();
    toast("Make a new pair code on the stick's own screen (press F9 there)");
    return;
  }
  try {
    const j = await remintPairCode();
    clearPairSession();
    const rid = String(j.remint_id || "").trim();
    if (rid) lastRemintId = rid;
    const code = String(j.pair_code || "").trim();
    if (code) {
      showPairCodeOnStick(code);
      toast("New pair code " + formatPairCode(code));
    } else {
      if ($("#pairCodeShow")) $("#pairCodeShow").textContent = "(see stick screen)";
      pushSystemMsg("New pair code minted on the stick. Enter the PAIR CODE shown on the stick screen chat.");
      toast("Look at the stick screen for the new PAIR CODE");
    }
    await refreshStatus();
  } catch (e) { toast(e.message); }
}
async function issueSshHotkey() {
  // F10 from any StickLLM screen. The server only returns the password to this UI.
  try {
    const r = await fetch("/api/health", { cache: "no-store", headers: authHeaders() });
    const j = await r.json().catch(() => ({}));
    const c = j.connect || {};
    const pass = String(c.ssh_password || "").trim();
    const enabled = !!c.ssh_enabled;
    const user = c.ssh_user || "stickllm";
    const host = c.ssh_host || c.ip || "127.0.0.1";
    if (enabled && pass) {
      pushSystemMsg(`SSH: ${user}@${host}  password: ${pass}`);
      toast("SSH password posted in chat");
    } else if (enabled) {
      pushSystemMsg("SSH is enabled but password is not in this response yet — check READY/Term, or reboot menu 3 Test - SSH Enabled.");
      toast("SSH on — password not available here");
    } else {
      pushSystemMsg("SSH is off on this boot. Reboot → GRUB → 2 Terminal or 3 Test - SSH Enabled to get a password.");
      toast("SSH disabled on this boot");
    }
  } catch (e) { toast(e.message); }
}
$("#remint").onclick = () => { issuePairHotkey(); };
/** LAN browsers: no code, no New code. Both live on the kiosk only. */
function applyPairKioskUi() {
  if (detectLocalHost()) return;
  const btn = $("#remint");
  if (btn) { btn.hidden = true; btn.disabled = true; }
  const label = $("#sec-devices .code small");
  if (label) label.textContent = "Pair code (shown only on the stick's screen; press F9 there)";
  const show = $("#pairCodeShow");
  if (show) show.textContent = "(see stick screen)";
}
applyPairKioskUi();
/** One pairing for StickLLM and Agent: a paired LAN tab gets a one-time
 *  link that signs this browser in to the Agent port (its own cookie). */
function openAgentPaired(e) {
  const a = e.target && e.target.closest ? e.target.closest("#agentLink, #agentDeskIcon") : null;
  if (!a || e.button || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  e.stopPropagation();
  const fallback = a.href;
  let resolve = null;
  if (!detectLocalHost() && token) {
    resolve = async () => {
      try {
        const r = await fetch("/api/agent/handoff", {
          method: "POST", cache: "no-store",
          headers: authHeaders({ "Content-Type": "application/json" }), body: "{}",
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.url) return j.url;
      } catch (_) {}
      return fallback;
    };
  }
  if (!openNamedTab(AGENT_TAB, fallback, resolve)) window.location.href = fallback;
}
document.addEventListener("click", (e) => { openAgentPaired(e); }, true);
if ($("#showSsh")) $("#showSsh").onclick = () => { issueSshHotkey(); };
if ($("#npAsk")) $("#npAsk").onclick = () => { requestKioskCode(); };
if ($("#npForm")) $("#npForm").onsubmit = async (e) => {
  e.preventDefault();
  const v = String($("#npCode").value || "").replace(/\s/g, "");
  const err = $("#npErr");
  if (!/^\d{4,8}$/.test(v)) { err.hidden = false; err.textContent = "Enter the code from the stick screen"; return; }
  try {
    await pairWithCode(v);
    err.hidden = true; $("#npCode").value = "";
    toast("Browser paired");
    startAppStatus();
    startOpenAppEvents();
    refreshModels().catch(() => {});
  } catch (ex) { err.hidden = false; err.textContent = ex.message; }
};
for (const el of document.querySelectorAll(".pairLink")) {
  el.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (pairUiState === "unpaired") showNotPaired();
    else openSettings("devices");
  });
}
setPairIcon();
if ($("#kprNo")) $("#kprNo").onclick = () => { $("#kioskPairReq").hidden = true; };
if ($("#kprYes")) $("#kprYes").onclick = () => { $("#kioskPairReq").hidden = true; issuePairHotkey(); };
$("#pairForm").onsubmit = async (e) => {
  e.preventDefault();
  const v = $("#pairIn").value.trim();
  const err = $("#pairErr");
  if (!/^\d{4,8}$/.test(v)) { err.hidden = false; err.textContent = "Enter the code from the stick screen"; return; }
  try {
    await pairWithCode(v);
    err.hidden = true; $("#pairIn").value = "";
    toast("Browser paired"); closeSettings();
    startAppStatus();
    startOpenAppEvents();
  } catch (ex) { err.hidden = false; err.textContent = ex.message; }
};

$("#copyUrl").onclick = () => {
  const u = $("#lanUrl2")?.textContent?.trim() || location.origin + "/";
  navigator.clipboard?.writeText(u).catch(() => {});
  toast("Address copied");
};
$("#wifiBtn").onclick = async () => {
  const ssid = ($("#ssid").value || "").trim();
  const password = $("#wpass").value || "";
  if (!ssid) return toast("Enter a network name");
  try {
    toast("Connecting to " + ssid + "…");
    const res = await control("wifi_connect", { ssid, password });
    $("#wpass").value = "";
    toast(res.online ? "Online via WiFi" : "WiFi profile saved — waiting for uplink");
    await refreshStatus();
  } catch (e) { $("#wpass").value = ""; toast(e.message); }
};

async function refreshStatus() {
  // A refresh must not paint Loading until this browser is paired.
  if (!browserPaired) return;
  const ep = vaultEpoch;
  const vaultFresh = () => ep === vaultEpoch && !vaultBusy();
  try {
    const r = await fetch("/api/health", { cache: "no-store" });
    if (!r.ok && r.status !== 503) throw new Error("health " + r.status);
    const j = await r.json();
    if (j.pair?.local || detectLocalHost()) isLocalMode = true;
    // Before anything else that can throw — F9 must follow a browser New code.
    announceRemintFromConnect(j.connect);
    // Vault is highlighted only while the vault is unlocked (a locked vault
    // with a stale "vault" session mode shows Ephemeral).
    if (j.session_mode && vaultFresh()) {
      const vOpen = j.vault ? vaultIsOpen(j.vault) : state.vaultOpen;
      applyModeUi(j.session_mode === "vault" && vOpen ? "vault" : "ephemeral");
    }
    const modelPath = String(j.connect?.model_path || "").trim();
    const named = friendlyModelLabel(j.connect?.model, modelPath);
    const visionNow = !!j.connect?.vision;
    if (visionNow !== modelVision) {
      modelVision = visionNow;
      if (!modelVision) state.attach = state.attach.filter((a) => a.kind === "file");
      renderAttach();
      syncAttach();
    }
    const backend = String(j.backend || j.connect?.backend || "").toUpperCase() || "—";
    if (loadingModelId && !j.llama_ok) loadSawNotOk = true;
    if (loadingModelId) {
      const label = requestedLoadName();
      if ($("#runName")) $("#runName").textContent = label;
      if (loadFinishedWrong(j)) {
        showLoadMismatch(runningModelLabel(j));
      } else if (loadFinishedOk(j)) {
        finishLoadSuccess(label);
      } else {
        if (!loadStartedAt) {
          loadStartedAt = Date.now();
          const m = findModel(loadingModelId);
          loadSizeGb = m ? modelSizeGb(m) : guessSizeGb(label);
        }
        const view = llamaView(j);
        const runPath = String(j.connect?.running_model || "").trim();
        const wantPath = requestedLoadPath();
        const progressTrust = !!(runPath && wantPath && sameModelPath(runPath, wantPath));
        if (view.crashed || view.giveUp) {
          setChipLoad(true, 0, label, phaseForRequestedLoad(view, j), true);
          showFewerLayers(view.giveUp);
        } else {
          showFewerLayers(false);
          const pct = progressTrust && view.alive ? view.pct : 1;
          setChipLoad(true, pct, label, phaseForRequestedLoad(view, j), false);
        }
        if ($("#popModel")) {
          $("#popModel").textContent = `loading — ${label}`;
          $("#popModel").title = wantPath || "";
        }
        if (!loadPollTimer) startLoadPoll();
      }
    } else if (loadMismatchText) {
      if ($("#chipModel")) $("#chipModel").textContent = "Load failed";
      if ($("#runName")) $("#runName").textContent = "Load failed";
      setChipLoad(true, 0, "", loadMismatchText, true);
    } else if (j.llama_ok) {
      stopLoadPoll();
      const readyName = named || "ready";
      $("#chipModel").textContent = readyName;
      setChipLoad(false, 100, readyName);
    } else if (named && named !== "none" && llamaUnitBusy(j)) {
      // Reload while this unit is actually starting. A saved model name is not a load.
      if (!loadStartedAt) {
        loadStartedAt = Date.now();
        loadSizeGb = guessSizeGb(named);
      }
      if (!loadPollTimer) {
        const view = llamaView(j);
        setChipLoad(true, view.crashed ? 0 : (view.pct || 1), named, loadPhaseText(view), view.crashed || view.giveUp);
        showFewerLayers(view.giveUp);
        startLoadPoll();
      }
    } else {
      stopLoadPoll();
      $("#chipModel").textContent = "none";
      setChipLoad(false, 0, null);
    }
    $("#chipMeta").textContent = modelVision && j.llama_ok ? backend + " · vision" : backend;
    $("#statusChip .dot")?.classList.toggle("ok", !loadingModelId && !loadMismatchText && !!j.llama_ok);
    $("#statusChip .dot")?.classList.toggle("busy", !!loadingModelId);
    if ($("#popModel")) {
      const pop = $("#popModel");
      if (loadingModelId) {
        pop.textContent = `loading — ${requestedLoadName()}`;
        pop.title = requestedLoadPath() || "";
      } else if (loadMismatchText) {
        pop.textContent = loadMismatchText;
        pop.title = "";
      } else if (j.llama_ok) {
        pop.textContent = named || "ready";
        pop.title = modelPath || named || "";
      } else if (named && named !== "none" && llamaUnitBusy(j)) {
        pop.textContent = `loading — ${named}`;
        pop.title = modelPath || "";
      } else if (named && named !== "none") {
        pop.textContent = `${named} — not running`;
        pop.title = modelPath || "";
      } else {
        pop.textContent = "none — Activate in Models";
        pop.removeAttribute("title");
      }
    }
    if ($("#popBackend")) $("#popBackend").textContent = backend;
    if ($("#popUplink")) $("#popUplink").textContent = (j.online || j.web) ? "Online" : "No uplink";
    if ($("#popCtx")) {
      const ctx = Number(j.connect?.ctx_size || j.ctx_size || j.loaded?.ctx_size || 0);
      if (ctx > 0) loadedCtx = ctx;
      $("#popCtx").textContent = loadedCtx > 0 ? `${loadedCtx.toLocaleString()} tokens` : "—";
      if (lastPerf) updatePerfStrip(lastPerf);
    }
    const url = j.connect?.url || (j.connect?.ip ? `http://${j.connect.ip}/` : location.origin + "/");
    if ($("#lanUrl2")) $("#lanUrl2").textContent = url;
    const code = j.connect?.pair_code;
    if (detectLocalHost() && $("#pairCodeShow")) {
      const digits = paintF9PairCode(j.connect);
      if (!digits) {
        const c = String(code || "");
        const shown = String($("#pairCodeShow").textContent || "").replace(/\s/g, "");
        if (c && !/^\d{4,8}$/.test(shown)) $("#pairCodeShow").textContent = c;
      }
    } else if ($("#pairCodeShow")) {
      const shown = String($("#pairCodeShow").textContent || "").replace(/\s/g, "");
      if (!/^\d{4,8}$/.test(shown)) $("#pairCodeShow").textContent = "(see stick screen)";
    }
    try {
      const m = await fetch("/stickllm.json", { cache: "no-store" });
      if (m.ok) {
        const meta = await m.json();
        if (meta.version && $("#aboutVer")) $("#aboutVer").textContent = "StickLLM v" + String(meta.version).replace(/^v/, "");
        const boot = String(meta.mode || "").toLowerCase();
        if (boot === "local" || boot === "chat") isLocalMode = true;
      }
    } catch (_) {}
    // vault chrome from health if present
    if (j.vault && vaultFresh()) setVaultChrome(vaultIsOpen(j.vault), vaultIsAbsent(j.vault));
    healthFails = 0;
  } catch (e) {
    healthFails += 1;
    $("#chipModel").textContent = healthFails >= 3 ? "stick not answering" : "waiting…";
    if (loadingModelId && healthFails >= 3) {
      setLoadStatusLine(true, 1, requestedLoadName(), `Can't reach the stick (${(e && e.message) || "no answer"}) — retrying…`, false);
    }
  }
}

// Capture phase so F9/F10 still fire from Settings, Models, or the chat box.
window.addEventListener("keydown", (e) => {
  if (e.key !== "F9" && e.key !== "F10") return;
  e.preventDefault();
  e.stopPropagation();
  // Holding the key auto-repeats: one press, one pair code or SSH line.
  if (e.repeat) return;
  if (e.key === "F9") issuePairHotkey();
  else issueSshHotkey();
}, true);
window.addEventListener("keydown", (e) => {
  const k = e.key.toLowerCase();
  if (e.key === "F9" || e.key === "F10") return;
  if (e.ctrlKey && e.shiftKey && k === "l") { e.preventDefault(); lockVault(); }
  else if (e.ctrlKey && e.shiftKey && k === "o") { e.preventDefault(); newChat(); }
  else if (e.ctrlKey && k === "b") { e.preventDefault(); toggleNav(); }
  else if (e.ctrlKey && k === ",") { e.preventDefault(); openSettings(); }
  else if (e.key === "Escape") {
    if ($("#ablAck") && !$("#ablAck").hidden) $("#ablAck").hidden = true;
    else if (!$("#confirm").hidden) $("#confirm").hidden = true;
    else if (!$("#picker").hidden) $("#picker").hidden = true;
    else if (!$("#settings").hidden) closeSettings();
    else if (!$("#statusPop").hidden) $("#statusPop").hidden = true;
    else if ($("#appsMenu") && !$("#appsMenu").hidden) toggleAppsMenu(false);
    else if (app.classList.contains("navOpen")) toggleNav(false);
  }
});

// Coming-soon stubs (MAP: Tor / offline / revoke / export / attach / mic / HF live search)
["#offline", "#exportAll", "#deleteAll", "#revokeAll", "#checkUpd"].forEach((sel) => {
  const el = $(sel); if (!el) return;
  el.onclick = (e) => { e.preventDefault(); toast("Coming soon"); };
  if ("onchange" in el) el.onchange = (e) => { e.preventDefault(); el.checked = false; toast("Coming soon"); };
});
$$("#backendSeg button").forEach((b) => {
  b.disabled = true;
  b.onclick = (e) => { e.preventDefault(); toast("Coming soon — backend is auto-selected"); };
});
// Advanced: KV type goes to llama-server on the next Load; sampling goes with every Chat message.
$$("#kvSeg button").forEach((b) => (b.onclick = () => {
  setKv(b.dataset.kv || "f16");
  syncPresetHighlight(); saveTune();
  renderModelsList();
}));
["#temp", "#topp", "#topk", "#rep", "#maxtok"].forEach((sel) => {
  const el = $(sel); if (!el) return;
  el.addEventListener("input", () => {
    if (sel === "#temp" && $("#tempVal")) $("#tempVal").textContent = el.value;
    if (sel === "#topp" && $("#toppVal")) $("#toppVal").textContent = el.value;
    syncPresetHighlight(); saveTune();
  });
});
if ($("#resetPreset")) {
  $("#resetPreset").onclick = () => {
    const hit = syncPresetHighlight() || "balanced";
    applyTune({ ctx: TUNE_PRESETS[hit].ctx, kv: TUNE_PRESETS[hit].kv, temp: TUNE_PRESETS[hit].temp, top_p: 0.9, top_k: 40, repeat_penalty: 1.1, max_tokens: CHAT_TOKENS });
    saveTune(); renderModelsList();
    toast("Reset to preset");
  };
}
try { applyTune(JSON.parse(localStorage.getItem(TUNE_KEY) || "null")); } catch (_) { syncPresetHighlight(); }
let modelVision = false;
function syncAttach() {
  const btn = $("#attachBtn");
  if (!btn) return;
  btn.disabled = false;
  btn.title = modelVision
    ? "Attach a file or image, or paste an image into the message box"
    : "Attach a file. It is converted to text for this model. Images need a vision model.";
  btn.setAttribute("aria-label", "Attach a file");
  const inp = $("#input");
  if (inp) inp.placeholder = modelVision ? "Message StickLLM — paste an image" : "Message StickLLM — attach a file";
}
function renderAttach() {
  const box = $("#attachments");
  if (!box) return;
  box.hidden = !state.attach.length;
  const sizeOf = (n) => {
    const v = Number(n) || 0;
    if (v >= 1024 * 1024) return (v / (1024 * 1024)).toFixed(1) + " MB";
    if (v >= 1024) return Math.round(v / 1024) + " KB";
    return v ? v + " B" : "";
  };
  box.innerHTML = state.attach.map((a, i) => {
    if (a.kind === "file") {
      const nImg = (a.images || []).length;
      const bits = [
        a.type || "file",
        a.pages ? a.pages + " pages" : "",
        nImg ? nImg + (nImg === 1 ? " page image" : " page images") : "",
        sizeOf(a.size),
        a.status || "",
      ].filter(Boolean);
      const view = a.plain ? `<button type="button" class="link attView" data-av="${i}">${a.open ? "Hide text" : "View extracted text"}</button>` : "";
      const thumbs = (a.images || []).map((im) => `<img class="thumb" alt="" src="${esc(im.dataUrl)}">`).join("");
      const pre = a.open ? `<pre class="attText">${esc(a.plain || "")}</pre>` : "";
      return `<span class="att file ${esc(a.status || "")}"><span class="attIc">${esc((a.type || "file").slice(0, 4))}</span><span class="attTx"><b>${esc(a.name || "file")}</b><small>${esc(bits.join(" · "))}</small>${view}</span><button type="button" class="attX" data-ax="${i}" aria-label="Remove">×</button>${thumbs}${pre}</span>`;
    }
    return `<span class="att"><img class="thumb" alt="" src="${esc(a.dataUrl)}"><span class="attTx"><b>${esc(a.name || "image")}</b><small>image${a.size ? " · " + sizeOf(a.size) : ""}</small></span><button type="button" class="attX" data-ax="${i}" aria-label="Remove">×</button></span>`;
  }).join("");
  $$("[data-ax]", box).forEach((b) => (b.onclick = () => {
    state.attach.splice(+b.dataset.ax, 1);
    renderAttach();
  }));
  $$("[data-av]", box).forEach((b) => (b.onclick = () => {
    const item = state.attach[+b.dataset.av];
    if (item) item.open = !item.open;
    renderAttach();
  }));
}
const IMAGE_URL_MAX = 70000;
const PHOTO_MAX = 3;
const PAGE_IMAGE_MAX = 8;
function jpegUnder(canvas, limit) {
  let q = 0.82;
  let url = canvas.toDataURL("image/jpeg", q);
  while (url.length > limit && q > 0.42) {
    q = Math.round((q - 0.12) * 100) / 100;
    url = canvas.toDataURL("image/jpeg", q);
  }
  return url;
}
function drawFitted(source, sw, sh, maxEdge) {
  const edge = Math.max(sw, sh) || 1;
  const scale = Math.min(1, maxEdge / edge);
  const w = Math.max(1, Math.round(sw * scale));
  const h = Math.max(1, Math.round(sh * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d").drawImage(source, 0, 0, w, h);
  const url = jpegUnder(canvas, IMAGE_URL_MAX);
  if (url.length > IMAGE_URL_MAX && maxEdge > 480) return drawFitted(source, sw, sh, Math.round(maxEdge * 0.75));
  return url;
}
function shrinkImage(file) {
  // Decode the file itself. blob: URLs are blocked by the page policy, so
  // new Image() + createObjectURL failed for every picture.
  return createImageBitmap(file).then((bitmap) => {
    const url = drawFitted(bitmap, bitmap.width, bitmap.height, 1024);
    bitmap.close?.();
    if (!url || url.length > 90000) throw new Error("Could not read that image");
    return { name: file.name || "image", dataUrl: url };
  }).catch(() => {
    throw new Error("Could not read that image");
  });
}
function shrinkDataUrl(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      try {
        const url = drawFitted(img, img.naturalWidth || img.width, img.naturalHeight || img.height, 1024);
        if (!url || !url.startsWith("data:image/") || url.length > 90000) reject(new Error("Page image is too large"));
        else resolve(url);
      } catch (e) {
        reject(e);
      }
    };
    img.onerror = () => reject(new Error("Could not read that page image"));
    img.src = dataUrl;
  });
}
function pageDataUrl(im) {
  if (!im || !im.data_base64) return "";
  const mime = String(im.mime || "image/jpeg").toLowerCase();
  if (!/^image\/(jpeg|jpg|png|webp)$/.test(mime)) return "";
  const b64 = String(im.data_base64);
  if (!/^[A-Za-z0-9+/=]+$/.test(b64)) return "";
  return `data:${mime === "image/jpg" ? "image/jpeg" : mime};base64,${b64}`;
}
function imageFileOk(file) {
  return /^image\/(jpeg|png|webp|gif)$/.test(file?.type || "");
}
const ATTACH_MAX_FILES = 10;
const ATTACH_MAX_BYTES = 50 * 1024 * 1024;
async function sniffImage(file) {
  if (imageFileOk(file)) return true;
  try {
    const buf = new Uint8Array(await file.slice(0, 16).arrayBuffer());
    if (buf[0] === 0xff && buf[1] === 0xd8) return true;
    if (buf[0] === 0x89 && buf[1] === 0x50) return true;
    if (buf[0] === 0x47 && buf[1] === 0x49) return true;
    if (buf[0] === 0x52 && buf[1] === 0x49 && buf[8] === 0x57) return true;
  } catch (_) {}
  return false;
}
async function convertDocFile(chip, file) {
  try {
    const data = new Uint8Array(await file.arrayBuffer());
    let bin = "";
    const chunk = 0x2000;
    for (let i = 0; i < data.length; i += chunk) {
      bin += String.fromCharCode(...data.subarray(i, i + chunk));
    }
    const r = await fetch("/api/attachments/convert", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        name: file.name || "file",
        chat_id: state.current?.id ? String(state.current.id) : "",
        vision: !!modelVision,
        data_base64: btoa(bin),
      }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || j.message || "Could not read that file");
    chip.type = j.type || "";
    chip.pages = j.pages || 0;
    chip.status = j.truncated ? "truncated" : "ready";
    chip.text = j.text || "";
    chip.plain = j.plain || "";
    chip.truncated = !!j.truncated;
    const incoming = modelVision ? (j.images || []).slice(0, PAGE_IMAGE_MAX) : [];
    const images = [];
    for (const im of incoming) {
      const direct = pageDataUrl(im);
      if (!direct) continue;
      if (direct.length <= 90000) {
        images.push({ dataUrl: direct });
        continue;
      }
      try {
        images.push({ dataUrl: await shrinkDataUrl(direct) });
      } catch (_) {}
    }
    chip.images = images;
    chip.status = j.truncated ? "truncated" : "ready";
    if (j.warning) toast(j.warning);
  } catch (e) {
    chip.status = "failed";
    chip.error = e.message;
    toast(e.message);
  }
  renderAttach();
}
async function addAnyFiles(list) {
  const incoming = [...list];
  const room = ATTACH_MAX_FILES - state.attach.length;
  if (room <= 0) {
    toast("10 files per message.");
    return 0;
  }
  if (incoming.length > room) toast("10 files per message. Extra files were skipped.");
  let added = 0;
  for (const file of incoming.slice(0, room)) {
    if (file.size > ATTACH_MAX_BYTES) {
      toast(`${file.name || "File"} is over the 50 MB limit.`);
      continue;
    }
    if (await sniffImage(file)) {
      if (!modelVision) {
        toast("This model cannot see images. Other files are still converted to text.");
        continue;
      }
      if (state.attach.filter((a) => a.kind !== "file").length >= PHOTO_MAX) {
        toast("3 images max");
        continue;
      }
      try {
        const img = await shrinkImage(file);
        state.attach.push({ kind: "image", ...img, size: file.size, status: "ready" });
        added += 1;
        renderAttach();
      } catch (e) { toast(e.message); }
      continue;
    }
    const chip = {
      kind: "file", name: file.name || "file", size: file.size, type: "", pages: 0,
      status: "converting", text: "", plain: "", truncated: false, error: "",
    };
    state.attach.push(chip);
    added += 1;
    renderAttach();
    convertDocFile(chip, file);
  }
  return added;
}
function imageFilesFromClipboard(data) {
  const out = [];
  if (!data) return out;
  // Chrome lists the same picture in items and files. Reading both attached it twice.
  const fromItems = [];
  for (const item of [...(data.items || [])]) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (file) fromItems.push({ file, type: item.type || file.type });
  }
  const raw = fromItems.length
    ? fromItems
    : [...(data.files || [])].map((file) => ({ file, type: file.type }));
  const seen = new Set();
  for (const { file, type } of raw) {
    let next = file;
    if (!imageFileOk(next) && imageFileOk({ type })) {
      next = new File([file], file.name || "pasted.png", { type });
    }
    if (!imageFileOk(next)) continue;
    const key = `${next.type}|${next.size}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(next);
  }
  return out;
}
if ($("#attachBtn") && $("#attachPick")) {
  syncAttach();
  $("#attachBtn").onclick = () => { $("#attachPick").click(); };
  $("#attachPick").onchange = async () => {
    const files = [...($("#attachPick").files || [])];
    $("#attachPick").value = "";
    await addAnyFiles(files);
  };
  const composer = $("#composer");
  if (composer) {
    composer.addEventListener("dragover", (e) => { e.preventDefault(); composer.classList.add("drop"); });
    composer.addEventListener("dragleave", () => composer.classList.remove("drop"));
    composer.addEventListener("drop", (e) => {
      e.preventDefault();
      composer.classList.remove("drop");
      const files = [...(e.dataTransfer?.files || [])];
      if (files.length) addAnyFiles(files);
    });
  }
  $("#input")?.addEventListener("paste", async (e) => {
    const images = imageFilesFromClipboard(e.clipboardData);
    if (images.length) {
      e.preventDefault();
      const n = await addAnyFiles(images);
      if (n === 1) toast("Image pasted");
      return;
    }
    const files = [];
    const seen = new Set();
    for (const f of [...(e.clipboardData?.files || [])]) {
      const key = `${f.name}|${f.size}|${f.type}`;
      if (seen.has(key)) continue;
      seen.add(key);
      files.push(f);
    }
    if (!files.length) return;
    e.preventDefault();
    await addAnyFiles(files);
  });
}
let micState = "idle";
let micChunks = [];
let micStream = null;
let micCtx = null;
let micSource = null;
let micTimer = null;
let micAbort = null;
let micRec = null;
let micRecMime = "";
let micAnalyser = null;
let micVadTimer = null;
let micStarting = false;
let micStopWanted = false;
let micGen = 0;
let micEpoch = 0;
let finishPromise = null;
let sendFromMic = false;
let speakAudio = null;
let speakIndex = -1;
let speakAbort = null;
let speakAborts = new Set();
let speakAhead = null;
let micNode = null;
let voicePowerBusy = false;
let speakToken = 0;
let speakQ = [];
let speakPumping = false;
let speakHalted = false;
let speakDone = null;
let speechSeen = "";
let speechHold = "";
let composerFromMic = false;
const VOICE_SILENCE_MS = 1000;
const VOICE_MIN_SPEECH_MS = 400;
// Quiet on purpose. Remote Desktop mics are often well below a normal laptop mic.
const VOICE_SPEECH_RMS = 0.006;
let voiceMode = false;
let voiceMuted = false;
let voiceHold = false;
let voiceHeard = false;
let voiceSpeechMs = 0;
let voiceQuietMs = 0;

function setMicNote(_text) {
  // Status copy under the composer changes its height. Leave the line blank.
  const note = $("#composerNote");
  if (!note) return;
  note.textContent = "";
  note.classList.remove("is-error");
}
function sentLabel(n) {
  const bytes = Number(n) || 0;
  if (bytes >= 1000) return "Sent " + Math.round(bytes / 1000) + " KB.";
  return "Sent " + bytes + " B.";
}
function showComposerLine(text, isError) {
  const note = $("#composerNote");
  if (!note) return;
  note.textContent = text || "";
  note.classList.toggle("is-error", !!isError);
}
function speechFail(msg) {
  const text = String(msg || "Speech recognition failed.").trim();
  const note = $("#composerNote");
  if (note) {
    note.textContent = text;
    note.classList.add("is-error");
  }
  const btn = $("#micBtn");
  if (btn) {
    btn.disabled = false;
    if (micState !== "recording") {
      btn.title = "Voice input";
      btn.setAttribute("aria-label", "Voice input");
    }
  }
}
function setMicUi(state) {
  micState = state;
  const btn = $("#micBtn");
  if (!btn) return;
  const recording = state === "recording";
  const busy = state === "transcribing";
  btn.classList.toggle("recording", recording);
  btn.classList.toggle("busy", busy);
  btn.disabled = false;
  btn.setAttribute("aria-pressed", recording ? "true" : "false");
  btn.setAttribute("aria-busy", busy ? "true" : "false");
  const title = recording ? (voiceMode ? "Listening" : "Recording… click to transcribe") : busy ? "Transcribing…" : "Voice input";
  btn.title = title;
  btn.setAttribute("aria-label", title);
}
function releaseMic() {
  if (micTimer) clearTimeout(micTimer);
  micTimer = null;
  if (micVadTimer) clearInterval(micVadTimer);
  micVadTimer = null;
  try { if (micSource) micSource.disconnect(); } catch (_) {}
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close().catch(() => {});
  micAnalyser = null;
  micSource = null;
  micStream = null;
  micCtx = null;
  micRec = null;
}
function cancelMic() {
  micEpoch++;
  micGen++;
  if (micAbort) micAbort.abort();
  micAbort = null;
  micChunks = [];
  const rec = micRec;
  micRec = null;
  try { if (rec && rec.state !== "inactive") rec.stop(); } catch (_) {}
  releaseMic();
  setMicUi("idle");
}
function bytesToBase64(bytes) {
  let bin = "";
  const step = 8192;
  for (let i = 0; i < bytes.length; i += step) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(bytes.length, i + step)));
  }
  return btoa(bin);
}
function micHallucination(text) {
  const n = String(text || "").toLowerCase().replace(/[^a-z\s]/g, " ").replace(/\s+/g, " ").trim();
  return n === "you" || n === "you you" || n === "thank you" || n === "thanks for watching" || n === "thanks for listening";
}
function micHot() {
  const btn = $("#micBtn");
  return micState === "recording" || !!(micRec && micRec.state === "recording") || !!(btn && btn.classList.contains("recording"));
}
function appendTranscript(text, sent) {
  const input = $("#input");
  const add = String(text || "").replace(/\s+/g, " ").trim();
  const prefix = sent ? sent + " " : "";
  if (!add) {
    speechFail(prefix + "No speech detected.");
    return false;
  }
  if (micHallucination(add)) {
    speechFail(prefix + "No speech detected.");
    return false;
  }
  const cur = input.value;
  input.value = !cur || composerFromMic ? add : (/\s$/.test(cur) ? cur + add : cur + " " + add);
  composerFromMic = true;
  autosize();
  input.focus();
  return true;
}
function pickRecMime() {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return "";
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  for (const t of types) {
    try { if (MediaRecorder.isTypeSupported(t)) return t; } catch (_) {}
  }
  return "";
}
function recorderLive(rec) {
  const cur = rec || micRec;
  return !!(cur && cur.state && cur.state !== "inactive");
}
function haltRecorder(rec) {
  const target = rec || micRec;
  if (!target || !target.state || target.state === "inactive") {
    if (micRec === target) micRec = null;
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      // dataavailable is specified to run before stop. Wait one turn in case
      // this browser fires stop first, so the last chunk is in the part list.
      setTimeout(resolve, 0);
    };
    target.addEventListener("stop", done, { once: true });
    target.addEventListener("error", done, { once: true });
    try { target.stop(); } catch (_) { done(); }
    setTimeout(done, 2000);
  }).finally(() => { if (micRec === target) micRec = null; });
}
function startVad(stream) {
  if (!voiceMode) return;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    // The meter has to reach the destination or Chrome reports silence.
    // Gain stays at 0 so the microphone is not played back.
    const tap = ctx.createGain();
    tap.gain.value = 0;
    analyser.connect(tap);
    tap.connect(ctx.destination);
    micCtx = ctx;
    micSource = source;
    micAnalyser = analyser;
    const buf = new Float32Array(analyser.fftSize);
    ctx.resume().catch(() => {});
    micVadTimer = setInterval(() => {
      if (micState !== "recording" || !voiceMode || !micAnalyser) return;
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      micAnalyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      if (rms >= VOICE_SPEECH_RMS) {
        voiceHeard = true;
        voiceSpeechMs += 100;
        voiceQuietMs = 0;
      } else if (voiceSpeechMs >= VOICE_MIN_SPEECH_MS) {
        voiceQuietMs += 100;
        if (voiceQuietMs >= VOICE_SILENCE_MS) finishMic();
      } else if (voiceHeard) {
        voiceQuietMs += 100;
        if (voiceQuietMs >= VOICE_SILENCE_MS) {
          voiceHeard = false;
          voiceSpeechMs = 0;
          voiceQuietMs = 0;
        }
      }
    }, 100);
  } catch (_) {}
}
function finishMic(reason) {
  if (finishPromise) {
    if (recorderLive()) {
      try { micRec.stop(); } catch (_) {}
    }
    return finishPromise;
  }
  if (!micHot() && !recorderLive()) return Promise.resolve();
  if (micTimer) clearTimeout(micTimer);
  micTimer = null;
  if (micVadTimer) clearInterval(micVadTimer);
  micVadTimer = null;
  micState = "transcribing";
  const parts = micChunks;
  const rec = micRec;
  const mime = micRecMime;
  finishPromise = finishMicBody(reason, parts, rec, mime).finally(() => {
    finishPromise = null;
  });
  return finishPromise;
}
async function finishMicBody(reason, parts, rec, mime) {
  const stop = reason === "stop";
  setMicUi("transcribing");
  await haltRecorder(rec);
  releaseMic();
  // Chrome records audio/webm;codecs=opus. The stick decodes that to 16 kHz WAV.
  // decodeAudioData drops or rejects these blobs, so the container is what we post.
  const blob = new Blob(parts || [], { type: mime || "audio/webm" });
  let raw = new Uint8Array(0);
  try {
    raw = new Uint8Array(await blob.arrayBuffer());
  } catch (_) {
    raw = new Uint8Array(0);
  }
  if (!parts || !parts.length || !raw.length) {
    setMicUi("idle");
    if (stop || !voiceMode) speechFail("The recording was empty");
    if (!stop && voiceMode) resumeVoiceListen();
    return;
  }
  const sent = sentLabel(raw.length);
  showComposerLine(sent, false);
  const postedMime = mime || blob.type || "audio/webm";
  const ctrl = new AbortController();
  micAbort = ctrl;
  let handed = false;
  try {
    const r = await fetch("/api/speech/transcribe", {
      method: "POST",
      signal: ctrl.signal,
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ audio_base64: bytesToBase64(raw), mime: postedMime }),
    });
    const j = await r.json().catch(() => ({}));
    if (ctrl.signal.aborted) return;
    if (r.status === 401) {
      pairLost();
      speechFail(sent + " Pair this browser using the code on the stick screen.");
      return;
    }
    if (!r.ok || !j.ok) {
      const msg = j.message || j.error || "Speech recognition failed.";
      speechFail(sent + " " + msg);
      return;
    }
    showComposerLine(sent, false);
    const heard = appendTranscript(j.text || "", sent);
    // Stop, or a finished voice-mode phrase, sends the transcript.
    // Empty audio and the "you" hallucination never get here.
    if (heard && (stop || voiceMode) && !sendBusy && !sendFlight) {
      const said = ($("#input").value || "").trim();
      if (said && !micHallucination(said)) {
        handed = true;
        sendFromMic = true;
        try { await send(); }
        finally { sendFromMic = false; }
        return;
      }
    }
  } catch (e) {
    if (e && e.name === "AbortError") return;
    speechFail(sent + " Speech recognition failed.");
  } finally {
    micAbort = null;
    if (micState === "transcribing") setMicUi("idle");
    if (!handed && !stop && voiceMode && !sendBusy && !voiceHold && !speakAudio) resumeVoiceListen();
  }
}
function secureMicMessage() {
  const shown = ($("#lanUrl2") && $("#lanUrl2").textContent || "").trim();
  if (/^https:\/\//i.test(shown)) return "Open " + shown + " in this browser to use the microphone.";
  return "Open this page with https to use the microphone.";
}
function abandonReplyForMic() {
  userStopGen = sendGen;
  if (sendAbort) {
    try { sendAbort.abort(); } catch (_) {}
  }
  requestChatStop();
  stopSpeak();
}
async function startMic() {
  if (!voiceMode) return;
  if (micStopWanted) return;
  if (recorderLive() || micHot()) {
    finishMic("stop");
    return;
  }
  if (micStarting || micState !== "idle") return;
  const btn = $("#micBtn");
  if (btn) btn.disabled = false;
  if (typeof MediaRecorder === "undefined") {
    speechFail("This browser cannot record audio.");
    setMicUi("idle");
    return;
  }
  micStarting = true;
  const gen = ++micGen;
  let stream = null;
  try {
    if (!(await ensurePaired())) {
      speechFail("Pair this browser before using the microphone.");
      setMicUi("idle");
      return;
    }
    if (gen !== micGen || micStopWanted) return;
    if (!window.isSecureContext) {
      speechFail(secureMicMessage());
      setMicUi("idle");
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      speechFail("This browser cannot use the microphone.");
      setMicUi("idle");
      return;
    }
    const micAudio = {
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    };
    const virtualMic = (label) => /cable|vb-audio|virtual|stereo mix|loopback|wave out|what u hear/i.test(String(label || ""));
    const realMicId = async () => {
      try {
        const list = await navigator.mediaDevices.enumerateDevices();
        const mics = list.filter((d) => d.kind === "audioinput" && d.deviceId && d.label && !virtualMic(d.label));
        const named = mics.find((d) => /microphone|headset|\bmic\b|usb/i.test(d.label));
        return (named || mics[0] || {}).deviceId || "";
      } catch (_) {
        return "";
      }
    };
    try {
      const preferId = await realMicId();
      const withId = preferId ? Object.assign({ deviceId: { exact: preferId } }, micAudio) : micAudio;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: withId });
      } catch (err) {
        const name = err && err.name;
        if (name !== "OverconstrainedError" && name !== "NotSupportedError" && name !== "ConstraintNotSatisfiedError") throw err;
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
      const opened = stream.getAudioTracks()[0];
      if (opened && virtualMic(opened.label)) {
        const id = await realMicId();
        if (id) {
          try {
            const next = await navigator.mediaDevices.getUserMedia({
              audio: Object.assign({ deviceId: { exact: id } }, micAudio),
            });
            stream.getTracks().forEach((t) => t.stop());
            stream = next;
          } catch (_) {}
        }
      }
    } catch (e) {
      const name = e && e.name;
      if (name === "NotFoundError" || name === "DevicesNotFoundError") speechFail("No microphone was found.");
      else if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") speechFail("Microphone permission was denied.");
      else speechFail("Could not use the microphone.");
      setMicUi("idle");
      return;
    }
    if (gen !== micGen || micStopWanted || micState !== "idle") {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
      return;
    }
    const mime = pickRecMime();
    let rec;
    try {
      rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    } catch (_) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
      speechFail("This browser cannot record audio.");
      setMicUi("idle");
      return;
    }
    const parts = [];
    micChunks = parts;
    voiceHeard = false;
    voiceSpeechMs = 0;
    voiceQuietMs = 0;
    micStream = stream;
    micRec = rec;
    micRecMime = rec.mimeType || mime || "";
    rec.ondataavailable = (ev) => {
      if (!ev.data || !ev.data.size) return;
      parts.push(ev.data);
    };
    try {
      rec.start(250);
    } catch (_) {
      try { rec.start(); } catch (_) {
        stream.getTracks().forEach((t) => t.stop());
        micRec = null;
        micStream = null;
        stream = null;
        speechFail("This browser cannot record audio.");
        setMicUi("idle");
        return;
      }
    }
    if (micStopWanted || gen !== micGen) {
      if (recorderLive(rec)) {
        stream = null;
        finishMic("stop");
        return;
      }
      try { rec.stop(); } catch (_) {}
      micRec = null;
      stream = micStream;
      micStream = null;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      stream = null;
      setMicUi("idle");
      return;
    }
    stream = null;
    startVad(micStream);
    setMicUi("recording");
    const armTimer = () => {
      micTimer = setTimeout(() => {
        if (micState !== "recording") return;
        if (voiceMode) {
          if (voiceSpeechMs >= VOICE_MIN_SPEECH_MS) finishMic();
          else armTimer();
        } else finishMic("stop");
      }, 60000);
    };
    armTimer();
  } catch (_) {
    speechFail("Could not use the microphone.");
    releaseMic();
    setMicUi("idle");
  } finally {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    micStarting = false;
    const btn = $("#micBtn");
    if (btn) btn.disabled = false;
  }
}
function toggleMic() {
  if (!voiceMode) return;
  const btn = $("#micBtn");
  if (btn) btn.disabled = false;
  unlockSpeech();
  if (recorderLive() || micHot()) {
    micStopWanted = true;
    finishMic("stop");
    return;
  }
  if (finishPromise || micState === "transcribing") return;
  if (micStarting) return;
  setMicNote("");
  micStopWanted = false;
  cancelMic();
  micStarting = false;
  micStopWanted = false;
  if (btn) btn.disabled = false;
  abandonReplyForMic();
  startMic();
}
function resumeVoiceListen() {
  // Voice on shows the mic. Recording starts only on the next press.
  if (!voiceMode || voiceMuted || voiceHold || sendBusy || speakAudio || speakQ.length || speakPumping) return;
  if (micState !== "idle") return;
}
function setVoiceMute(on) {
  voiceMuted = !!on;
  const btn = $("#voiceMuteBtn");
  if (btn) {
    btn.classList.toggle("muted", voiceMuted);
    btn.setAttribute("aria-pressed", voiceMuted ? "true" : "false");
    btn.title = voiceMuted ? "Unmute the microphone" : "Mute the microphone";
    btn.setAttribute("aria-label", btn.title);
  }
  if (voiceMuted) {
    if (micState === "recording" || micState === "transcribing") cancelMic();
    setMicNote("Microphone muted. Voice mode stays on.");
    return;
  }
  resumeVoiceListen();
}
function voiceControls(on) {
  const mic = micNode || (micNode = document.getElementById("micBtn"));
  const stopSpeech = $("#stopSpeechBtn");
  const btn = $("#voiceModeBtn");
  if (mic) {
    if (!on) {
      if (mic.parentNode) {
        mic._home = mic.parentNode;
        mic._next = mic.nextSibling;
        mic.remove();
      }
    } else if (!mic.isConnected && mic._home) {
      mic.hidden = false;
      mic._home.insertBefore(mic, mic._next || null);
    } else {
      mic.hidden = false;
    }
  }
  if (stopSpeech) stopSpeech.hidden = !on;
  if (btn) {
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "Voice on" : "Voice off";
  }
}
async function setVoiceMode(on) {
  if (voicePowerBusy) return;
  on = !!on;
  if (on && !window.isSecureContext) {
    speechFail(secureMicMessage());
    return;
  }
  voicePowerBusy = true;
  voiceMode = on;
  voiceControls(on);
  if (!on) {
    voiceMuted = false;
    voiceHold = false;
    voiceHeard = false;
    voiceSpeechMs = 0;
    const mute = $("#voiceMuteBtn");
    if (mute) mute.classList.remove("muted");
    cancelMic();
    stopSpeak();
    setMicNote("");
  }
  if (typeof renderThread === "function") renderThread({ keepSpeech: true });
  try {
    const r = await fetch("/api/speech/power", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ on: on }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok || !!j.on !== on) {
      voiceMode = false;
      voiceControls(false);
      cancelMic();
      stopSpeak();
      if (typeof renderThread === "function") renderThread({ keepSpeech: true });
      toast(j.error || "Could not change voice.");
      return;
    }
  } catch (_) {
    voiceMode = false;
    voiceControls(false);
    cancelMic();
    stopSpeak();
    toast("Could not change voice.");
  } finally {
    voicePowerBusy = false;
  }
}
async function loadVoicePower() {
  voiceMode = false;
  voiceControls(false);
  try {
    const r = await fetch("/api/speech/power", { headers: authHeaders() });
    const j = await r.json().catch(() => ({}));
    if (r.ok && j.on) await setVoiceMode(true);
  } catch (_) {}
}
async function speakVoiceReply(text) {
  voiceHold = true;
  if (micState !== "idle") cancelMic();
  stopSpeak();
  voiceHold = true;
  const mine = speakToken;
  const ctrl = new AbortController();
  speakAbort = ctrl;
  const idx = state.current && state.current.msgs ? state.current.msgs.length - 1 : -1;
  try {
    const r = await fetch("/api/speech/speak", {
      method: "POST",
      signal: ctrl.signal,
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text, voice: "Bella" }),
    });
    const j = await r.json().catch(() => ({}));
    if (mine !== speakToken || !voiceMode) return;
    if (r.status === 401) {
      pairLost();
      return;
    }
    if (!r.ok || !j.ok || !j.audio_base64) {
      toast(j.message || j.error || "Could not read the reply aloud.");
      return;
    }
    const raw = atob(j.audio_base64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    const audio = new Audio(url);
    audio._url = url;
    speakAudio = audio;
    speakIndex = idx;
    const btn = idx >= 0 ? document.querySelector(`[data-speak="${idx}"]`) : null;
    if (btn) {
      btn.classList.add("on");
      btn.title = "Stop reading";
      btn.setAttribute("aria-label", "Stop reading");
    }
    if (mine !== speakToken) {
      try { audio.pause(); } catch (_) {}
      if (audio._url) URL.revokeObjectURL(audio._url);
      if (speakAudio === audio) speakAudio = null;
      return;
    }
    setMicNote("Speaking the reply…");
    audio.onended = () => {
      if (speakAudio !== audio) return;
      stopSpeak();
      voiceHold = false;
      resumeVoiceListen();
    };
    await audio.play();
  } catch (e) {
    if (e && e.name === "AbortError") return;
    if (mine !== speakToken) return;
    toast("Could not read the reply aloud.");
  } finally {
    if (mine === speakToken && !speakAudio) {
      voiceHold = false;
      resumeVoiceListen();
    }
  }
}
function newSpeakAbort() {
  const ctrl = new AbortController();
  speakAborts.add(ctrl);
  speakAbort = ctrl;
  return ctrl;
}
function stopCurrentSpeech() {
  speakHalted = true;
  stopSpeak();
  voiceHold = false;
  resumeVoiceListen();
}
function stopSpeak() {
  speakToken++;
  speakQ.length = 0;
  speechSeen = "";
  speechHold = "";
  speakAhead = null;
  speakAborts.forEach((ctrl) => {
    try { ctrl.abort(); } catch (_) {}
  });
  speakAborts.clear();
  if (speakAbort) {
    try { speakAbort.abort(); } catch (_) {}
    speakAbort = null;
  }
  if (speakAudio) {
    try { speakAudio.pause(); } catch (_) {}
    if (speakAudio._url) URL.revokeObjectURL(speakAudio._url);
    speakAudio = null;
  }
  if (speakDone) {
    const done = speakDone;
    speakDone = null;
    done();
  }
  speakIndex = -1;
  $$(".speakBtn.on, .speakBtn.busy").forEach((b) => {
    b.classList.remove("on", "busy");
    b.disabled = false;
    b.title = "Read aloud";
    b.setAttribute("aria-label", "Read aloud");
  });
}
function resetSpeechFeed() {
  speechSeen = "";
  speechHold = "";
}
function speechCut(text) {
  // A sentence is finished when . ! ? or a newline is already in the bubble.
  // Do not wait for another character, or for the rest of the reply.
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "\n") return i + 1;
    if (c !== "." && c !== "!" && c !== "?") continue;
    let j = i + 1;
    while (j < text.length && /["')\]]/.test(text[j])) j++;
    if (j >= text.length || /\s/.test(text[j])) return j;
  }
  return 0;
}
function unlockSpeech() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  try {
    if (!unlockSpeech.ctx) unlockSpeech.ctx = new Ctx();
    const ctx = unlockSpeech.ctx;
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    const buf = ctx.createBuffer(1, 1, 22050);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.start();
  } catch (_) {}
}
function feedSpeech(full) {
  if (!voiceMode || speakHalted) return;
  const text = dropEmptyPlaceholder(stripThink(String(full || "")));
  if (!text.trim() || text.trim() === "(empty response)") return;
  // The answer replaced the thinking text. Keep anything already sent to
  // Kitten, and queue the new sentences behind it. Do not wait for the stream.
  if (!text.startsWith(speechSeen)) resetSpeechFeed();
  speechHold += text.slice(speechSeen.length);
  speechSeen = text;
  while (speechHold) {
    const cut = speechCut(speechHold);
    if (cut <= 0) break;
    const chunk = speechHold.slice(0, cut).trim();
    speechHold = speechHold.slice(cut);
    if (chunk && !micHallucination(chunk)) enqueueSpeak(chunk);
  }
}
function flushSpeech() {
  if (speakHalted) {
    speechHold = "";
    return;
  }
  const chunk = speechHold.trim();
  speechHold = "";
  if (chunk && chunk !== BUDGET_NOTE && !micHallucination(chunk)) enqueueSpeak(chunk);
}
function enqueueSpeak(text) {
  if (speakHalted) return;
  const mine = speakToken;
  speakQ.push({ text, mine });
  if (speakAudio && !speakAhead) kickAhead(mine);
  pumpSpeak();
}
function kickAhead(mine) {
  if (speakAhead || mine !== speakToken || !voiceMode) return;
  let item = null;
  while (speakQ.length) {
    const next = speakQ.shift();
    if (next && next.mine === mine) {
      item = next;
      break;
    }
  }
  if (!item) return;
  const ctrl = newSpeakAbort();
  speakAhead = { mine, ctrl, job: fetchSpeakWav(item.text, mine, ctrl) };
}
async function fetchSpeakWav(text, mine, ctrl) {
  if (mine !== speakToken || !voiceMode) return null;
  if (!text || text.trim() === "(empty response)") return null;
  const speakPromise = fetch("/api/speech/speak", {
    method: "POST",
    signal: ctrl.signal,
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ text, voice: "Bella" }),
  });
  if (!(await ensurePaired())) {
    try { ctrl.abort(); } catch (_) {}
    return null;
  }
  const r = await speakPromise;
  const j = await r.json().catch(() => ({}));
  if (mine !== speakToken || !voiceMode) return null;
  if (!r.ok || !j.ok || !j.audio_base64) return null;
  const raw = atob(j.audio_base64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
}
async function playWavUrl(url, mine) {
  const audio = new Audio(url);
  audio._url = url;
  speakAudio = audio;
  try {
    if (mine !== speakToken) return false;
    await audio.play();
    if (mine !== speakToken) return false;
    // The next sentence synthesizes while this one is still playing.
    kickAhead(mine);
    await new Promise((resolve) => {
      speakDone = resolve;
      const finish = () => {
        if (speakDone === resolve) {
          speakDone = null;
          resolve();
        }
      };
      audio.onended = finish;
      audio.onerror = finish;
    });
    return mine === speakToken;
  } catch (e) {
    if (e && e.name === "AbortError") return false;
    return false;
  } finally {
    if (speakAudio === audio) {
      try { audio.pause(); } catch (_) {}
      if (audio._url) URL.revokeObjectURL(audio._url);
      speakAudio = null;
    }
  }
}
async function pumpSpeak() {
  if (speakPumping) return;
  speakPumping = true;
  const mine = speakToken;
  voiceHold = true;
  try {
    while (mine === speakToken) {
      let job = null;
      if (speakAhead && speakAhead.mine === mine) {
        job = speakAhead.job;
        speakAhead = null;
      } else if (speakQ.length) {
        const item = speakQ.shift();
        if (!item || item.mine !== mine) continue;
        const ctrl = newSpeakAbort();
        job = fetchSpeakWav(item.text, mine, ctrl);
      } else {
        break;
      }
      let url = null;
      try {
        url = await job;
      } catch (_) {
        url = null;
      }
      if (mine !== speakToken) {
        if (url) URL.revokeObjectURL(url);
        break;
      }
      if (!url) continue;
      await playWavUrl(url, mine);
    }
  } finally {
    speakPumping = false;
    if (mine === speakToken && (speakQ.length || (speakAhead && speakAhead.mine === mine))) {
      pumpSpeak();
      return;
    }
    if (mine === speakToken && !speakQ.length && !speakAudio && !speakAhead) {
      voiceHold = false;
      resumeVoiceListen();
    }
  }
}
async function readAloud(btn) {
  const idx = Number(btn.dataset.speak);
  const msg = state.current && state.current.msgs[idx];
  const text = msg && msg.t;
  if (!text || !String(text).trim()) return;
  if (speakIndex === idx && speakAudio) {
    stopSpeak();
    voiceHold = false;
    resumeVoiceListen();
    return;
  }
  stopSpeak();
  if (voiceMode) {
    voiceHold = true;
    if (micState !== "idle") cancelMic();
  }
  if (!(await ensurePaired())) {
    voiceHold = false;
    resumeVoiceListen();
    return;
  }
  btn.classList.add("busy");
  btn.disabled = true;
  btn.title = "Preparing audio…";
  btn.setAttribute("aria-label", "Preparing audio");
  const mine = speakToken;
  const ctrl = new AbortController();
  speakAbort = ctrl;
  try {
    const r = await fetch("/api/speech/speak", {
      method: "POST",
      signal: ctrl.signal,
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text, voice: "Bella" }),
    });
    const j = await r.json().catch(() => ({}));
    if (mine !== speakToken) return;
    if (r.status === 401) {
      pairLost();
      return;
    }
    if (!r.ok || !j.ok || !j.audio_base64) {
      toast(j.message || j.error || "Could not read that aloud.");
      return;
    }
    const raw = atob(j.audio_base64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    const audio = new Audio(url);
    audio._url = url;
    speakAudio = audio;
    speakIndex = idx;
    btn.classList.remove("busy");
    btn.classList.add("on");
    btn.disabled = false;
    btn.title = "Stop reading";
    btn.setAttribute("aria-label", "Stop reading");
    audio.onended = () => {
      if (speakAudio !== audio) return;
      stopSpeak();
      voiceHold = false;
      resumeVoiceListen();
    };
    if (mine !== speakToken) {
      try { audio.pause(); } catch (_) {}
      if (audio._url) URL.revokeObjectURL(audio._url);
      if (speakAudio === audio) speakAudio = null;
      return;
    }
    await audio.play();
  } catch (e) {
    if (e && e.name === "AbortError") return;
    if (mine !== speakToken) return;
    toast("Could not read that aloud.");
    stopSpeak();
    voiceHold = false;
  } finally {
    if (mine === speakToken && !speakAudio) resumeVoiceListen();
    if (!btn.classList.contains("on")) {
      btn.classList.remove("busy");
      btn.disabled = false;
      if (btn.title === "Preparing audio…") {
        btn.title = "Read aloud";
        btn.setAttribute("aria-label", "Read aloud");
      }
    }
  }
}
const micBtn = $("#micBtn");
micNode = micBtn;
if (micBtn) {
  micBtn.disabled = false;
  micBtn.title = "Voice input";
  micBtn.setAttribute("aria-label", "Voice input");
  // One complete press is pointerdown then pointerup. pointerdown starts and
  // leaves the recorder running. pointerup and click must not stop it: that
  // posted a WebM header with no audio clusters. The next press's pointerdown
  // stops and posts every chunk.
  let pressDown = false;
  micBtn.addEventListener("pointerdown", (e) => {
    if (e.button != null && e.button !== 0) return;
    if (pressDown) return;
    pressDown = true;
    toggleMic();
  });
  micBtn.addEventListener("pointerup", () => { pressDown = false; });
  micBtn.addEventListener("pointercancel", () => { pressDown = false; });
  micBtn.addEventListener("click", (e) => { e.preventDefault(); });
}
if ($("#voiceModeBtn")) $("#voiceModeBtn").onclick = () => { setVoiceMode(!voiceMode); };
loadVoicePower();
if ($("#stopSpeechBtn")) $("#stopSpeechBtn").onclick = () => { stopCurrentSpeech(); };
if ($("#thread")) {
  $("#thread").addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest("[data-speak]");
    if (!btn) return;
    e.preventDefault();
    readAloud(btn);
  });
}

// Models browser filters (MAP › Models)
$$(".tabs [data-tab]").forEach((b) => (b.onclick = () => { state.mtab = b.dataset.tab; renderModelsList(); }));
if ($("#mfTarget")) $("#mfTarget").onchange = (e) => { state.mf.target = e.target.value; renderModelsList(); };
["cVram", "cRam"].forEach((id) => $(`#${id}`)?.addEventListener("input", () => renderModelsList()));
if ($("#mfFits")) $("#mfFits").onchange = (e) => { state.mf.fits = e.target.checked; renderModelsList(); };
if ($("#mfCtx")) $("#mfCtx").onchange = (e) => { state.mf.ctx = +e.target.value; renderModelsList(); };
$$("#mfTrust input").forEach((i) => (i.onchange = () => {
  if (i.checked) state.mf.trust.add(i.dataset.t); else state.mf.trust.delete(i.dataset.t);
  renderModelsList();
}));
$$("#mfAbl button").forEach((b) => (b.onclick = () => {
  state.mf.abl = b.dataset.v;
  const q = (state.mf.q || "").trim();
  if (state.mtab === "browse" && q.length >= 2) {
    hfBusy = true;
    hfErr = "";
    renderModelsList();
    clearTimeout(hfTimer);
    hfTimer = setTimeout(() => runHfSearch(q), 200);
  } else {
    renderModelsList();
  }
}));
$$("#mfLic button").forEach((b) => (b.onclick = () => { state.mf.lic = b.dataset.v; renderModelsList(); }));
$$("#mfVis button").forEach((b) => (b.onclick = () => {
  state.mf.vis = b.dataset.v;
  const q = (state.mf.q || "").trim();
  if (state.mtab === "browse" && q.length >= 2) runHfSearch(q);
  else renderModelsList();
}));
if ($("#mfQuant")) $("#mfQuant").onchange = (e) => { state.mf.quant = e.target.value; renderModelsList(); };
if ($("#mfSort")) $("#mfSort").onchange = (e) => {
  state.mf.sort = e.target.value;
  if (state.mf.sort === "running") {
    const run = lastCatalog.find((m) => m.running) || lastCatalog.find((m) => m.active);
    if (run) selectedModelId = run.id;
    else toast("No model is running");
  }
  renderModelsList();
  if (state.mf.sort === "running") {
    document.querySelector("#modelList .mcard.sel")?.scrollIntoView({ block: "nearest" });
  }
};
if ($("#mfSearch")) $("#mfSearch").addEventListener("input", (e) => {
  state.mf.q = e.target.value;
  clearTimeout(hfTimer);
  const q = state.mf.q.trim();
  if (state.mtab !== "browse" || q.length < 2) {
    hfHits = [];
    hfErr = "";
    hfBusy = false;
    renderModelsList();
    return;
  }
  hfBusy = true;
  hfErr = "";
  renderModelsList();
  hfTimer = setTimeout(() => runHfSearch(q), 450);
});
async function runHfSearch(q) {
  try {
    const res = await control("hf_search", { q, abl: state.mf.abl || "include", vision: state.mf.vis || "any" });
    if ((state.mf.q || "").trim() !== q) return;
    if (!res.ok) {
      hfHits = [];
      hfErr = res.error || "Search failed";
    } else {
      hfHits = res.models || [];
      hfErr = hfHits.length ? "" : (state.mf.vis === "only" ? "No vision GGUF files for that search" : state.mf.abl === "only" ? "No abliterated GGUF files for that search" : "No GGUF files for that search");
    }
  } catch (e) {
    if ((state.mf.q || "").trim() !== q) return;
    hfHits = [];
    hfErr = e.message || "Search failed";
  }
  hfBusy = false;
  renderModelsList();
}
if ($("#mfReset")) $("#mfReset").onclick = resetModelFilters;
let hfDirty = false;
let hfSaveTimer = null;
function hfHint(st) {
  const el = $("#hfWhere");
  if (!el) return;
  if (st?.error) { el.textContent = st.error; return; }
  if (st?.saved || st?.hf_token_saved) {
    el.textContent = st.settings_mounted
      ? "Saved on the USB stick settings partition."
      : "Saved in the vault.";
    return;
  }
  if (st?.vault_unlocked) {
    el.textContent = st.settings_mounted
      ? "Saved on the USB stick settings partition when you enter a token. Same vault key. Not kept in the models folder."
      : "Saved in the vault when you enter a token. Not kept in the models folder.";
  } else el.textContent = "Unlock the vault to keep this token on the encrypted USB settings partition.";
}
if ($("#hfToken")) $("#hfToken").addEventListener("input", () => {
  hfDirty = true;
  clearTimeout(hfSaveTimer);
  hfSaveTimer = setTimeout(async () => {
    const token = $("#hfToken").value.trim();
    try {
      const res = await control("set_hf_token", { token });
      hfDirty = false;
      hfHint(res);
      if (res.note) toast(res.note);
    } catch (e) { hfHint({ error: e.message }); }
  }, 700);
});
if ($("#hfShow")) $("#hfShow").onclick = () => { const i = $("#hfToken"); if (i) i.classList.toggle("secret"); };
if ($("#hfTest")) $("#hfTest").onclick = () => toast("HF token test — live gated downloads come later; catalog downloads need no token");

applyModeUi("ephemeral");
newChat();
if (detectLocalHost()) isLocalMode = true;
let browserPaired = false;
let statusTimer = null;
function startAppStatus() {
  browserPaired = true;
  refreshStatus();
  if (statusTimer) return;
  // Stick kiosk polls faster so LAN Pair remints show in chat promptly.
  rememberPairCookie();
  refreshAgentLink();
  statusTimer = setInterval(() => { refreshStatus(); refreshAgentLink(); }, isLocalMode || detectLocalHost() ? 2000 : 3000);
}
ensurePaired(false).then((ok) => {
  if (!ok) return;
  startAppStatus();
  startOpenAppEvents();
});
if (detectLocalHost()) startOpenAppEvents();

// window.stickllmApp hooks are later.
const APP_LABELS = {
  minesweeper: "Minesweeper",
  solitaire: "Solitaire",
  notepad: "Notepad",
  calculator: "Calculator",
  tetris: "Tetris",
  files: "Files",
  media: "Media",
  monitor: "Monitor",
};
let openToastTimer = null;
function appLabel(id) {
  if (APP_LABELS[id]) return APP_LABELS[id];
  const a = catalogApps.get(APP_ID_ALIASES[id] || id);
  return (a && a.name) || id;
}
function reportOpenApp(id, result) {
  fetch("/api/ui/open-app-seen", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ id, result, opened: result === "opened" }),
  }).catch(() => {});
}
function showOpenAppToast(id) {
  const t = $("#toast");
  if (!t) return false;
  t.hidden = false;
  t.replaceChildren();
  const text = document.createElement("span");
  text.textContent = "Agent Zero opened " + appLabel(id) + " — ";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "Open in new tab";
  btn.onclick = (e) => {
    e.preventDefault();
    openAppFromClick(id);
  };
  t.append(text, btn);
  clearTimeout(openToastTimer);
  // Count the 30 s from when this tab is visible, so a background tab still
  // has the button when the user comes back to it.
  const arm = () => {
    clearTimeout(openToastTimer);
    openToastTimer = setTimeout(hideOpenAppToast, 30000);
  };
  if (document.visibilityState === "hidden") {
    document.addEventListener("visibilitychange", function shown() {
      if (document.visibilityState !== "visible") return;
      document.removeEventListener("visibilitychange", shown);
      arm();
    });
  } else {
    arm();
  }
  return true;
}
function hideOpenAppToast() {
  clearTimeout(openToastTimer);
  const t = $("#toast");
  if (!t) return;
  t.hidden = true;
  t.replaceChildren();
}
// Opening an app on a LAN browser works exactly like clicking its desktop
// icon (<a href="/apps/<id>/" target="stickllm-<id>">): the same URL and the
// same named target, so Chrome opens it in a new tab (or reuses that app's
// tab) and the page loads with the apps cookie. No window features, so it is
// a tab, never a pop-up window.
// Where an app id opens: its desktop icon (starter or catalog), then the
// catalog's open_url (docs is ONLYOFFICE at /apps/docs/), and /apps/<id>/
// only for the built-in starter apps. Unknown ids get null, not a 404 tab.
const APP_ID_ALIASES = { docs: "onlyoffice", office: "onlyoffice", "onlyoffice-docs": "onlyoffice" };
function appTabLink(id) {
  const cid = APP_ID_ALIASES[id] || id;
  const sel = (k, v) => document.querySelector("#deskIcons a.deskIcon[" + k + '="' + CSS.escape(v) + '"]');
  const icon = sel("data-starter", id) || sel("data-catalog-app", cid);
  if (icon && icon.getAttribute("href")) {
    return { href: icon.getAttribute("href"), target: icon.getAttribute("target") || "stickllm-" + cid };
  }
  const a = catalogApps.get(cid);
  if (a && a.open_url) return { href: a.open_url, target: "stickllm-" + cid };
  if (cid === "onlyoffice") return { href: "/apps/docs/", target: "stickllm-onlyoffice" };
  if (Object.prototype.hasOwnProperty.call(APP_LABELS, id)) return { href: "/apps/" + id + "/", target: "stickllm-" + id };
  return null;
}
// Agent Zero create_*/open_document: ONLYOFFICE opens that vault file.
function docsOpenHref(doc) {
  return "/apps/docs/?open=" + encodeURIComponent(String(doc || ""));
}
function openAppTab(id, doc) {
  const link = appTabLink(id);
  if (!link) return null;
  const cid = APP_ID_ALIASES[id] || id;
  const force = !!(doc && cid === "onlyoffice");
  if (force) link.href = docsOpenHref(doc);
  // Add-ons on a paired LAN browser: same signed handoff as the desktop icon.
  const icon = document.querySelector('#deskIcons a.deskIcon[data-catalog-app="' + CSS.escape(cid) + '"]');
  let resolve = null;
  if (icon && icon.dataset.openLink && !detectLocalHost() && token) {
    resolve = () => fetch(icon.dataset.openLink, {
      method: "POST", cache: "no-store",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ id: cid }),
    }).then((r) => r.json().catch(() => ({})).then((j) => ((r.ok && j.url) ? j.url : link.href)));
  }
  return openNamedTab(link.target, link.href, resolve, force);
}
// A click (toast button, notification, panel button): open the app tab.
function openAppFromClick(id) {
  hideOpenAppToast();
  stopTabCue();
  if (openAppTab(id, pendingDoc[id])) {
    reportOpenApp(id, "opened");
    return true;
  }
  // The browser refused a new tab even on a click (new tabs disabled by
  // policy). Apps only ever open in their own tab, never inside this page.
  reportOpenApp(id, "blocked");
  return false;
}
const pendingDoc = Object.create(null);
// Visible cue when Agent Zero opens an app while this tab is in the
// background: flash the tab title and, if allowed, show a notification whose
// click brings this tab forward.
const tabCue = { timer: null, base: "", note: null };
function stopTabCue() {
  if (document.visibilityState === "hidden") return;
  clearInterval(tabCue.timer);
  tabCue.timer = null;
  if (tabCue.base) document.title = tabCue.base;
  tabCue.base = "";
  if (tabCue.note) { try { tabCue.note.close(); } catch (e) {} tabCue.note = null; }
}
document.addEventListener("visibilitychange", stopTabCue);
function cueHiddenTab(id) {
  if (document.visibilityState !== "hidden") return false;
  const label = appLabel(id);
  if (!tabCue.base) tabCue.base = document.title;
  clearInterval(tabCue.timer);
  let on = false;
  tabCue.timer = setInterval(() => {
    on = !on;
    document.title = on ? "\u25B6 " + label + " opened \u2013 StickLLM" : tabCue.base;
  }, 1000);
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      const n = new Notification("Agent Zero opened " + label, {
        body: "Click to open it in a new tab.",
        tag: "stickllm-open-app",
      });
      n.onclick = () => {
        try { window.focus(); } catch (e) {}
        n.close();
        // The click is a user gesture: same new-tab open as the toast button.
        openAppFromClick(id);
      };
      tabCue.note = n;
    } catch (e) {}
  }
  return true;
}
function openStickApp(id, doc) {
  if (!/^[a-z][a-z-]{0,23}$/.test(id)) return false;
  if (doc) pendingDoc[id] = String(doc); else delete pendingDoc[id];
  // The gateway sends open_app only to the screen whose user just chatted
  // with Agent (a LAN browser that sent a message in the last 5 minutes,
  // else the kiosk). Kiosk and LAN browser alike do exactly what a click on
  // the app's desktop icon does: the same URL and named target, so a new tab
  // (or that app's existing tab). The kiosk allows pop-ups for itself, so it
  // opens at once; a LAN browser opens at once only if the user allowed
  // pop-ups for StickLLM. Otherwise the toast (and, for a background tab, the
  // title flash and notification) offers that same click.
  primeAppsSession();
  // The add-on catalog loads with the Apps page. A fresh tab that never showed
  // it has no link for an add-on yet: load the catalog once, then open.
  if (!appTabLink(id) && !openStickApp.retry) {
    refreshApps().catch(() => {}).finally(() => {
      openStickApp.retry = true;
      try { openStickApp(id, pendingDoc[id] || ""); } finally { openStickApp.retry = false; }
    });
    return true;
  }
  if (openAppTab(id, pendingDoc[id])) {
    reportOpenApp(id, "opened");
    return true;
  }
  // No click, so the browser refused the tab (pop-ups not allowed for this
  // site, iPhone/iPad Safari). Apps open only in their own tab, never in a
  // panel inside this page: the toast (and, for a background tab, the title
  // flash and notification) offers one "Open in new tab" click.
  cueHiddenTab(id);
  if (showOpenAppToast(id)) reportOpenApp(id, "toast-shown");
  else reportOpenApp(id, "blocked");
  return false;
}
// Agent Zero install_app: the gateway asks this screen; nothing installs
// until the user clicks Install here (the normal /api/apps/install).
let agentInstallId = "";
function showAgentInstall(id, name) {
  const box = $("#agentInstall");
  if (!box || !/^[a-z][a-z-]{0,23}$/.test(id)) return;
  agentInstallId = id;
  $("#aiTitle").textContent = "Install " + name + "?";
  $("#aiText").textContent = "Agent Zero asks to install " + name + ". It downloads and runs on this stick, inside your vault. Install it?";
  const err = $("#aiErr");
  if (err) { err.hidden = true; err.textContent = ""; }
  $("#aiYes").disabled = false;
  box.hidden = false;
  try { $("#aiYes").focus(); } catch (e) {}
}
async function agentInstallYes(extra) {
  const id = agentInstallId;
  if (!id) return;
  const cid = APP_ID_ALIASES[id] || id;
  $("#aiYes").disabled = true;
  try {
    const r = await fetch("/api/apps/install", {
      method: "POST",
      cache: "no-store",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(Object.assign({ id: cid }, extra || {})),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok && verifyGate(j, (more) => agentInstallYes(Object.assign({}, extra || {}, more)))) {
      $("#agentInstall").hidden = true;
      return;
    }
    if (!r.ok || j.ok === false) {
      const err = $("#aiErr");
      if (err) { err.textContent = j.message || "Not installed."; err.hidden = false; }
      $("#aiYes").disabled = false;
      return;
    }
    $("#agentInstall").hidden = true;
    agentInstallId = "";
    [1, 3, 10, 20, 40, 60, 120, 240, 480].forEach((sec) => setTimeout(() => refreshApps().catch(() => {}), sec * 1000));
  } catch (e) {
    $("#aiYes").disabled = false;
  }
}
if ($("#aiNo")) $("#aiNo").onclick = () => { $("#agentInstall").hidden = true; agentInstallId = ""; };
if ($("#aiYes")) $("#aiYes").onclick = () => { agentInstallYes(); };

function startOpenAppEvents() {
  if (typeof EventSource !== "function") return;
  if (startOpenAppEvents.armed) {
    if (typeof startOpenAppEvents.resubscribe === "function") startOpenAppEvents.resubscribe();
    return;
  }
  startOpenAppEvents.armed = true;
  let es = null;
  let delay = 1000;
  let timer = null;
  let gen = 0;

  function teardown() {
    if (!es) return;
    es.onerror = null;
    es.onopen = null;
    try { es.close(); } catch (e) { /* already closed */ }
    es = null;
  }

  async function connect() {
    const mine = ++gen;
    clearTimeout(timer);
    teardown();
    syncToken();
    let url = "/api/ui/events";
    try {
      const opts = {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: "{}",
        cache: "no-store",
      };
      if (typeof AbortSignal !== "undefined" && AbortSignal.timeout) opts.signal = AbortSignal.timeout(4000);
      const r = await fetch("/api/ui/events-ticket", opts);
      if (mine !== gen) return;
      if (r.ok) {
        const j = await r.json();
        if (j && j.t) url = "/api/ui/events?t=" + encodeURIComponent(j.t);
      }
    } catch (e) { /* cookie or loopback can still subscribe */ }
    if (mine !== gen) return;
    es = new EventSource(url);
    es.onopen = () => { delay = 1000; };
    es.addEventListener("open_app", (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data || "{}"); } catch (err) { return; }
      if (data && data.id) openStickApp(String(data.id), typeof data.doc === "string" ? data.doc : "");
    });
    es.addEventListener("install_confirm", (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data || "{}"); } catch (err) { return; }
      if (data && data.id) showAgentInstall(String(data.id), String(data.name || data.id));
    });
    es.onerror = () => {
      if (mine !== gen) return;
      teardown();
      const wait = delay;
      delay = Math.min(delay * 2, 15000);
      clearTimeout(timer);
      timer = setTimeout(connect, wait);
    };
  }

  function resubscribe() {
    if (document.visibilityState === "hidden") return;
    if (es && es.readyState !== EventSource.CLOSED) return;
    delay = 1000;
    connect();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") resubscribe();
  });
  window.addEventListener("focus", resubscribe);
  startOpenAppEvents.resubscribe = resubscribe;
  connect();
}

})();

// 0.5.2: StickLLM's own right-click menu. On the kiosk (cage, software
// rendering) Chromium's native context menu draws invisible in both themes,
// so this page shows its own: Cut/Copy/Paste/Select all, link actions, Reload.
// Shift+right-click falls through to the native menu.
(function stickContextMenu() {
  let menu = null;
  let ctx = null;
  function close() {
    if (menu) menu.hidden = true;
    ctx = null;
  }
  function editableOf(el) {
    if (!el || !el.closest) return null;
    const ed = el.closest('input, textarea, [contenteditable=""], [contenteditable="true"]');
    if (!ed) return null;
    if (ed.tagName === "INPUT" && !/^(text|search|url|email|tel|number|password|)$/i.test(ed.type || "")) return null;
    if (ed.disabled || ed.readOnly) return { el: ed, ro: true };
    return { el: ed, ro: false };
  }
  function selectedText(ed) {
    if (ed && (ed.el.tagName === "INPUT" || ed.el.tagName === "TEXTAREA")) {
      try { return ed.el.value.slice(ed.el.selectionStart, ed.el.selectionEnd); } catch (e) { return ""; }
    }
    return String(window.getSelection ? window.getSelection() : "");
  }
  function restore() {
    if (!ctx || !ctx.ed) return;
    try { ctx.ed.el.focus({ preventScroll: true }); } catch (e) {}
    if (ctx.range && (ctx.ed.el.tagName === "INPUT" || ctx.ed.el.tagName === "TEXTAREA")) {
      try { ctx.ed.el.setSelectionRange(ctx.range[0], ctx.range[1]); } catch (e) {}
    }
  }
  async function act(what) {
    const c = ctx;
    close();
    if (!c) return;
    ctx = c;
    restore();
    try {
      if (what === "copy" || what === "cut") {
        if (!document.execCommand(what) && c.text && navigator.clipboard) await navigator.clipboard.writeText(c.text);
      } else if (what === "paste") {
        let t = "";
        try { t = await navigator.clipboard.readText(); } catch (e) { t = ""; }
        if (t) document.execCommand("insertText", false, t);
        else if (typeof toast === "function") toast("Paste with Ctrl+V");
      } else if (what === "selectall") {
        if (c.ed && c.ed.el.select) c.ed.el.select(); else document.execCommand("selectAll");
      } else if (what === "openlink") {
        const w = window.open(c.href, "_blank", "noopener");
        if (!w) location.href = c.href;
      } else if (what === "copylink") {
        await navigator.clipboard.writeText(c.href);
      } else if (what === "reload") {
        location.reload();
      }
    } catch (e) { /* clipboard refused: nothing to do */ }
    ctx = null;
  }
  function build() {
    menu = document.createElement("div");
    menu.id = "ctxMenu";
    menu.className = "ctxMenu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    // Keep the selection and focus where they are while the menu is used.
    menu.addEventListener("mousedown", (e) => e.preventDefault());
    menu.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]");
      if (b && !b.disabled) act(b.dataset.act);
    });
    menu.addEventListener("contextmenu", (e) => e.preventDefault());
    document.body.append(menu);
  }
  function item(act, label, key, off) {
    return '<button type="button" role="menuitem" data-act="' + act + '"' + (off ? " disabled" : "") + ">" +
      "<span>" + label + "</span>" + (key ? "<kbd>" + key + "</kbd>" : "") + "</button>";
  }
  document.addEventListener("contextmenu", (e) => {
    if (e.shiftKey || e.defaultPrevented) return;
    if (!document.body) return;
    if (!menu) build();
    const ed = editableOf(e.target);
    const a = e.target.closest ? e.target.closest("a[href]") : null;
    const href = a && /^(https?:|\/)/i.test(a.getAttribute("href") || "") ? a.href : "";
    const text = selectedText(ed);
    let range = null;
    if (ed && (ed.el.tagName === "INPUT" || ed.el.tagName === "TEXTAREA")) {
      try { range = [ed.el.selectionStart, ed.el.selectionEnd]; } catch (err) { range = null; }
    }
    ctx = { ed, href, text, range };
    let html = "";
    if (href) html += item("openlink", "Open link in new tab") + item("copylink", "Copy link address") + "<hr>";
    if (ed) {
      html += item("cut", "Cut", "Ctrl+X", ed.ro || !text) + item("copy", "Copy", "Ctrl+C", !text) +
        item("paste", "Paste", "Ctrl+V", ed.ro) + item("selectall", "Select all", "Ctrl+A");
    } else {
      html += item("copy", "Copy", "Ctrl+C", !text) + item("selectall", "Select all", "Ctrl+A");
    }
    html += "<hr>" + item("reload", "Reload", "F5");
    e.preventDefault();
    menu.innerHTML = html;
    menu.hidden = false;
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = Math.max(4, Math.min(e.clientX, window.innerWidth - w - 4)) + "px";
    menu.style.top = Math.max(4, Math.min(e.clientY, window.innerHeight - h - 4)) + "px";
    const first = menu.querySelector("button:not(:disabled)");
    if (first && e.button !== 2) first.focus({ preventScroll: true });
  });
  document.addEventListener("mousedown", (e) => { if (menu && !menu.hidden && !menu.contains(e.target)) close(); }, true);
  document.addEventListener("keydown", (e) => {
    if (!menu || menu.hidden) return;
    if (e.key === "Escape") { e.preventDefault(); close(); restore(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const bs = [...menu.querySelectorAll("button:not(:disabled)")];
      if (!bs.length) return;
      e.preventDefault();
      let i = bs.indexOf(document.activeElement);
      i = e.key === "ArrowDown" ? (i + 1) % bs.length : (i <= 0 ? bs.length - 1 : i - 1);
      bs[i].focus({ preventScroll: true });
    }
  }, true);
  window.addEventListener("blur", close);
  window.addEventListener("resize", close);
  document.addEventListener("scroll", close, true);
})();
