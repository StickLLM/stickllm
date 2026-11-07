(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const app = $("#app");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// 0.6.5: never native-alert raw gateway status codes (Cursor Simple Browser
// was popping window.alert("pair_required") on reconnect). Keep confirm/prompt.
(function gateNativeDialogs() {
  const raw = /^(pair_required|vault_locked|not_paired|unauthorized|plugins_locked|no_model|app_not_open|agent_not_running)(:.*)?$/i;
  const a0Noise = /agent.?zero is not running|agent_not_running|agent not responding|not responding|refused to connect|err_connection_refused|could not get data|unable to load agent zero|this site can.?t be reached|err_empty_response|connection (reset|refused|closed)/i;
  const wrap = (fn) => function gatedAlert(msg) {
    const s = String(msg == null ? "" : msg).trim();
    if (raw.test(s) || /^\{[\s\S]*"error"\s*:\s*"pair_required"/i.test(s)) return;
    // A0 iframe / intentional vault-lock: never block the desk with refuse popups.
    if (a0Noise.test(s) || (typeof vaultLocking !== "undefined" && vaultLocking)) return;
    return fn.apply(this, arguments);
  };
  try {
    if (typeof window.alert === "function") window.alert = wrap(window.alert.bind(window));
  } catch (_) {}
})();
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
let vaultLocking = false; // intentional Lock vault — toast/alert gates + A0 suppress
let vaultEpoch = 0;
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
let hwInfo = { vram: 0, vramEach: 0, gpuCount: 0, planCount: 0, backend: "", ram: 0, gpu: "", name: "This machine" };
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
  mf: { target: "this", fits: false, ctx: 32768, trust: ALL_TRUST(), abl: "include", quant: "any", lic: "any", vis: "any", q: "", sort: "fit" },
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
    setPairIcon("paired");
    hideNotPaired();
    afterPairSuccess().catch(() => {});
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
let pairLostAt = 0;
function pairLost(msg) {
  const now = Date.now();
  // Debounce: reconnect blips must not re-flash the pair overlay every few seconds.
  if (pairUiState === "unpaired" && now - pairLostAt < 20000) return;
  pairLostAt = now;
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
  // Force /api/ui/apps-session on the next prime (do not fake a fresh session).
  appsSession.token = ""; appsSession.at = 0;
  setPairIcon("paired");
  hideNotPaired();
  return j;
}
/** After a successful pair: cookies, status, desktop/A0 — no manual F5. */
async function afterPairSuccess() {
  rememberPairCookie();
  try { await primeAppsSession(true); } catch (_) {}
  startAppStatus();
  startOpenAppEvents();
  try { await refreshStatus(); } catch (_) {}
  try { await refreshAgentLink(); } catch (_) {}
  try { await refreshModels(); } catch (_) {}
  try { window.dispatchEvent(new CustomEvent("stickllm:paired")); } catch (_) {}
  try {
    if (window.stickDesk && typeof window.stickDesk.onPaired === "function") {
      await window.stickDesk.onPaired();
    }
  } catch (_) {}
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
// 0.5.6: on the Xfce desktop each app opens as its own window (a popup of
// the same browser profile), not as a tab, so it gets its own taskbar button.
function onXfceShell() {
  try {
    if (/[?&]shell=xfce(?:&|$)/.test(location.search)) sessionStorage.setItem("stickllm.shell", "xfce");
    return sessionStorage.getItem("stickllm.shell") === "xfce";
  } catch (e) { return false; }
}
function openNamedTab(target, url, resolve, force) {
  let w = appTabHandle(target);
  if (!w) {
    try {
      w = onXfceShell()
        ? window.open("", target, "popup,width=" + Math.min(1280, screen.availWidth || 1280) + ",height=" + Math.min(820, screen.availHeight || 820))
        : window.open("", target);
    } catch (e) { w = null; }
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
function agentUrlIsLoopback(u) {
  try {
    const h = new URL(String(u), location.href).hostname;
    return h === "127.0.0.1" || h === "localhost" || h === "::1" || h === "[::1]";
  } catch (_) {
    return /127\.0\.0\.1|localhost|\[::1\]/.test(String(u || ""));
  }
}
function agentPageUrl(status, opts) {
  // Same-origin /agent-zero/ for Chat iframe AND the stick kiosk.
  // Never open raw http://127.0.0.1:5099/ from the UI — while Agent Zero is
  // starting, Chromium shows "can't connect to 127.0.0.1" on the kiosk and on
  // laptops. The gateway embed returns a proper status instead.
  // LAN pop-out (embed:false off-stick) may still use :5443 after cert trust.
  const embed = !(opts && opts.embed === false);
  if (embed || detectLocalHost()) {
    if (status && status.agent_embed) return status.agent_embed;
    if (status && status.agent_url && String(status.agent_url).indexOf("/agent-zero") >= 0) return status.agent_url;
    return "/agent-zero/";
  }
  const advertised = status && (status.agent_popout_url || status.agent_url);
  if (advertised && String(advertised).indexOf("/agent-zero") < 0 && !agentUrlIsLoopback(advertised)) {
    return advertised;
  }
  const host = location.hostname || "127.0.0.1";
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
    icon.innerHTML = '<span class="deskGlyph deskGlyphLogo" aria-hidden="true"><img src="agent-zero.png?v=desk7" alt=""></span><span class="deskLabel">Agent Zero</span>';
    desk.appendChild(icon);
  }
  icon.href = href;
}
// 0.6.0 (A5): one status line for Agent Zero while it installs or loads.
// 0.6.2 (A4): "Step X of 6: <name>… N%" across the whole install (load,
// unpack, check, create, start, health); 100% only when A0 answers.
let agentLastStatus = null;
let agentInstallWatch = false;   // this page started an install: switch to Open when ready
let agentReadyToasted = false;
function agentProgressLine(s) {
  if (!s) return "";
  const pct = Number.isFinite(Number(s.progress)) && s.progress !== null && s.progress !== "" ? Math.round(Number(s.progress)) : null;
  const tail = pct !== null ? " " + Math.max(0, Math.min(99, pct)) + "%" : "";
  if (s.state !== "installing" && s.state !== "starting") return "";
  const who = s.state === "starting" ? "Starting Agent Zero" : "Installing Agent Zero";
  if (s.step && s.steps) return `${who} — step ${s.step} of ${s.steps}: ${s.step_name || s.phase || ""}…${tail}`;
  const phase = {
    loading: "Loading Agent Zero from the stick…",
    downloading: "Downloading Agent Zero…",
    checking: "Checking Agent Zero…",
  }[s.phase] || (s.state === "starting" ? "Agent Zero is starting…" : "Installing Agent Zero…");
  return phase + tail;
}
function setBtnBusy(btn, busy, text) {
  if (!btn) return;
  btn.classList.toggle("busy", !!busy);
  btn.disabled = !!busy;
  btn.setAttribute("aria-busy", busy ? "true" : "false");
  if (text != null) btn.textContent = text;
}
// True when /agent-zero/ is actually usable — never navigate an iframe to a
// dead :5099 / splash-"Unable to load" / refused-to-connect page.
// CSRF only (proves embed proxy + A0 API). HEAD+/status.running alone used to
// embed too early; A0 then navigated the frame to 127.0.0.1:5099 and Chromium
// showed connection refused until a full desktop reload.
let agentHttpReadyCache = { ok: false, at: 0 };
async function agentHttpReady(force) {
  const now = Date.now();
  if (!force && agentHttpReadyCache.at && (now - agentHttpReadyCache.at) < 1200) {
    return !!agentHttpReadyCache.ok;
  }
  const fail = () => {
    agentHttpReadyCache = { ok: false, at: now };
    return false;
  };
  try {
    const csrf = await fetch("/agent-zero/api/csrf_token", {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: authHeaders({ Accept: "application/json" }),
    });
    if (csrf.status === 503 || csrf.status === 502 || csrf.status === 404) return fail();
    if (!csrf.ok) return fail();
    const j = await csrf.json().catch(() => ({}));
    if (j && (j.ok === true || j.token || j.csrf_token || typeof j === "string")) {
      agentHttpReadyCache = { ok: true, at: now };
      return true;
    }
    // 200 JSON without a token shape — still require a live status.running.
    const s = agentLastStatus || {};
    if (s.running || s.state === "running") {
      agentHttpReadyCache = { ok: true, at: now };
      return true;
    }
    return fail();
  } catch (_) {
    return fail();
  }
}

async function refreshAgentLink() {
  const label = $("#agentLinkLabel");
  const link = $("#agentLink");
  if (!label && !link && !$("#agentCatalogInstall") && !window.stickDesk) return;
  try {
    const r = await fetch("/api/agent/status", { cache: "no-store", headers: authHeaders() });
    if (r.status === 401 && !detectLocalHost() && pairUiState !== "unpaired") { ensurePaired().catch(() => {}); return; }
    if (!r.ok) return;
    const s = await r.json();
    agentLastStatus = s;
    // Invalidate HTTP-ready cache when status says not running.
    if (!(s.running || s.state === "running")) agentHttpReadyCache = { ok: false, at: 0 };
    const installed = agentIsInstalled(s);
    // Prefer /agent-zero/ (kiosk + LAN). Avoid raw :5099 — kiosk Chromium
    // shows "can't connect to 127.0.0.1" while A0 is still starting.
    const href = agentPageUrl(s, { embed: true });
    agentZeroNote = agentZeroStatusNote(installed, s);
    agentZeroInstalled = installed;
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
    else if (s.state === "installing") detail = agentProgressLine(s) || "Installing";
    else if (s.state === "pull_failed") detail = "Install failed";
    else if (s.state === "starting") detail = agentProgressLine(s) || "Starting";
    else if (s.state === "error") detail = (s.message || "Failed to start").replace(/\s+/g, " ").trim() || "Failed to start";
    else if (s.state === "low_space") detail = "Host drive is low on space";
    if (label) label.textContent = "Agent";
    if (note) note.textContent = detail;
    if (link) link.title = s.state === "error" ? detail : "";
    const deskIcon = $("#agentDeskIcon");
    if (deskIcon) deskIcon.title = s.state === "error" ? detail : "Agent";
    const line = agentProgressLine(s);
    const message = line || s.message || "";
    for (const msg of [$("#agentInstallMsg"), $("#agentCatalogMsg")]) {
      if (msg) msg.textContent = message;
    }
    const busy = s.state === "installing" || (agentInstallWatch && s.state === "starting");
    const ready = s.state === "running" && agentInstallWatch;
    const show = !!(s.needs_install || busy || s.state === "pull_failed" || ready);
    for (const btn of agentInstallButtons()) {
      btn.hidden = !show;
      if (ready) {
        setBtnBusy(btn, false, "Open Agent Zero");
        btn.onclick = () => { agentInstallWatch = false; btn.onclick = () => installAgent(); refreshAgentLink(); a0OpenFull(); };
      } else if (busy) setBtnBusy(btn, true, "Installing…");
      else if (s.preinstalled || (s.drive && s.drive.seed_ready) || s.image_present) {
        setBtnBusy(btn, false, "Open Agent Zero");
        btn.hidden = true;
      } else setBtnBusy(btn, false, s.bundled ? "Install Agent Zero (from the stick)" : "Install Agent Zero");
    }
    if (ready && !agentReadyToasted) { agentReadyToasted = true; toast("Agent Zero is ready — Open Agent Zero"); }
    if (s.state === "error" || s.state === "pull_failed") agentInstallWatch = false;
    renderA0Drive(s);
    const text = s.state === "error" ? (s.message || detail) : (s.pull_log || "");
    for (const log of [$("#agentPullLog"), $("#agentCatalogPull")]) {
      if (!log) continue;
      log.hidden = !text;
      log.textContent = text;
    }
    try { window.dispatchEvent(new CustomEvent("stickllm:agent-status", { detail: s })); } catch (_) {}
  } catch (e) { /* status is optional until the gateway is current */ }
}
// 0.6.2 (A4): poll every 1.5 s while an install/start is in flight.
let agentFastTimer = null;
function agentFastPoll() {
  if (agentFastTimer) return;
  agentFastTimer = setInterval(() => {
    const s = agentLastStatus;
    if (s && s.state !== "installing" && s.state !== "starting" && !(agentInstallWatch && !s.state)) {
      clearInterval(agentFastTimer); agentFastTimer = null;
    }
    refreshAgentLink();
  }, 1500);
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
  for (const btn of agentInstallButtons()) setBtnBusy(btn, true, "Installing…");
  agentInstallWatch = true; agentReadyToasted = false;
  try {
    const r = await fetch("/api/agent/install", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(extra || {}),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok && verifyGate(j, (more) => installAgent(Object.assign({}, extra || {}, more)))) {
      for (const btn of agentInstallButtons()) setBtnBusy(btn, false, "Install Agent Zero");
      agentInstallWatch = false;
      return;
    }
    if (!r.ok) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    toast(j.message || "Installing Agent Zero");
  } catch (e) {
    agentInstallWatch = false;
    for (const btn of agentInstallButtons()) setBtnBusy(btn, false, "Install Agent Zero");
    showError(e, "Could not install Agent Zero");
  }
  agentFastPoll();
  refreshAgentLink();
}
for (const btn of agentInstallButtons()) btn.onclick = () => installAgent();
function showApps() {
  // Desktop layout (0.5.6): the catalog is its own window (App Store).
  if (window.stickDesk && window.stickDesk.handles("store") && window.stickDesk.openApp("store")) return;
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
  // Desktop layout (desktop.js): starter and installed catalog apps open in
  // a window on the desktop (0.5.6), never a browser tab.
  if (window.stickDesk && window.stickDesk.handles(id)) return !!window.stickDesk.openApp(id);
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
    // Confirm before wiping the session — a brief gateway blip must not
    // spam the re-pair overlay on a still-paired LAN browser.
    let stillPaired = false;
    try {
      const st = await fetch("/api/pair/status", { cache: "no-store", headers: authHeaders() }).then((x) => x.json());
      stillPaired = !!(st && (st.local || st.this_paired || !st.require_pair));
    } catch (_) { /* offline blip */ }
    if (!stillPaired) pairLost("This browser is no longer paired with the stick.");
    throw new Error(stillPaired ? "Temporary auth error — retry" : "Pair required");
  }
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status} (no JSON)` }));
  if (!r.ok) {
    const e = new Error(j.message && j.error ? `${j.error}: ${j.message}` : (j.error || j.message || `HTTP ${r.status}`));
    e.status = r.status;
    throw e;
  }
  return j;
}

// 0.6.1-hotfix: errors stay on screen until dismissed (toasts vanish in 2.8 s).
function plainError(raw) {
  const s = String(raw || "").replace(/^stickllm-vault:\s*/gm, "").trim();
  if (/refusing StickLLM live USB \/ STICKLLM-DATA/i.test(s))
    return "This folder is on the StickLLM drive itself. To keep the vault here, use \u201cStore vault on this drive\u2026\u201d (or pick the folder again and click Use this drive), then Create vault.";
  if (/passcodes? (do not|don't) match/i.test(s)) return "The two passcodes don't match.";
  if (/at least 8/i.test(s)) return "The passcode must be at least 8 characters.";
  if (/not writable|read-only/i.test(s)) return "StickLLM can't write to that folder. Pick another folder or drive.";
  if (/Pair required|no longer paired/i.test(s)) return "This browser is no longer paired with the stick. Pair again and retry.";
  return s.split("\n")[0] || "Something went wrong.";
}
function showError(err, title) {
  title = title || (err && err.title);
  const raw = (err && err.message) ? err.message : String(err || "");
  // Mid lock: A0 going away is expected — never sticky-error the desk.
  if (vaultLocking && /agent.?zero|agent_not_running|not responding|refused to connect|could not get data/i.test(raw + " " + (title || ""))) {
    return;
  }
  let box = document.getElementById("errBox");
  if (!box) {
    box = document.createElement("div");
    box.id = "errBox"; box.className = "errBox"; box.setAttribute("role", "alert");
    box.innerHTML = '<div class="ebHead"><b class="ebTitle"></b><button type="button" class="ebX" aria-label="Dismiss">\u00d7</button></div>' +
      '<p class="ebMsg"></p><details><summary>Details</summary><pre class="ebRaw"></pre></details>' +
      '<div class="ebActs"><button type="button" class="btn sm ebCopy">Copy details</button><button type="button" class="btn sm ghost ebOk">Dismiss</button></div>';
    document.body.appendChild(box);
    const hide = () => { box.hidden = true; };
    box.querySelector(".ebX").onclick = hide; box.querySelector(".ebOk").onclick = hide;
    box.querySelector(".ebCopy").onclick = async () => {
      const t = box.dataset.details || "";
      try { await navigator.clipboard.writeText(t); }
      catch (_) { const ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); } catch (_e) {} ta.remove(); }
      box.querySelector(".ebCopy").textContent = "Copied";
      setTimeout(() => { box.querySelector(".ebCopy").textContent = "Copy details"; }, 1500);
    };
  }
  box.querySelector(".ebTitle").textContent = title || "Something went wrong";
  box.querySelector(".ebMsg").textContent = plainError(raw);
  box.querySelector(".ebRaw").textContent = raw;
  box.dataset.details = `${title || "Error"}\n${new Date().toISOString()}\n${raw}`;
  box.hidden = false;
  try { console.error("[StickLLM]", title || "", raw); } catch (_) {}
}
let tt;
// 0.6.2: toasts stack (newest at the bottom), each has a close X, and a new
// one never replaces an older message (so a warning cannot hide an error).
// Errors use showError()'s persistent box.
// 0.6.5: coalesce disconnect / Failed-to-fetch spam so remote clients are not
// flooded while EventSource or health briefly drop.

const toastRecent = new Map();
function toast(msg, opts) {
  opts = opts || {};
  const text = String(msg == null ? "" : msg);
  // Intentional vault lock: suppress A0/connection refuse spam (UI already tore down embeds).
  if (vaultLocking && !opts.force
    && /agent.?zero|agent_not_running|not responding|refused to connect|err_connection|could not get data|unable to load|starting agent|disconnected|reconnected|websocket/i.test(text)
    && !/^vault locked$/i.test(text.trim())) {
    return;
  }
  const flaky = /failed to fetch|networkerror|load failed|err_network|err_connection|connection (reset|refused|closed|lost)|disconnected|no longer paired|temporary auth|stick not answering|waiting…|agent not responding|agent.?zero is not running/i.test(text);
  const now = Date.now();
  const prev = toastRecent.get(text) || 0;
  if (!opts.force && (now - prev) < (flaky ? 20000 : 4000)) {
    const stack0 = document.getElementById("toastStack");
    if (stack0 && Array.from(stack0.children).some((n) => n.dataset.msg === text)) return;
    if (flaky) return;
  }
  toastRecent.set(text, now);
  if (toastRecent.size > 40) {
    for (const [k, at] of toastRecent) { if (now - at > 60000) toastRecent.delete(k); }
  }
  let stack = document.getElementById("toastStack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toastStack"; stack.className = "toastStack";
    stack.setAttribute("role", "status"); stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  const dup = Array.from(stack.children).find((n) => n.dataset.msg === text);
  if (dup) dup.remove();
  const item = document.createElement("div");
  item.className = "toastItem" + (opts.warn || /^(warning|could not|couldn't|failed|error)/i.test(text) ? " warn" : "");
  item.dataset.msg = text;
  const span = document.createElement("span"); span.textContent = text;
  const x = document.createElement("button");
  x.type = "button"; x.className = "toastX"; x.setAttribute("aria-label", "Close"); x.textContent = "\u00d7";
  const close = () => { clearTimeout(item._t); item.remove(); };
  x.onclick = close;
  item.append(span, x);
  stack.appendChild(item);
  while (stack.children.length > 4) stack.firstElementChild.remove();
  const ms = opts.ms || (item.classList.contains("warn") ? 8000 : Math.max(2800, Math.min(8000, text.length * 60)));
  item._t = setTimeout(close, ms);
  item.onmouseenter = () => clearTimeout(item._t);
  item.onmouseleave = () => { item._t = setTimeout(close, 2500); };
  // The single #toast slot is for progress/open-app only; drop a finished one.
  const t = $("#toast");
  if (t && !t.classList.contains("busy") && !t.querySelector("button")) { clearTimeout(tt); t.hidden = true; }
}

// 0.6.0 (B8): anything that can take over a second shows progress. The
// spinner appears after 1 s and stays until done(); update() changes the text
// (for example "Starting Node-RED… 40%").
function progressToast(msg) {
  let text = msg, finished = false;
  const show = () => {
    if (finished) return;
    const t = $("#toast"); if (!t) return;
    t.textContent = text; t.classList.add("busy"); t.hidden = false;
    clearTimeout(tt);
  };
  const timer = setTimeout(show, 1000);
  return {
    update(m) { text = m; const t = $("#toast"); if (t && t.classList.contains("busy")) t.textContent = m; },
    done(m) {
      finished = true; clearTimeout(timer);
      const t = $("#toast");
      if (t) t.classList.remove("busy");
      if (m) toast(m); else if (t && !t.hidden) { clearTimeout(tt); tt = setTimeout(() => (t.hidden = true), 300); }
    },
  };
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
    ? (state.chatStore === "usb"  // 0.6.0 B9: from /api/chat-store
      ? "Vault: saved encrypted on this USB stick."
      : "Vault: saved encrypted on the host SSD.")
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

// 0.6.0 (B9/B10): pick the USB or SSD vault for chats; optional sync.
function paintChatStore(j) {
  const store = j.active || j.store || "ssd";
  state.chatStore = store;
  $$("#chatStoreSeg [data-store]").forEach((b) => {
    const on = b.dataset.store === (j.store || store);
    b.classList.toggle("on", on);
    b.disabled = !(j.available && j.available[b.dataset.store]);
    b.title = b.disabled ? "Unlock this vault first" : "";
  });
  const sync = $("#chatSync");
  if (sync) {
    sync.checked = !!j.sync;
    sync.disabled = !(j.available && j.available.ssd && j.available.usb);
  }
  const note = $("#chatStoreNote");
  if (note) {
    note.textContent = j.fallback
      ? `The ${j.store === "usb" ? "USB" : "SSD"} vault is locked, so chats use the ${store === "usb" ? "USB" : "SSD"} vault for now.`
      : "Both choices are encrypted with your vault passcode.";
  }
  applyModeUi(sessionMode);
}
async function refreshChatStore() {
  const r = await fetch("/api/chat-store", { cache: "no-store", headers: authHeaders() });
  const j = await r.json().catch(() => ({}));
  if (r.ok && j.ok !== false) paintChatStore(j);
  return j;
}
async function setChatStore(store, sync) {
  const t = progressToast("Switching chat vault…");
  try {
    const r = await fetch("/api/chat-store", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ store, sync: !!sync }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || `HTTP ${r.status}`);
    paintChatStore(j);
    const synced = j.sync_result ? ` · synced ${j.sync_result.copied} chat(s)` : "";
    t.done((store === "usb" ? "Chats now saved on the USB stick" : "Chats now saved on the host SSD") + synced);
    if (sessionMode === "vault") loadVaultChats().catch(() => {});
  } catch (e) {
    t.done("Chat vault: " + e.message);
    refreshChatStore().catch(() => {});
  }
}
$$("#chatStoreSeg [data-store]").forEach((b) => (b.onclick = () => setChatStore(b.dataset.store, $("#chatSync")?.checked)));
if ($("#chatSync")) $("#chatSync").onchange = (e) => {
  const cur = $("#chatStoreSeg [data-store].on")?.dataset.store || state.chatStore || "ssd";
  setChatStore(cur, e.target.checked);
};

async function setSessionMode(m, opts) {
  const next = m === "vault" ? "vault" : "ephemeral";
  const prev = sessionMode;
  const quiet = !!(opts && opts.quiet);
  if (sessionModeBusy) return;
  // Already in this mode — do not re-POST (gateway would re-fire ensure-addons
  // and the UI would toast "Vault mode · starting your apps" on every poll).
  if (next === prev && (next !== "vault" || state.vaultOpen)) {
    applyModeUi(next);
    return;
  }
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
        if (!quiet) {
          toast("No vault yet — create or attach one in Storage");
          openSettings("storage");
        }
        return;
      }
      if (!(st === "unlocked" || vault.mounted)) {
        applyModeUi(prev);
        if (!quiet) {
          toast("Unlock the vault first");
          await focusVaultUnlock();
        }
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
      // 0.6.0 (B3): Ephemeral only changes where chats go. The vault stays
      // unlocked, the model and add-ons keep running. A saved chat that is on
      // screen is left alone in the vault; new chats stay in memory.
      if (state.current && !state.ephemeral.includes(state.current)) newChat();
    }
    if (!quiet) {
      // Mode switch must not restart apps/model (gateway no longer ensure-addons).
      toast(next === "vault"
        ? "Vault mode · chats save encrypted"
        : "Ephemeral mode · new chats stay in memory");
    }
    renderConvs();
    if (next === "vault") loadVaultChats().catch(() => {});
  } catch (e) {
    applyModeUi(prev);
    if (!quiet) toast("Mode switch failed: " + e.message);
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

// 0.5.6: the stick's vault was set up on a different computer. Say so at once
// (no unlock attempt that probes this computer's drives) and offer to search
// this computer or pick a drive. Unlocking still works: the passcode opens the
// stick's settings, which may hold this computer's own vault location.
const VAULT_OTHER_RE = /VAULT_OTHER_COMPUTER:?\s*/;
function showVaultOther(on, label) {
  state.vaultOther = !!on;
  const box = $("#vaultOther");
  if (box) box.hidden = !on;
  if (!on) return;
  if ($("#vcState")) $("#vcState").textContent = "Vault is on another computer";
  if ($("#vcSub")) {
    $("#vcSub").textContent = (label ? `Set up on ${label}. ` : "") +
      "Search this computer for a vault, pick a drive, or enter the passcode to use this computer's saved vault.";
  }
}
if ($("#vaultOtherSearch")) $("#vaultOtherSearch").onclick = () => searchForVault({ inPicker: false });
if ($("#vaultOtherPick")) $("#vaultOtherPick").onclick = () => openFolderPicker("vault", "Choose folder / vault");

// Take the user to the passcode box. If the form is hidden (the page thinks
// the vault is open, or there is none) say why instead of failing silently.
async function focusVaultUnlock() {
  // Desktop layout (0.5.6): unlock from the taskbar's vault switch.
  if (deskOn() && window.stickDesk.vaultPrompt && window.stickDesk.vaultPrompt()) return true;
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
// vaultEpoch / vaultLocking are declared with the other top-level state.
const vaultBusy = () => vaultUnlocking || vaultLocking;
function setVaultChrome(open, absent = false) {
  if (!!open !== !!state.vaultOpen) vaultEpoch += 1;
  // Open -> locked from anywhere (another browser, the kiosk lock combo, a
  // lock in Settings): clear the screen too, not only the chrome (0.5.4).
  if (!open && state.vaultOpen && !vaultUnlocking && !clearingOnLock) clearOnLock();
  const wasOpen = !!state.vaultOpen;
  const vaultChanged = !!open !== wasOpen;
  state.vaultOpen = open;
  // 0.6.1 (item 20): vault models appear/disappear without a manual refresh.
  if (vaultChanged) setTimeout(() => { if (typeof refreshModels === "function") refreshModels().catch(() => {}); }, 300);
  // The mode tabs follow the vault: Vault is highlighted only while it is
  // unlocked, Ephemeral whenever it is locked (first load included).
  if (!open && sessionMode === "vault") applyModeUi("ephemeral");
  const none = !open && !!absent;
  $("#vaultCard")?.classList.toggle("open", open);
  // 0.5.6: the health poll repaints this too; keep "on another computer"
  // (set by refreshStorage) instead of flipping it back to "Vault locked".
  if ($("#vcState")) $("#vcState").textContent = open ? "Vault unlocked" : (none ? "No vault set up" : (state.vaultOther ? "Vault is on another computer" : "Vault locked"));
  if ($("#unlockForm")) $("#unlockForm").hidden = open;
  if (open) unlockMessage("");
  if ($("#lockBtn2")) $("#lockBtn2").hidden = !open;
  if ($("#lockBtn")) $("#lockBtn").hidden = !open;
  if ($("#popVault")) $("#popVault").textContent = open ? "Unlocked" : (none ? "Not set up" : "Locked");
  // 0.6.7: notify desktop/A0 once when the vault becomes open (listener was orphaned).
  if (open && vaultChanged) {
    try { window.dispatchEvent(new CustomEvent("stickllm:vault-unlocked")); } catch (_) {}
  }
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
    try { stickllmAutoStartA0 = false; } catch (_) {}
    try { agentHttpReadyCache = { ok: false, at: 0 }; } catch (_) {}
    state.vaultOpen = false;
    state.chats = [];
    state.ephemeral = [];
    state.current = null;
    state.attach = [];
    activeChatId = null;
    for (const w of appTabs.values()) { try { if (w && !w.closed) w.close(); } catch (_) {} }
    appTabs.clear();
    // Desktop: tear down A0 embeds (blank + close Chat) and vault app windows.
    // prepareForVaultLock is preferred; closeAll alone left the pinned Chat iframe alive.
    try {
      if (window.stickDesk && window.stickDesk.prepareForVaultLock) window.stickDesk.prepareForVaultLock();
      else if (window.stickDesk) window.stickDesk.closeAll();
    } catch (_) {}
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
  // Single-flight: mash Lock must not stack competing vault_lock calls.
  if (vaultLocking) return;
  vaultLocking = true;
  // Do not auto-restart A0 after this lock until the user opens it again.
  try { stickllmAutoStartA0 = false; } catch (_) {}
  try { agentHttpReadyCache = { ok: false, at: 0 }; } catch (_) {}
  // 1) Tear down A0 UI / vault app windows FIRST (blank iframes, stop polls)
  //    so stopping the container cannot paint "127.0.0.1 refused" / "agent not
  //    responding" over a live embed.
  try {
    if (window.stickDesk && window.stickDesk.prepareForVaultLock) window.stickDesk.prepareForVaultLock();
    else if (window.stickDesk && window.stickDesk.closeAll) window.stickDesk.closeAll();
  } catch (_) {}
  // 2) Clear readable vault/ephemeral chat state on screen.
  clearOnLock();
  // A0 going away during lock is expected (control vault_lock stops it).
  const isA0DownNoise = (s) => /agent.?zero is not running|agent_not_running|agent not responding|refused to connect/i.test(String(s || ""));
  try {
    // 3) Lock LUKS — control stops llama + stickllm-agent, then stickllm-vault
    //    stops add-ons/Docs and umounts. UI embeds are already gone.
    let res = await control("vault_lock");
    // Busy umount (docker still releasing): one short retry.
    if (res && res.ok === false && /busy|umount|in use|device is busy/i.test(String(res.error || res.stderr || ""))) {
      await new Promise((r) => setTimeout(r, 2500));
      res = await control("vault_lock");
    }
    if (res && res.ok === false) {
      const err = res.error || res.stderr || "unknown";
      if (isA0DownNoise(err)) {
        toast("Vault locked");
        setVaultChrome(false);
      } else {
        toast("Lock failed: " + err, { force: true });
        showError(new Error(String(err)), "Lock failed");
      }
    } else {
      toast("Vault locked");
      setVaultChrome(false);
    }
  } catch (e) {
    if (isA0DownNoise(e && e.message)) {
      toast("Vault locked");
      setVaultChrome(false);
    } else showError(e, "Lock failed");
  } finally { vaultLocking = false; vaultEpoch += 1; }
  try {
    await fetch("/api/session-mode", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ mode: "ephemeral" }),
    });
  } catch (_) {}
  try { refreshAgentLink(); } catch (_) {}
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
  // 0.6.2 (A6): Agent Zero's steps inline, link to the full window.
  const a0 = a0Html(m);
  const a0Link = m.a0 && !m.pending ? '<div class="msgTools"><a href="#agent" class="a0Full">Open the full Agent Zero window</a></div>' : "";
  return `<div class="msg ${cls}"><div class="av">${av}</div><div class="body">${pics}${m.pending ? a0 + wait : why + a0 + md(parts.answer)}${warn}${src}${speak}${undo}${a0Link}</div></div>`;
}
function renderThread(opts) {
  if (!(opts && opts.keepSpeech) && typeof stopSpeak === "function") stopSpeak();
  const th = $("#thread"), c = state.current;
  if (mainView !== "apps") $("#chatTitle").textContent = c ? c.title : "New chat";
  if (!c || !c.msgs.length) {
    // 0.5.6: no example prompts. The desktop Chat window hides this block
    // too (just the input); Classic keeps the heading and storage line.
    th.innerHTML = `<div class="empty"><span class="logo lg"></span><h2>What can I help with?</h2>
      <p>${esc(heroModeLine(state.mode))}</p></div>`;
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
// 0.5.6: Qwen3.5-4B often streams its reasoning as plain text before an orphan
// </think> (no <think>, nothing in reasoning_content). While streaming, text
// that opens like reasoning is held back ("Thinking…") until </think> comes;
// if it never comes the whole text is shown at the end.
const THINK_OPENER = /^\s*(thinking process:|here'?s a thinking process|\*\*thinking|okay,? (so )?(the user|let me|i need)|let me (think|analy[sz]e|figure)|the user (is asking|wants|asked|has asked|said))/i;
function streamingAnswer(content) {
  const s = String(content || "");
  if (!/<\/think>/i.test(s) && !/<think>/i.test(s) && THINK_OPENER.test(s)) return "";
  return stripThink(s);
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
      const answer = dropEmptyPlaceholder(streamingAnswer(content));
      // 0.5.5: the bubble shows (and voice speaks) the answer only, never the
      // reasoning; while there is only reasoning it says "Thinking…".
      const shown = answer;
      if (shown.trim() && shown.trim() !== "(empty response)" && onShown) onShown(shown);
      else if (onThink && (reasoning.trim() || splitThink(content).think || (content.trim() && !answer.trim()))) onThink();
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
// 0.6.1 (item 23): the chat model knows whether Agent Zero is there.
let agentZeroNote = "";
let agentZeroInstalled = false;
function agentZeroStatusNote(installed, s) {
  if (!installed) return "Agent Zero (the autonomous agent app on this stick) is not installed; it can be installed from Apps.";
  const st = String((s && s.state) || "");
  const how = st === "running" || st === "ready" ? "running" : (st ? "installed (" + st + ")" : "installed");
  return "Agent Zero (the autonomous agent app on this stick) is " + how + ". For multi-step work on files, code or the web, suggest the Agent Zero button next to Web, which sends the message to Agent Zero.";
}
function withAgentZeroNote(list) {
  if (!agentZeroNote) return list;
  const out = list.slice();
  const i = out.findIndex((m) => m && m.role === "system" && typeof m.content === "string");
  if (i >= 0) out[i] = { role: "system", content: out[i].content + "\n\n" + agentZeroNote };
  return out;
}
function messagesForRequest(voiceOn) {
  return withAgentZeroNote(messagesForRequestBase(voiceOn));
}
function messagesForRequestBase(voiceOn) {
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
// ---- App agent (0.5.6): requests aimed at an app go to stickllm-appagent
// (/appagent/act through the gateway) instead of the chat model. It shares the
// chat model (baked Qwen2.5-7B Q4) and only runs when the user loads it here.
// No picker: the target is the app window used last (focus), "in <App>, ..."
// names one, a keyword router covers the rest (installed apps only), and a
// search box + recent-apps row pick one by hand. Browser apps (Notepad,
// Calculator, Solitaire) are read and driven over the same-origin
// BroadcastChannel "stickllm-appbridge" (ui/apps/stickllm-bridge.js).
const APPAGENT_NAMES = { onlyoffice: "ONLYOFFICE slides", nodered: "Node-RED", notepad: "Notepad", calculator: "Calculator", solitaire: "Solitaire", tetris: "Tetris", minesweeper: "Minesweeper", media: "Media", browser: "Browser", slides: "Test slides" };
const APPAGENT_PREFIX = /^@(onlyoffice|office|slides|pptx|nodered|node-red|notepad|calculator|calc|solitaire|tetris|minesweeper|media|browser)\b[:,]?\s*/i;
const APPAGENT_IN = /^(?:in|on|with|use|using)\s+(?:the\s+)?(onlyoffice|office|slides|presentation|powerpoint|pptx|node-red|nodered|node red|notepad|notes?|calculator|calc|solitaire|cards|tetris|minesweeper|media|browser)(?:\s+app)?\s*[,:]\s*/i;
const APPAGENT_ALIAS = { onlyoffice: "onlyoffice", office: "onlyoffice", pptx: "onlyoffice", slides: "onlyoffice", presentation: "onlyoffice", powerpoint: "onlyoffice",
  nodered: "nodered", "node-red": "nodered", "node red": "nodered", notepad: "notepad", note: "notepad", notes: "notepad",
  calculator: "calculator", calc: "calculator", solitaire: "solitaire", cards: "solitaire",
  tetris: "tetris", minesweeper: "minesweeper", media: "media", browser: "browser" };
// Keyword router for requests with no app named and no app window used lately.
const APPAGENT_KEYWORDS = {
  onlyoffice: /\b(slides?|presentation|deck|textbox|text box|rectangle|ellipse|triangle|shape)\b/i,
  nodered: /\b(flows?|inject node|debug node|http[- ]in|http[- ]response|node-red|wire)\b/i,
  notepad: /\b(notepad|in the note|the document text|append|save as)\b/i,
  calculator: /\b(calculator|on the calc)\b/i,
  solitaire: /\b(solitaire|foundation|tableau|draw a card|move the [a-z0-9]+ of (hearts|spades|diamonds|clubs))\b/i,
  tetris: /\b(tetris|hard drop|falling piece)\b/i,
  minesweeper: /\b(minesweeper|flag the square|reveal the square)\b/i,
  media: /\b(media player|the video|the song|play the (?:video|song|music))\b/i,
  browser: /\b(web browser|in the browser|https?:\/\/|hello world|write a (?:page|program))\b/i,
};
const APPAGENT_CLIENT = ["notepad", "calculator", "solitaire", "tetris", "minesweeper", "media"];
const APPAGENT_DESKTOP = ["browser"];
const APPAGENT_RECENT_MS = 2 * 60 * 1000;
let appAgentApps = [];
let appAgentOn = false;
let appAgentBusy = false;
let appAgentPinned = "";
let appAgentSkipOnce = false;
const appAgentWins = new Map();
function appAgentSession() {
  let id = "";
  try { id = localStorage.getItem("stickllm-appagent-session") || ""; } catch (_) {}
  if (!/^[a-z0-9]{8,32}$/.test(id)) {
    id = "ui" + Math.random().toString(36).slice(2, 12);
    try { localStorage.setItem("stickllm-appagent-session", id); } catch (_) {}
  }
  return id;
}
function appAgentLastUsed(now) {
  let best = null;
  for (const w of appAgentWins.values()) {
    if (!appAgentApps.includes(w.id) || !w.focusT) continue;
    if (!best || w.focusT > best.focusT) best = w;
  }
  return best && (now || Date.now()) - best.focusT <= APPAGENT_RECENT_MS ? best.id : "";
}
function appAgentOpen(app) {
  if (APPAGENT_DESKTOP.includes(app)) return true;
  if (!APPAGENT_CLIENT.includes(app)) return true;
  for (const w of appAgentWins.values()) if (w.id === app) return true;
  return false;
}
function appAgentKeyword(text) {
  const hits = appAgentApps.filter((a) => APPAGENT_KEYWORDS[a] && APPAGENT_KEYWORDS[a].test(text) && appAgentOpen(a));
  return hits.length === 1 ? hits[0] : "";
}
function appAgentRoute(raw, now) {
  const text = String(raw || "").trim();
  if (!text || !appAgentApps.length) return null;
  let m = text.match(APPAGENT_PREFIX) || text.match(APPAGENT_IN);
  if (m) {
    const app = APPAGENT_ALIAS[m[1].toLowerCase()];
    const rest = text.slice(m[0].length).trim();
    return rest && appAgentApps.includes(app) ? { app, text: rest, why: "named" } : null;
  }
  if (appAgentSkipOnce) return null;
  if (appAgentPinned && appAgentApps.includes(appAgentPinned)) return { app: appAgentPinned, text, why: "picked" };
  const last = appAgentLastUsed(now);
  if (last) return { app: last, text, why: "last used" };
  const kw = appAgentKeyword(text);
  return kw ? { app: kw, text, why: "matched" } : null;
}
function appAgentReply(app, j) {
  const name = APPAGENT_NAMES[app] || app;
  if (j && j.error === "no_model") return `**${name}:** ${String(j.message || "No model is loaded.")}`;
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
function appAgentRecent() {
  let r = [];
  try { r = JSON.parse(localStorage.getItem("stickllm-appagent-recent") || "[]"); } catch (_) {}
  return (Array.isArray(r) ? r : []).filter((a) => appAgentApps.includes(a)).slice(0, 4);
}
function appAgentTouch(app) {
  const r = [app].concat(appAgentRecent().filter((a) => a !== app)).slice(0, 4);
  try { localStorage.setItem("stickllm-appagent-recent", JSON.stringify(r)); } catch (_) {}
}
function appAgentExperimental() {
  try { return localStorage.getItem("stickllm-appagent-exp") === "1"; } catch (_) { return false; }
}
function renderAppAgentBar() {
  const row = $("#appAgentRow");
  if (!row) return;
  // 0.5.9: the app agent is experimental and off by default (Settings > Advanced).
  row.hidden = !(appAgentExperimental() || appAgentOn);
  if ($("#advAppAgent")) $("#advAppAgent").checked = appAgentOn;
  const tog = $("#appAgentToggle");
  tog.setAttribute("aria-pressed", appAgentOn ? "true" : "false");
  tog.textContent = appAgentOn ? "App agent: on" : "App agent: off";
  tog.title = appAgentOn ? "Unload the app agent (the chat model stays loaded)" : "Load the app agent: chat can then work in your open apps";
  const on = appAgentOn && appAgentApps.length > 0;
  $("#appAgentPick").hidden = !on;
  const route = on ? appAgentRoute($("#input").value || "x") : null;
  const chip = $("#appAgentTarget");
  chip.hidden = !route;
  if (route) {
    chip.innerHTML = `→ ${esc(APPAGENT_NAMES[route.app] || route.app)} <small>(${esc(route.why)})</small> <button type="button" data-aaclear="1" title="Send this message to the chat instead" aria-label="Send to chat instead">✕</button>`;
  }
  $("#input").placeholder = route ? `Tell ${APPAGENT_NAMES[route.app] || route.app} what to do` : "Message StickLLM";
  const rec = $("#appAgentRecent");
  rec.innerHTML = on ? appAgentRecent().map((a) =>
    `<button type="button" class="aaChip${appAgentPinned === a ? " on" : ""}" data-aapin="${esc(a)}">${esc(APPAGENT_NAMES[a] || a)}</button>`).join("") : "";
  const dl = $("#appAgentList");
  dl.innerHTML = appAgentApps.map((a) => `<option value="${esc(APPAGENT_NAMES[a] || a)}"></option>`).join("");
}
async function loadAppAgentApps() {
  if (!$("#appAgentRow")) return;
  appAgentApps = [];
  if (appAgentOn) {
    try {
      const r = await fetch("/appagent/apps", { headers: authHeaders(), credentials: "same-origin" });
      const list = r.ok ? await r.json() : [];
      appAgentApps = (Array.isArray(list) ? list : []).map((a) => a && a.name).filter((n) => n && n !== "slides");
    } catch (_) { appAgentApps = []; }
  }
  if (appAgentPinned && !appAgentApps.includes(appAgentPinned)) appAgentPinned = "";
  renderAppAgentBar();
}
async function appAgentRefresh() {
  // Quiet status read: an unpaired browser just sees "off" (no pair prompt).
  try {
    const r = await fetch("/api/control", {
      method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ action: "appagent_status", params: {} }),
    });
    const j = r.ok ? await r.json() : {};
    appAgentOn = !!(j && j.running);
  } catch (_) { appAgentOn = false; }
  await loadAppAgentApps();
}
async function appAgentToggle() {
  const tog = $("#appAgentToggle");
  if (!(await ensurePaired())) return;
  tog.disabled = true;
  tog.textContent = appAgentOn ? "Unloading…" : "Loading…";
  try {
    const j = await control(appAgentOn ? "appagent_unload" : "appagent_load", { autoload: true });
    appAgentOn = !!(j && j.running);
    if (j && j.autoloaded) toast("Loading the on-stick model for the app agent…");
    else if (appAgentOn && j && j.model_loaded === false) {
      toast("App agent loaded. Load a model on the Models page (Qwen2.5-7B Q4 is on the stick) before asking an app.");
    }
  } catch (e) {
    toast(`App agent: ${e.message || e}`);
  } finally {
    tog.disabled = false;
  }
  await loadAppAgentApps();
}
// Browser apps: who is open, which window was used last, and calls into one.
let appAgentBC = null;
const appAgentCalls = new Map();
try {
  appAgentBC = new BroadcastChannel("stickllm-appbridge");
  appAgentBC.onmessage = (e) => {
    const d = e.data || {};
    if (!d.id || !/^[a-z-]{1,32}$/.test(String(d.id))) return;
    const key = `${d.id}:${d.inst || ""}`;
    if (d.type === "bye") { appAgentWins.delete(key); renderAppAgentBar(); return; }
    if (d.type === "reply") {
      const p = appAgentCalls.get(d.req);
      if (p) { appAgentCalls.delete(d.req); p(d); }
      return;
    }
    if (d.type !== "hello" && d.type !== "focus") return;
    const w = appAgentWins.get(key) || { id: d.id, inst: d.inst || "", focusT: 0 };
    w.seen = Date.now();
    if (d.type === "focus") { w.focusT = Date.now(); }
    appAgentWins.set(key, w);
    renderAppAgentBar();
  };
  appAgentBC.postMessage({ type: "who" });
} catch (_) { appAgentBC = null; }
function appAgentWindow(app) {
  let best = null;
  for (const w of appAgentWins.values()) {
    if (w.id !== app) continue;
    if (!best || (w.focusT || 0) > (best.focusT || 0) || ((w.focusT || 0) === (best.focusT || 0) && w.seen > best.seen)) best = w;
  }
  return best;
}
function appAgentCall(app, kind, action, ms = 8000) {
  return new Promise((resolve, reject) => {
    const w = appAgentWindow(app);
    if (!appAgentBC || !w) {
      reject(new Error(`${APPAGENT_NAMES[app] || app} is not open. Open it from the desktop, then ask again.`));
      return;
    }
    const req = "r" + Math.random().toString(36).slice(2, 12);
    const timer = setTimeout(() => { appAgentCalls.delete(req); reject(new Error(`${APPAGENT_NAMES[app] || app} did not answer. Is its window still open?`)); }, ms);
    appAgentCalls.set(req, (d) => { clearTimeout(timer); resolve(d); });
    appAgentBC.postMessage({ type: "call", to: app, inst: w.inst, req, kind, action: action || {} });
  });
}
async function appAgentBrowserState() {
  try {
    const j = await control("browser_status", {});
    return j && typeof j === "object" ? j : { windows: [] };
  } catch (e) {
    return { windows: [] };
  }
}
async function appAgentRunBrowser(actions) {
  const out = [];
  const taskbar = Math.round(48 * (window.devicePixelRatio || 1));
  for (const a of (Array.isArray(actions) ? actions : []).slice(0, 20)) {
    let res;
    try {
      if (a.page && a.page.html) {
        const saved = await fetch("/api/browser-page", {
          method: "POST", credentials: "same-origin",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ title: a.page.title || "Page", html: a.page.html }),
        });
        const doc = await saved.json().catch(() => ({}));
        if (!saved.ok || !doc.url) throw new Error(doc.message || doc.error || "The page was not saved");
        res = await control("browser_open", { url: doc.url, title: doc.title || a.page.title || "Page" });
        if (res && doc.vault && doc.vault.saved && doc.vault.path) res.vault_path = doc.vault.path;
      } else if (a.open) res = await control("browser_open", { url: a.open, title: a.title || "Browser" });
      else if (a.focus) res = await control("browser_focus", { id: a.focus });
      else if (a.close) res = await control("browser_close", { id: a.close });
      else if (a.op && a.id) res = await control("browser_window", { id: a.id, op: a.op, taskbar });
      else { out.push({ action: a, ok: false, error: "unknown browser action" }); break; }
    } catch (e) {
      out.push({ action: a, ok: false, error: String(e.message || e) });
      break;
    }
    const ok = !!(res && res.ok !== false && !res.error);
    out.push({ action: a, ok, error: ok ? "" : String((res && (res.message || res.error)) || "failed"), note: res && res.vault_path ? "Saved " + res.vault_path : "" });
    if (!ok) break;
  }
  try { window.dispatchEvent(new CustomEvent("stickllm-browser-changed")); } catch (_) {}
  return out;
}
async function appAgentRunClient(app, actions) {
  const out = [];
  for (const a of (Array.isArray(actions) ? actions : []).slice(0, 20)) {
    const d = await appAgentCall(app, "act", a, 15000);
    out.push({ action: a, ok: !!d.ok, error: d.error || "" });
    if (!d.ok) break;
  }
  return out;
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
  appAgentTouch(app);
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
    const body = { app, request: text, session: appAgentSession() };
    const client = APPAGENT_CLIENT.includes(app);
    const desk = APPAGENT_DESKTOP.includes(app);
    if (client) {
      const st = await appAgentCall(app, "state");
      body.state = st && st.result && typeof st.result === "object" ? st.result : {};
    } else if (desk) {
      body.state = await appAgentBrowserState();
    }
    const r = await fetch("/appagent/act", {
      method: "POST", credentials: "same-origin",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (r.status === 502) throw new Error("The app agent is not loaded. Turn it on with the App agent button.");
    if (!r.ok) throw new Error(j.error || j.message || `The app agent answered ${r.status}`);
    let txt = appAgentReply(app, j);
    let changed = (j.results || []).some((x) => x.ok);
    if ((client || desk) && Array.isArray(j.client_actions) && j.client_actions.length) {
      const ran = desk ? await appAgentRunBrowser(j.client_actions) : await appAgentRunClient(app, j.client_actions);
      const bad = ran.find((x) => !x.ok);
      if (bad) txt += `\n\n✗ ${APPAGENT_NAMES[app] || app} refused \`${JSON.stringify(bad.action).slice(0, 120)}\`: ${String(bad.error).slice(0, 120)}`;
      const notes = ran.filter((x) => x.note).map((x) => x.note);
      if (notes.length) txt += "\n\n" + notes.join("\n");
      changed = ran.some((x) => x.ok);
    } else if (client || desk) {
      changed = false;
    }
    pend.t = txt;
    if (changed) { pend.appUndo = app; if (!client) reloadAgentAppTab(app); }
  } catch (e) {
    pend.t = `**${APPAGENT_NAMES[app] || app}:** ${e.message || e}`;
    pend.warn = "Nothing was sent to the chat model.";
  } finally {
    pend.pending = false;
    appAgentBusy = false;
    renderThread();
    renderAppAgentBar();
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
    const body = { app, session: appAgentSession() };
    const client = APPAGENT_CLIENT.includes(app);
    const desk = APPAGENT_DESKTOP.includes(app);
    if (client) {
      const st = await appAgentCall(app, "state");
      body.state = st && st.result && typeof st.result === "object" ? st.result : {};
    } else if (desk) {
      body.state = await appAgentBrowserState();
    }
    const r = await fetch("/appagent/undo", {
      method: "POST", credentials: "same-origin",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `The app agent answered ${r.status}`);
    let ok = !!j.ok;
    if (ok && (client || desk) && Array.isArray(j.client_actions)) {
      const ran = desk ? await appAgentRunBrowser(j.client_actions) : await appAgentRunClient(app, j.client_actions);
      ok = ran.length > 0 && ran.every((x) => x.ok);
    }
    line = `**${APPAGENT_NAMES[app] || app}:** ${ok ? "Undone." : "Nothing to undo."} ${String(j.message || "").slice(0, 200)}`;
    if (ok) { m.appUndo = ""; if (!client) reloadAgentAppTab(app); }
  } catch (e) {
    line = `**${APPAGENT_NAMES[app] || app}:** undo failed: ${e.message || e}`;
  } finally {
    appAgentBusy = false;
  }
  c.msgs.push({ r: "ai", t: line.trim() });
  renderThread();
}
if ($("#appAgentRow")) {
  $("#appAgentToggle").onclick = () => appAgentToggle();
  $("#appAgentRow").addEventListener("click", (e) => {
    const pin = e.target.closest && e.target.closest("[data-aapin]");
    if (pin) {
      appAgentPinned = appAgentPinned === pin.dataset.aapin ? "" : pin.dataset.aapin;
      appAgentSkipOnce = false;
      renderAppAgentBar();
      return;
    }
    if (e.target.closest && e.target.closest("[data-aaclear]")) {
      // This message goes to the chat; the pin and the last-used window are dropped.
      appAgentPinned = "";
      appAgentSkipOnce = true;
      renderAppAgentBar();
    }
  });
  $("#appAgentSearch").addEventListener("change", (e) => {
    const q = String(e.target.value || "").trim().toLowerCase();
    const hit = appAgentApps.find((a) => a === q || (APPAGENT_NAMES[a] || "").toLowerCase() === q)
      || appAgentApps.find((a) => (APPAGENT_NAMES[a] || a).toLowerCase().includes(q));
    e.target.value = "";
    if (hit) { appAgentPinned = hit; appAgentSkipOnce = false; appAgentTouch(hit); }
    renderAppAgentBar();
  });
  $("#input").addEventListener("input", () => renderAppAgentBar());
  appAgentRefresh();
  // Pairing may finish after load: look again (at most every 15 s).
  let appAgentLooked = Date.now();
  $("#input").addEventListener("focus", () => {
    if (Date.now() - appAgentLooked < 15000) return;
    appAgentLooked = Date.now();
    appAgentRefresh();
  });
}
$("#thread").addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-appundo]");
  if (!b) return;
  e.preventDefault();
  appAgentUndo(Number(b.dataset.appundo));
});
// /apps/docs/ (same origin, another tab) says when a slides editor opens or
// closes; an open editor counts as the last-used app window.
try {
  const ch = new BroadcastChannel("stickllm-appagent");
  ch.onmessage = (e) => {
    const d = e.data || {};
    if (d.app !== "onlyoffice") return;
    if (d.open) appAgentWins.set("onlyoffice:", { id: "onlyoffice", inst: "", focusT: Date.now(), seen: Date.now() });
    else appAgentWins.delete("onlyoffice:");
    renderAppAgentBar();
  };
} catch (_) {}

// 0.6.1 (item 21): "open minesweeper" opens the app at once, no model call.
const OPEN_FAST_ALIAS = {
  minesweep: "minesweeper", mines: "minesweeper", office: "docs", onlyoffice: "docs",
  documents: "docs", document: "docs", word: "docs", excel: "docs", spreadsheet: "docs",
  "file manager": "files", "files app": "files", "text editor": "notepad", editor: "notepad",
  calc: "calculator", "system monitor": "monitor", music: "media", video: "media",
  "web browser": "browser", chromium: "browser", internet: "browser", web: "browser",
  "agent zero": "agent", agent0: "agent", a0: "agent", "node red": "node-red", nodered: "node-red",
  tasks: "tasks-md", "tasks.md": "tasks-md", notes: "trilium", budget: "paisa", comfy: "comfyui",
};
function openFastPathId(raw) {
  const m = String(raw || "").trim().match(/^(?:please\s+)?(?:open|start|launch|show|run)\s+(?:the\s+|my\s+)?(.{2,30}?)(?:\s+app)?\s*[.!]?$/i);
  if (!m) return "";
  const name = m[1].toLowerCase().replace(/\s+/g, " ").trim();
  const id = OPEN_FAST_ALIAS[name] || name.replace(/ /g, "-");
  return /^[a-z][a-z0-9-]{0,23}$/.test(id) ? id : "";
}
function openFastPath(raw) {
  const id = openFastPathId(raw);
  if (!id) return false;
  const desk = window.stickDesk;
  if (id === "browser") {
    if (desk && desk.openBrowser) { desk.openBrowser("", "Browser"); return true; }
    return false;
  }
  if (desk && desk.handles && desk.handles(id)) return !!desk.openApp(id);
  if (typeof appTabLink === "function" && appTabLink(id)) return openStickApp(id, "");
  return false;
}
// 0.6.2 (A6): with the Agent Zero toggle on, the message goes to Agent Zero
// through the gateway (/api/agent/ask + /api/agent/poll). Its steps show
// inline (collapsed) and its final answer becomes the reply, with a link to
// the full Agent window. Falls back to the 0.6.1 clipboard hand-off when A0
// is not running.
let a0Busy = false;
const A0_LOOP_HINT = "Agent Zero seems stuck repeating the same step. Small models often loop: load a bigger model (14B or more) for agent work.";
function a0Clip(t, n) { t = String(t || ""); return t.length > n ? t.slice(0, n) + "…" : t; }
function a0StepRows(steps) {
  return steps.map((st) => {
    let body = "";
    try {
      const j = JSON.parse(st.content);
      if (j && typeof j === "object") body = j.thoughts ? [].concat(j.thoughts).join(" ") : (j.tool_name ? "tool: " + j.tool_name : "");
    } catch (_) { body = st.type === "response" ? "" : st.content; }
    return { h: a0Clip(st.heading || st.type || "step", 160), b: a0Clip(body, 300) };
  });
}
function a0Html(m) {
  if (!m.a0) return "";
  const rows = m.a0.steps || [];
  const list = rows.length
    ? `<details class="a0Steps"${m.pending ? " open" : ""}><summary>Agent Zero steps (${rows.length})</summary><ol>${rows.map((r) => `<li><b>${esc(r.h)}</b>${r.b ? " — " + esc(r.b) : ""}</li>`).join("")}</ol></details>`
    : "";
  return `<div class="a0Run">${m.a0.status ? `<div class="a0Status">${esc(m.a0.status)}</div>` : ""}${list}</div>`;
}
function a0Thoughts(steps) {
  const out = [];
  for (const st of steps) {
    if (st.type !== "agent") continue;
    let t = st.content;
    try { const j = JSON.parse(st.content); if (j && j.thoughts) t = [].concat(j.thoughts).join(" ") + "|" + (j.tool_name || ""); } catch (_) {}
    out.push(String(t || "").toLowerCase().replace(/\s+/g, " ").slice(0, 400));
  }
  return out;
}
function a0Looping(steps) {
  const t = a0Thoughts(steps).filter(Boolean);
  if (t.length < 3) return false;
  const tail = t.slice(-3);
  return tail[0] === tail[1] && tail[1] === tail[2];
}
async function handOffToAgentZero(text) {
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; } catch (_) {}
  const desk = window.stickDesk;
  if (desk && desk.handles && desk.handles("agent")) desk.openApp("agent");
  else { const a = $("#agentLink"); if (a && a.href) window.open(a.href, a.target || "_blank"); }
  toast(!agentZeroInstalled ? "Agent Zero is not installed yet — install it from Apps."
    : copied ? "Opening Agent Zero… your message is on the clipboard: paste it there (Ctrl+V). Progress shows in the Agent Zero window."
    : "Opening Agent Zero… paste your message there. Progress shows in the Agent Zero window.");
}
async function a0Post(action, body) {
  const r = await fetch("/api/agent/" + action, {
    method: "POST", cache: "no-store", credentials: "same-origin",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body || {}),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) { const e = new Error(j.message || j.error || ("Agent Zero answered " + r.status)); e.status = r.status; throw e; }
  return j;
}
function a0OpenFull() {
  const desk = window.stickDesk;
  if (desk && desk.handles && desk.handles("agent")) return desk.openApp("agent");
  const a = $("#agentLink"); if (a && a.href) window.open(a.href, a.target || "_blank");
}
async function sendToAgentZero(text) {
  if (a0Busy) { toast("Agent Zero is still working on the last message."); return; }
  if (!agentZeroInstalled) return handOffToAgentZero(text);
  if (!state.current) {
    const chat = { id: Date.now(), title: text.slice(0, 40), msgs: [] };
    state.ephemeral.unshift(chat); state.current = chat;
  }
  const c = state.current;
  c.msgs.push({ r: "user", t: text });
  const pend = { r: "ai", pending: true, t: "", a0: { status: "Agent Zero is working…", steps: [] } };
  c.msgs.push(pend);
  renderThread(); renderConvs();
  a0Busy = true;
  const steps = new Map();
  let ctx = c.a0ctx || "";
  let from = 0, final = "", idle = 0, loopWarned = false;
  const started = Date.now();
  const paint = (head) => {
    const list = [...steps.values()].sort((x, y) => (x.no || 0) - (y.no || 0));
    pend.a0.status = head || "";
    pend.a0.steps = a0StepRows(list.filter((x) => x.type !== "response"));
    pend.t = final || "";
    if (loopWarned) pend.warn = A0_LOOP_HINT;
    renderThread();
    return list;
  };
  try {
    const a = await a0Post("ask", { text, context: ctx });
    ctx = a.context || ctx; c.a0ctx = ctx;
    for (;;) {
      await new Promise((res) => setTimeout(res, 1500));
      let p;
      try { p = await a0Post("poll", { context: ctx, from }); }
      catch (e) { if (++idle > 20) throw e; continue; }
      idle = 0;
      for (const st of p.steps || []) steps.set(st.no != null ? st.no : steps.size, st);
      if (p.next != null) from = p.next;
      if (p.final) final = p.final;
      const secs = Math.round((Date.now() - started) / 1000);
      const list = paint(final ? "" : "Agent Zero is working… (" + secs + " s, " + steps.size + " steps)");
      if (!loopWarned && a0Looping(list)) { loopWarned = true; toast(A0_LOOP_HINT, "warn"); paint(""); }
      if (final && !p.busy) break;
      if (Date.now() - started > 30 * 60 * 1000) { pend.warn = "Agent Zero is still working after 30 minutes; see the Agent window."; break; }
    }
    paint("");
    if (!final) pend.t = "Agent Zero finished without a final answer. See the Agent window.";
  } catch (e) {
    if (e.status === 503 || e.status === 401) {
      pend.a0.status = ""; pend.t = "**Agent Zero:** " + (e.message || "not running");
      pend.warn = "Your message is on the clipboard; the Agent window opens so you can paste it.";
      handOffToAgentZero(text);
    } else {
      pend.a0.status = ""; pend.t = "**Agent Zero:** " + (e.message || e);
      pend.warn = "Agent Zero did not finish. Open the Agent window for details.";
    }
  } finally {
    pend.pending = false;
    a0Busy = false;
    renderThread(); renderConvs();
  }
}
document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest('a[href="#agent"]');
  if (!a) return;
  e.preventDefault();
  a0OpenFull();
});
async function send() {
  {
    const raw = $("#input").value;
    if (!state.attach.length && openFastPath(raw)) {
      $("#input").value = "";
      autosize();
      toast("Opened " + openFastPathId(raw));
      return;
    }
    if (state.a0 && raw.trim() && !state.attach.length) {
      $("#input").value = "";
      autosize();
      return sendToAgentZero(raw.trim());
    }
  }
  {
    const route = appAgentOn ? appAgentRoute($("#input").value) : null;
    appAgentSkipOnce = false;
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
if ($("#a0Toggle")) $("#a0Toggle").onclick = () => {
  state.a0 = !state.a0;
  $("#a0Toggle").setAttribute("aria-pressed", state.a0);
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
// Desktop layout (0.5.6): Settings and Models are desktop windows, so the
// modal stays hidden and desktop.js shows the right window instead.
const deskOn = () => !!(window.stickDesk && window.stickDesk.active && window.stickDesk.active());
const settingsModal = () => $(".setShell") || $(".modal:not(.small):not(.fp)");
// Hamburger follows Settings panel width (WinBox / modal), not the browser viewport.
const SET_NARROW_PX = 820;
function settingsNarrow() {
  const m = settingsModal();
  return !!(m && m.classList.contains("setNarrow"));
}
function syncSettingsNarrow() {
  const m = settingsModal();
  if (!m) return;
  const w = m.clientWidth;
  // Hidden / not laid out yet: keep prior class until a real width is known.
  if (w <= 0) return;
  const narrow = w <= SET_NARROW_PX;
  const was = m.classList.contains("setNarrow");
  m.classList.toggle("setNarrow", narrow);
  if (!narrow && was) setNavMenuOpen(false);
}
function watchSettingsWidth() {
  const m = settingsModal();
  if (!m || m._setNarrowRO) return;
  const ro = new ResizeObserver(() => syncSettingsNarrow());
  m._setNarrowRO = ro;
  ro.observe(m);
  syncSettingsNarrow();
}
function setNavButtons() {
  return $$(".setNav [data-sec]").filter((b) => getComputedStyle(b).display !== "none");
}
function setNavMenuOpen(open) {
  const m = settingsModal();
  if (!m) return;
  m.classList.toggle("setNavOpen", !!open);
  const btn = $("#setNavBtn");
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    const cur = $(".setNav [data-sec].on") || setNavButtons()[0];
    cur?.focus();
  }
}
function pickSetSec(sec, { closeMenu = true } = {}) {
  showSec(sec);
  if (sec === "models" || sec === "downloads") refreshModels().catch((e) => toast(e.message));
  if (sec === "storage") refreshStorage().catch(() => {});
  if (["devices", "network", "system", "about"].includes(sec)) refreshStatus().catch(() => {});
  if (sec === "chats") { renderSaved(); refreshChatStore().catch(() => {}); }
  refreshSecLive(sec);
  if (closeMenu) setNavMenuOpen(false);
}
function openSettings(sec = "general") {
  const desk = deskOn();
  lastFocus = document.activeElement; if (!desk) $("#settings").hidden = false; $("#statusPop").hidden = true;
  if (mobile()) toggleNav(false);
  watchSettingsWidth();
  syncSettingsNarrow();
  // Narrow Settings uses a hamburger drawer; always show the section body.
  showSec(sec === "__nav" ? "general" : sec, true);
  setNavMenuOpen(sec === "__nav" && settingsNarrow());
  if (sec === "models" || sec === "downloads") refreshModels().catch((e) => toast(e.message));
  if (sec === "storage") refreshStorage().catch((e) => showError(e, "Storage"));
  if (sec === "devices" || sec === "network" || sec === "system" || sec === "about")
    refreshStatus().catch(() => {});
  if (sec === "chats") { renderSaved(); refreshChatStore().catch(() => {}); }
  refreshSecLive(sec === "__nav" ? "general" : sec);
  if (desk && window.stickDesk.onSettings) window.stickDesk.onSettings(sec === "__nav" ? "general" : sec);
}
function showSec(sec, open = true) {
  // Only sections that share a container switch: in the desktop layout the
  // Models window holds Models + Downloads, the Settings window the rest.
  const target = $("#sec-" + sec);
  if (!target) return;
  const scope = target.parentNode || document;
  $$(".sec", scope).forEach((s) => (s.hidden = s.id !== "sec-" + sec));
  if (!target.closest(".setScroll")) {
    $$("[data-desk-sec]").forEach((b) => b.classList.toggle("on", b.dataset.deskSec === sec));
    scope.scrollTop = 0;
    return;
  }
  $$(".setNav [data-sec]").forEach((b) => {
    b.classList.toggle("on", b.dataset.sec === sec);
    b.setAttribute("aria-current", b.dataset.sec === sec ? "page" : "false");
  });
  $("#secTitle").innerHTML = $("#sec-" + sec).dataset.title;
  settingsModal()?.classList.toggle("secOpen", open);
  const sc = $(".setScroll");
  if (sc) sc.scrollTop = 0;
}
function closeSettings() {
  setNavMenuOpen(false);
  $("#settings").hidden = true;
  if (deskOn() && window.stickDesk.onSettingsClose) window.stickDesk.onSettingsClose();
  lastFocus?.focus?.();
}
$$("[data-open]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openSettings(b.dataset.open); }));
$$(".setNav [data-sec]").forEach((b) => (b.onclick = () => pickSetSec(b.dataset.sec)));
$$("[data-sec-go]").forEach((b) => (b.onclick = () => {
  if (deskOn()) { openSettings(b.dataset.secGo); return; }
  pickSetSec(b.dataset.secGo);
}));
$("#setClose").onclick = closeSettings;
$("#setBack").onclick = () => setNavMenuOpen(true);
$("#setNavBtn").onclick = (e) => {
  e.stopPropagation();
  const m = settingsModal();
  setNavMenuOpen(!(m && m.classList.contains("setNavOpen")));
};
$(".setNav")?.addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const bs = setNavButtons();
  const i = bs.indexOf(document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const n = bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length];
  n.focus();
  // Keep the hamburger open while arrowing through sections; click still closes.
  const keep = settingsModal()?.classList.contains("setNavOpen");
  pickSetSec(n.dataset.sec, { closeMenu: !keep });
});
// Wide layout: ↑/↓ move sections while Settings is open, unless focus is in a
// field or the scrollable section body (those keep normal caret / scroll).
window.addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  const t = e.target;
  if (!t || !t.closest) return;
  if (t.closest("input, textarea, select, [contenteditable=true]") || t.isContentEditable) return;
  if (t.closest(".setScroll")) return;
  if ($(".setNav")?.contains(t)) return; // setNav listener owns these
  const settingsEl = $("#settings");
  const m = settingsModal();
  const settingsVisible = (settingsEl && !settingsEl.hidden) ||
    (deskOn() && m && document.body.contains(m));
  if (!settingsVisible || !m) return;
  // Narrow: ↑/↓ only while the hamburger drawer is open; wide: always.
  if (settingsNarrow() && !m.classList.contains("setNavOpen")) return;
  const bs = setNavButtons();
  if (!bs.length) return;
  const cur = bs.findIndex((b) => b.classList.contains("on"));
  const i = cur < 0 ? 0 : cur;
  e.preventDefault();
  const n = bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length];
  n.focus();
  pickSetSec(n.dataset.sec, { closeMenu: !m.classList.contains("setNavOpen") });
});
document.addEventListener("click", (e) => {
  const m = settingsModal();
  if (!m || !m.classList.contains("setNavOpen")) return;
  if (m.contains(e.target) && (e.target.closest(".setNav") || e.target.closest("#setNavBtn"))) return;
  setNavMenuOpen(false);
});
$("#settings").onclick = (e) => { if (e.target.id === "settings") closeSettings(); };
watchSettingsWidth();

let cfCb;
// 0.6.2: no typed magic words anywhere. A plain confirm is two buttons; a
// destructive one (delete, wipe, recovery phrase) adds a checkbox that
// enables the button. `word` is kept only to mark those (see CF_CHECK).
const CF_CHECK = {
  "ARE YOU SURE": "I understand these files are deleted for good",
  "WIPE-OK": "I understand wrong passcodes can destroy the vault",
  "SAVED": "I have written down the recovery phrase",
  "REMOVE": "",
};
function confirmBox({ title, text, word, check, ok = "Delete", extra, cb, noCancel = false, danger = true }) {
  $("#cfTitle").textContent = title; $("#cfText").textContent = text;
  const label = check || (word && CF_CHECK[word]) || "";
  const row = $("#cfCheckRow");
  if (row) row.hidden = !label;
  if ($("#cfCheckLabel")) $("#cfCheckLabel").textContent = label;
  if ($("#cfCheck")) $("#cfCheck").checked = false;
  $("#cfOk").textContent = ok; $("#cfOk").disabled = !!label;
  $("#cfOk").className = danger ? "btn danger" : "btn primary";
  if ($("#cfCancel")) $("#cfCancel").hidden = !!noCancel;
  $("#cfExtra").hidden = !extra; $("#cfExtra").textContent = extra || "";
  cfCb = cb; $("#confirm").hidden = false; setTimeout(() => (label ? $("#cfCheck") : $("#cfOk")).focus(), 20);
}
if ($("#cfCheck")) $("#cfCheck").onchange = () => ($("#cfOk").disabled = !$("#cfCheck").checked);
$("#cfCancel").onclick = () => { $("#confirm").hidden = true; if ($("#cfCancel")) $("#cfCancel").hidden = false; };
$("#cfOk").onclick = () => {
  $("#confirm").hidden = true;
  if ($("#cfCancel")) $("#cfCancel").hidden = false;
  $("#cfOk").className = "btn danger";
  cfCb?.();
};

/** Recovery phrase after vault create: tick + Continue only (no Cancel). */
function showRecoveryPhraseOnce(phrase) {
  return new Promise((resolve) => {
    confirmBox({
      title: "Save your recovery phrase",
      text: "This is the only time it's shown. Write it down and keep it somewhere safe.",
      extra: phrase || "(no phrase in response — check stick logs)",
      ok: "Continue",
      check: "I wrote down the recovery phrase.",
      noCancel: true,
      danger: false,
      cb: resolve,
    });
  });
}

function setupWizardShowing() {
  return !!$("#setupWizard")?.classList.contains("show");
}
function dismissSetupWizard() {
  const overlay = $("#setupWizard");
  if (overlay) overlay.classList.remove("show");
  setSetupChrome(false);
  try { showVaultCreating(false); } catch (_) {}
  try {
    const next = $("#setupNext");
    if (next) next.disabled = false;
  } catch (_) {}
}
/** Unstick create/unlock wizard when the vault is already open or create hung.
 * Never dismiss the wizard past recovery / System ready — that caused first-boot
 * to jump straight to the desktop A0 panel with no recovery phrase. */
async function rescueStuckVaultWizard() {
  if (!setupWizardShowing()) return false;
  let busyOn = false;
  try {
    const busy = $("#vaultCreatingOverlay");
    busyOn = !!(busy && busy.classList.contains("show"));
  } catch (_) {}
  // Do not interrupt an in-flight create/unlock busy overlay (recovery phrase still pending).
  if (busyOn) return false;
  let st = null;
  try { st = await refreshSetupState(true); } catch (_) { st = null; }
  const unlocked = !!(st && st.vault_unlocked) || !!state.vaultOpen;
  // Re-enable Continue so the wizard's own create/unlock handler can advance
  // (recovery → System ready). Do not markSetupDone or dismiss here.
  try {
    const next = $("#setupNext");
    if (next && next.disabled) next.disabled = false;
  } catch (_) {}
  if (unlocked) {
    try { showVaultCreating(false); } catch (_) {}
    return false;
  }
  // Hung create: Continue disabled, blob already on disk → switch form to unlock wording only.
  const title = (($("#setupTitle") && $("#setupTitle").textContent) || "").toLowerCase();
  const onVaultPassStep = /vault passcode|unlock vault/.test(title);
  if (onVaultPassStep && st && (st.blob || st.vault_configured)) {
    try { showVaultCreating(false); } catch (_) {}
    return false;
  }
  return false;
}
function setSetupChrome(on) {
  document.body.classList.toggle("setup-active", !!on);
  try {
    if (on && window.stickDesk && window.stickDesk.closeAll) window.stickDesk.closeAll();
  } catch (_) {}
}
/** True while first-boot wizard (or unlock-only) is on screen — no Agent Zero yet. */
function setupBlocksAgent() {
  if (setupWizardShowing() || document.body.classList.contains("setup-active")) return true;
  return !setupDone();
}

/** After create/unlock: vault mode + chrome. Never auto-start Agent Zero —
 * opening A0 at wizard end / first paint breaks first-boot; user opens it later. */
async function enterVaultModeNow(opts) {
  const quiet = !!(opts && opts.quiet);
  const duringSetup = !!(opts && opts.duringSetup) || setupWizardShowing();
  setVaultChrome(true);
  state.vaultOpen = true;
  try { await setSessionMode("vault", { quiet: quiet || duringSetup || sessionMode === "vault" }); } catch (_) {}
  if (duringSetup || !setupDone()) return;
  try { window.dispatchEvent(new CustomEvent("stickllm:vault-unlocked")); } catch (_) {}
  try { await refreshAgentLink(); } catch (_) {}
}

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
  if (!n || !(Number(hwInfo.vram) > 0)) return `Detected: no GPU (CPU only) · RAM ${ram}`;
  // 0.5.6: Vulkan (AMD/Intel) runs a model on ONE card: show that card's VRAM, never a sum.
  if (hwInfo.backend === "vulkan") {
    const each = fitGb(hwInfo.vramEach || hwInfo.vram);
    return n > 1
      ? `Detected: ${n}× ${name} (Vulkan) · ${each} VRAM each, a model uses one card · RAM ${ram}`
      : `Detected: ${name} (Vulkan) · ${each} VRAM · RAM ${ram}`;
  }
  if (n > 1) {
    const each = Number(hwInfo.vramEach) || 0;
    const split = each ? ` (${n}× ${fitGb(each)})` : "";
    return `Detected: ${n}× ${name} · ${fitGb(hwInfo.vram)} VRAM${split} · RAM ${ram}`;
  }
  return `Detected: ${hwInfo.gpu ? hwInfo.gpu + " " : ""}${fitGb(hwInfo.vram)} VRAM · RAM ${ram}`;
}
function llamaStarting() {
  const s = String(lastLlama?.active_state || "");
  return s === "activating" || (s === "active" && !lastLlama?.stopped);
}
// Where an installed model's file lives: the baked base model is on the stick even
// in a vault session.
function modelWhere(m) {
  const p = String(m.path || m.location || "");
  if (p.startsWith("/opt/stickllm/")) return "stick";
  if (p.includes("/mnt/stickllm-host") || p.includes("host-ssd")) return "host SSD";
  if (p.includes("vault")) return "vault";
  if (!p && sessionMode === "vault") return "vault";
  return "stick";
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
  const vk = hw.backend === "vulkan";
  // Vulkan plans one card (no cross-card split): the pool is that card's VRAM.
  const pool = vk ? (Number(hw.vramEach) || Number(hw.vram) || 0) : (Number(hw.vram) || 0);
  const each = Number(hw.vramEach) || pool;
  const cards = vk ? 1 : Math.max(1, Number(hw.gpuCount) || 1);
  const ram = Number(hw.ram) || 0;
  const size = fitGb(need);
  // 0.5.6 RAM check: whatever does not fit in VRAM runs from system RAM.
  const spill = Math.max(0, gb * 1.1 - pool);
  const ramShort = ram > 0 && spill > 0 && spill + 1 > ram;
  const ramNote = ramShort ? ` · needs ~${fitGb(spill + 1)} RAM, ${fitGb(ram)} free` : "";
  if (pool > 0 && cards > 1 && each > 0 && need <= each) return { k: "gpu", need, kv, label: `Fits on 1 GPU · ${size}`, cls: "fit-ok" };
  if (pool > 0 && need <= pool) return { k: "gpu", need, kv, label: cards > 1 ? `Fits on ${cards} GPUs · ${size}` : `Fits in VRAM · ${size}`, cls: "fit-ok" };
  if (pool <= 0) {
    if (ram > 0 && need + 1.5 <= ram) return { k: "offload", need, kv, label: `CPU only · ${size} in RAM`, cls: "fit-warn" };
    return { k: "no", need, kv, label: ram > 0 ? `Not enough RAM · needs ${size}, ${fitGb(ram)} free` : `Won't fit · needs ${size}`, cls: "fit-no" };
  }
  if (!ramShort && need <= pool + ram - 2) return { k: "offload", need, kv, label: `Partial · ${fitGb(pool)} in VRAM`, cls: "fit-warn" };
  return { k: "no", need, kv, label: ramShort ? `Won't fit${ramNote}` : `Won't fit · needs ${size}`, cls: "fit-no" };
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
  const total = Math.max(1, (hwInfo.backend === "vulkan" ? hwInfo.vramEach : 0) || hwInfo.vram || Number(hwInfo.ram) || 1);
  const wPct = Math.min(100, (gb / total) * 100);
  const kvPct = Math.min(100 - wPct, (fit.kv / total) * 100);
  const freePct = Math.max(0, 100 - wPct - kvPct);
  if ($("#vW")) $("#vW").style.width = wPct + "%";
  if ($("#vKV")) $("#vKV").style.width = kvPct + "%";
  if ($("#vFree")) $("#vFree").style.width = freePct + "%";
  if ($("#lW")) $("#lW").textContent = gb ? gb.toFixed(1) + " GB" : "—";
  if ($("#lKV")) $("#lKV").textContent = fit.kv.toFixed(1) + " GB";
  if ($("#lFree")) $("#lFree").textContent = Math.max(0, total - gb - fit.kv).toFixed(1) + " GB";
  if ($("#vramTotal")) $("#vramTotal").textContent = `of ${fitGb(total)}${hwInfo.backend === "vulkan" && hwInfo.gpuCount > 1 ? " (one card)" : !(hwInfo.vram > 0) ? " RAM" : ""}`;
  if ($("#vramWarn")) $("#vramWarn").hidden = fit.k !== "no";
}
// A search hit for a file the catalog already lists (server sets id = catalog id,
// e.g. the baked base 7B Q4) shows as that catalog row: one card with its
// installed/running/Delete state, not an hf: duplicate.
function searchRows() {
  const seen = new Set();
  const out = [];
  for (const h of hfHits) {
    const row = lastCatalog.find((x) => x.id === h.id || (h.catalog_id && x.id === h.catalog_id));
    const m = row ? { ...h, ...row, hf_id: h.hf_id || h.id, repo: h.repo, file: h.file, sha256: h.sha256 || "", hf: true } : h;
    if (seen.has(m.id)) continue;
    seen.add(m.id);
    out.push(m);
  }
  return out;
}
function browseSource() {
  const q = (state.mf.q || "").trim();
  if (state.mtab === "browse" && q.length >= 2) return searchRows();
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
  const cantIds = new Set();
  for (const m of rows) {
    const nm = String(m.name || m.id || "");
    const sz = Number(m.approx_size_gb || m.size_gb || 0);
    if (m.cant_load || (sz > 0 && sz < 0.1) || /vocab|mtp|nextn|expert|mmproj|qwen4exp/i.test(nm)) {
      cantIds.add(m.id || m.path || m.name);
    }
  }
  state._cantLoadRows = rows.filter((m) => cantIds.has(m.id || m.path || m.name));
  rows = rows.filter((m) => !cantIds.has(m.id || m.path || m.name));
  const order = { gpu: 0, offload: 1, no: 2 };
  // 0.5.6: installed models always come first (then the chosen sort).
  const have = (m) => Number(!m.installed);
  // 0.6.1 (item 19): when models exist on an SSD/vault, installed USB-stick
  // models go to the bottom and get a red "Slow USB load" label.
  const fastDisk = rows.some((m) => m.installed && modelWhere(m) !== "stick");
  const slowUsb = (m) => Number(fastDisk && !!m.installed && modelWhere(m) === "stick");
  rows.sort((a, b) => {
    if (slowUsb(a) !== slowUsb(b)) return slowUsb(a) - slowUsb(b);
    if (state.mf.sort === "running") {
      const rank = (m) => (m.running ? 0 : m.active ? 1 : 2);
      return (rank(a) - rank(b)) || (have(a) - have(b)) || String(a.name || a.id).localeCompare(String(b.name || b.id));
    }
    if (have(a) !== have(b)) return have(a) - have(b);
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
    // An active row only shows Loading while llama-server is actually starting;
    // a stopped or crashed server must not leave the card stuck on "Loading…".
    const loading = !run && (loadingModelId === id || (!loadingModelId && !!m.active && llamaStarting()));
    const rec = !!m.recommended;
    const sel = id === selectedModelId;
    const trust = modelTrust(m);
    const t = TRUST[trust];
    const fit = fitOf(m);
    const where = modelWhere(m);
    let actions = "";
    const delBtn = m.deletable
      ? `<button class="btn sm danger ghost" data-delf="${esc(id)}" type="button" title="Permanently delete model files">Delete</button>`
      : "";
    if (trust === "blocked") {
      actions = delBtn;
    } else if (have) {
      actions = `<span class="pill ok">installed</span><button class="btn sm primary" data-load="${esc(id)}" type="button" ${fit.k === "no" && m.runnable === false ? "disabled" : ""}>${run ? "Running" : loading ? "Loading…" : "Load"}</button>${run || loading ? `<button class="btn sm ghost" data-unload="${esc(id)}" type="button" title="Stop this model (chat and the app agent have no model until you load one)">Unload</button>` : ""}${delBtn}`;
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
        <div class="mcName"><b>${esc(name)}</b><small>${esc(q)} · ${have ? gbTxt + " on disk" : "~" + gbTxt}${have && !(fastDisk && where === "stick") ? " · on " + where : ""}${rec ? " · recommended" : ""}${have && fastDisk && where === "stick" ? ' <span class="pill slowUsb" title="Loads from the USB stick; a copy on the SSD loads much faster">Slow USB load</span>' : ""}</small></div>
        ${run ? '<span class="pill ok">running</span>' : ""}${loading ? '<span class="pill warn">loading</span>' : ""}${rec ? '<span class="pill acc">recommended</span>' : ""}
      </div>
      <div class="tags"><span class="trust ${t.c}" title="${t.d}">${t.l}</span>${visionTag(m, id)}${isAbliterated(m) ? '<span class="pill abl">⚠ uncensored</span>' : ""}<span class="pill cap">GGUF</span></div>
      <div class="mcFoot">
        <span class="fit ${fit.cls}" title="Needs ~${fit.need.toFixed(1)} GB">${fit.label}</span>${m.ram_warning && fit.k !== "no" ? `<span class="pill warn" title="${esc(m.ram_warning)}">low RAM</span>` : ""}${m.arch_warning ? `<span class="pill warn" title="${esc(m.arch_warning)}">experimental</span>` : ""}
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
  $$("#modelList [data-unload]").forEach((b) => (b.onclick = async (e) => {
    e.stopPropagation();
    b.disabled = true;
    b.textContent = "Unloading…";
    try {
      await control("model_unload", {});
      loadingModelId = null;
      toast("Model unloaded. Load one when you want to chat.");
    } catch (err) {
      toast(`Unload failed: ${err.message || err}`);
    }
    refreshModelsNow();
  }));
  $$("#modelList [data-delf]").forEach((b) => (b.onclick = (e) => {
    e.stopPropagation();
    selectedModelId = b.dataset.delf;
    askDeleteModel(findModel(b.dataset.delf));
  }));
  const cant = state._cantLoadRows || [];
  if (cant.length && state.mtab === "local") {
    const box = document.createElement("div");
    box.className = "cant-load-group";
    box.innerHTML = "<details><summary>Can't load on this system (" + cant.length + ")</summary>" +
      cant.map((m) => "<div class=\"model muted small\"><b>" + esc(m.name || m.id || "") + "</b> — " + esc(m.cant_load_reason || m.arch_warning || "unsupported or not a full model") + "</div>").join("") +
      "</details>";
    $("#modelList")?.appendChild(box);
  }
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
  try { updateDynamicPresets(m); } catch (_) {}
  if ($("#ctx")) {
    $("#ctx").max = max;
    if (+$("#ctx").value > max) $("#ctx").value = max;
    if ($("#ctxVal")) paintCtxVal();
    try { syncPresetHighlight(); } catch (_) {}
  }
  updateVramBar(m);
}
function findModel(id) {
  const q = (state.mf.q || "").trim();
  if (state.mtab === "browse" && q.length >= 2) {
    const hit = searchRows().find((x) => x.id === id || x.hf_id === id);
    if (hit) return hit;
  }
  return lastCatalog.find((x) => x.id === id) || hfHits.find((x) => x.id === id);
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
  const gpuCount = Number(st.gpu_count ?? (Array.isArray(st.gpus) ? st.gpus.length : 0)) || 0;
  // No made-up defaults (0.5.6): an unknown or GPU-less host shows 0 GB VRAM, not 24.
  const vram = Number(st.vram_gb || probe.vram_gb || 0) || 0;
  hwInfo = {
    vram,
    vramEach: Number(st.vram_each_gb) || (gpuCount > 1 ? vram / gpuCount : vram),
    gpuCount,
    planCount: Number(st.gpu_plan_count || gpuCount) || 0,
    backend: String(st.gpu_backend || st.backend || ""),
    ram: Number(st.ram_gb || hwInfo.ram) || 0,
    gpu: String(st.gpu || probe.gpu || hwInfo.gpu || ""),
    name: "This machine",
  };
  hwWarnings = Array.isArray(st.hw_warnings) ? st.hw_warnings.filter((w) => typeof w === "string" && w) : [];
  if (hwWarnings.length && !hwWarnToasted) {
    hwWarnToasted = true;
    toast(hwWarnings[0]);
  }
  if ($("#recGpuLabel")) {
    $("#recGpuLabel").textContent = !gpuCount ? "Recommended for this PC"
      : hwInfo.backend === "vulkan" ? "Recommended for one card" : gpuCount > 1 ? `Recommended for these ${gpuCount} GPUs` : "Recommended for this GPU";
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
  // 0.6.5: Minimum 32k / Balanced 64k / Long 128k (Agent Zero wants >= 32K).
  fast: { ctx: 32768, kv: "q8", temp: 0.7 },
  balanced: { ctx: 65536, kv: "f16", temp: 0.7 },
  long: { ctx: 131072, kv: "q8", temp: 0.6 },
};
// Presets follow free VRAM for the selected model; floor stays 32K when it fits.
const KV_MUL = { f16: 1, q8: 0.53, q4: 0.28 };
const CTX_STEPS = [2048, 4096, 8192, 16384, 32768, 65536, 131072];
function vramPoolGb() {
  const hw = hardwarePool();
  return hw.backend === "vulkan" ? (Number(hw.vramEach) || Number(hw.vram) || 0) : (Number(hw.vram) || 0);
}
// Largest context (tokens) whose KV cache fits next to the weights.
function ctxThatFits(m, kv, poolGb = vramPoolGb()) {
  const gb = modelGb(m || {}) || Number(m?.min_vram_gb || 0) || 4;
  const perTok = (gb / 8) / 8192 * (KV_MUL[kv] || 1);
  const left = poolGb - gb - 1;
  if (!(poolGb > 0) || left <= 0 || perTok <= 0) return 0;
  return Math.floor(left / perTok);
}
function roundCtxDown(n) { let r = 0; for (const s of CTX_STEPS) if (s <= n) r = s; return r; }
function pickCtx(m, target, kvs, max, poolGb) {
  for (const kv of kvs) {
    const c = Math.min(max, roundCtxDown(ctxThatFits(m, kv, poolGb)));
    if (c >= Math.min(target, max)) return { ctx: Math.min(target, max), kv };
  }
  const kv = kvs[kvs.length - 1];
  return { ctx: Math.max(2048, Math.min(max, roundCtxDown(ctxThatFits(m, kv, poolGb)))), kv };
}
function dynamicPresets(m, poolGb = vramPoolGb()) {
  const max = Number(m?.ctx_max || m?.ctxMax || 131072) || 131072;
  if (!(poolGb > 0)) {
    return { fast: { ctx: Math.min(32768, max), kv: "q8", temp: 0.7 },
             balanced: { ctx: Math.min(65536, max), kv: "f16", temp: 0.7 },
             long: { ctx: Math.min(131072, max), kv: "q4", temp: 0.6 } };
  }
  return {
    fast: { ...pickCtx(m, 32768, ["q8", "f16", "q4"], max, poolGb), temp: 0.7 },
    balanced: { ...pickCtx(m, 65536, ["f16", "q8", "q4"], max, poolGb), temp: 0.7 },
    long: { ...pickCtx(m, 131072, ["q8", "q4"], max, poolGb), temp: 0.6 },
  };
}
function ctxLabel(n) { return n >= 1024 ? Math.round(n / 1024) + "k" : String(n); }
function updateDynamicPresets(m) {
  const d = dynamicPresets(m);
  for (const k of Object.keys(d)) {
    TUNE_PRESETS[k] = d[k];
    const sm = document.querySelector(`#presets button[data-preset="${k}"] small`);
    if (sm) sm.textContent = `${ctxLabel(d[k].ctx)} ctx · ${d[k].kv} KV · temp ${d[k].temp}`;
  }
}
// 0.6.1 (item 17): before Load, check model + context fits; offer a smaller
// KV cache or the largest context that fits instead of failing in llama.cpp.
function preloadFit(m, ctx, kv, poolGb = vramPoolGb()) {
  if (!(poolGb > 0)) return { ok: true };
  const fitsAt = (k) => ctxThatFits(m, k, poolGb) >= ctx;
  if (fitsAt(kv)) return { ok: true };
  for (const k of ["q8", "q4"]) {
    if ((KV_MUL[k] < (KV_MUL[kv] || 1)) && fitsAt(k)) return { ok: false, kv: k, ctx };
  }
  const best = roundCtxDown(ctxThatFits(m, "q4", poolGb));
  return { ok: false, kv: "q4", ctx: best >= 2048 ? best : 0 };
}
const TUNE_KEY = "stickllm_tune";
const LLAMA_CTX_FLOOR = 32768; // below this, show the Agent Zero hint (llama-start honours the value)
function tuneNow() {
  const num = (sel, d) => { const el = $(sel); const v = el ? Number(el.value) : NaN; return Number.isFinite(v) ? v : d; };
  return {
    ctx: num("#ctx", 32768), kv: state.kv || "f16", temp: num("#temp", 0.7),
    top_p: num("#topp", 0.9), top_k: num("#topk", 40), repeat_penalty: num("#rep", 1.1), max_tokens: num("#maxtok", CHAT_TOKENS),
  };
}
function paintCtxVal() {
  const v = +$("#ctx").value;
  $("#ctxVal").textContent = v.toLocaleString();
  const note = $("#ctxNote");
  // 0.6.1: visibility, not hidden, so dragging never reflows the panel (the
  // note popping in/out under SwiftShader left a white/checkered box).
  if (note) { note.hidden = false; note.style.visibility = v >= LLAMA_CTX_FLOOR ? "hidden" : "visible"; }
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
  const max = +$("#ctx").max || 131072;
  // 0.6.5: floor context at Minimum (32K) for Agent Zero unless the model max is lower.
  let ctx = Number(t.ctx);
  if (!Number.isFinite(ctx) || ctx < 256) ctx = LLAMA_CTX_FLOOR;
  else if (ctx < LLAMA_CTX_FLOOR && max >= LLAMA_CTX_FLOOR) ctx = LLAMA_CTX_FLOOR;
  set("#ctx", Math.min(ctx, max));
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
// 0.6.1: one repaint per frame while dragging; save + re-fit on release.
let ctxRaf = 0;
$("#ctx").addEventListener("input", () => {
  if (ctxRaf) return;
  ctxRaf = requestAnimationFrame(() => { ctxRaf = 0; paintCtxVal(); syncPresetHighlight(); });
});
$("#ctx").addEventListener("change", () => { paintCtxVal(); syncPresetHighlight(); saveTune(); renderModelsList(); });
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
  {
    const ctx = +$("#ctx").value;
    const pf = preloadFit(m, ctx, state.kv);
    if (!pf.ok) {
      const pool = vramPoolGb().toFixed(0);
      if (pf.ctx === ctx) {
        if (window.confirm(`${ctxLabel(ctx)} context with ${state.kv} KV cache will not fit in ${pool} GB VRAM.\n\nOK = use ${pf.kv} KV cache (fits, slightly lower quality).\nCancel = load anyway (may spill to RAM or fail).`)) {
          setKv(pf.kv); saveTune(); syncPresetHighlight();
        }
      } else if (pf.ctx) {
        if (window.confirm(`${ctxLabel(ctx)} context will not fit in ${pool} GB VRAM with this model.\n\nOK = use ${ctxLabel(pf.ctx)} context with q4 KV cache (largest that fits).\nCancel = load anyway (may spill to RAM or fail).`)) {
          setKv("q4"); $("#ctx").value = Math.min(pf.ctx, +$("#ctx").max || pf.ctx); paintCtxVal(); syncPresetHighlight(); saveTune();
        }
      } else {
        toast(`This model barely fits in ${pool} GB VRAM; it will run partly from RAM (slower).`);
      }
    }
  }
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
    showError(e);
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
  } catch (e) { showError(e); }
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
  } catch (e) { showError(e); }
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
      } catch (e) { showError(e); }
    },
  });
}
$("#delModel").onclick = () => {
  askDeleteModel(lastCatalog.find((x) => x.id === selectedModelId));
};


/** Busy overlay for vault create vs open/unlock. mode: "create" | "open" */
function showVaultCreating(on, mode) {
  let el = $("#vaultCreatingOverlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "vaultCreatingOverlay";
    el.innerHTML = '<div class="vault-creating-card"><div class="spin" aria-hidden="true"></div><div><strong id="vaultBusyTitle">Creating vault, please wait…</strong><div class="muted small" id="vaultBusySub">This can take a few minutes on a USB stick.</div></div></div>';
    document.body.appendChild(el);
  }
  const title = el.querySelector("#vaultBusyTitle");
  const sub = el.querySelector("#vaultBusySub");
  const opening = mode === "open" || mode === "unlock" || mode === "opening";
  if (title) title.textContent = opening ? "Opening vault, please wait…" : "Creating vault, please wait…";
  if (sub) sub.textContent = opening
    ? "Unlocking the encrypted vault file."
    : "This can take a few minutes on a USB stick.";
  el.classList.toggle("show", !!on);
  el.setAttribute("aria-hidden", on ? "false" : "true");
  ["#createVault", "#pickCreate", "#np1", "#np2", "#setupNext"].forEach((sel) => {
    const n = $(sel); if (n) n.disabled = !!on;
  });
}
/** Harden vault passcode inputs so browsers do not offer to save the passcode. */
function hardenVaultPassFields(...nodes) {
  nodes.forEach((n) => {
    if (!n) return;
    try {
      n.setAttribute("type", "text");
      n.classList.add("secret");
      n.setAttribute("autocomplete", "off");
      n.setAttribute("autocapitalize", "off");
      n.setAttribute("autocorrect", "off");
      n.setAttribute("spellcheck", "false");
      n.setAttribute("data-lpignore", "true");
      n.setAttribute("data-1p-ignore", "true");
      n.setAttribute("data-form-type", "other");
      n.setAttribute("name", "stickllm-vault-pass-" + Math.random().toString(36).slice(2, 8));
      // Readonly until focus defeats Chrome's save-password heuristic.
      n.setAttribute("readonly", "readonly");
      const unlock = () => { try { n.removeAttribute("readonly"); } catch (_) {} };
      n.addEventListener("focus", unlock, { once: true });
      n.addEventListener("pointerdown", unlock, { once: true });
    } catch (_) {}
  });
}
/** Wizard vault forms used onsubmit="return false", so Enter never ran Unlock/Continue.
 *  Wire submit + Enter to the same path as the primary setupNext button. */
function wireVaultPassEnterToSetupNext(root) {
  const scope = root && root.querySelector ? root : document;
  const go = () => {
    const btn = $("#setupNext");
    if (btn && !btn.disabled) btn.click();
  };
  const form = scope.querySelector ? scope.querySelector("form") : null;
  if (form && !form.dataset.stickEnterUnlock) {
    form.dataset.stickEnterUnlock = "1";
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      go();
    });
  }
  ["#wizP1", "#wizP2"].forEach((sel) => {
    const n = scope.querySelector ? scope.querySelector(sel) : $(sel);
    if (!n || n.dataset.stickEnterUnlock) return;
    n.dataset.stickEnterUnlock = "1";
    n.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.shiftKey || e.repeat || e.isComposing) return;
      e.preventDefault();
      e.stopPropagation();
      go();
    });
  });
}

async function refreshStorage() {
  if (!(await ensurePaired())) return;
  const ep = vaultEpoch;
  const st = await control("status_light");
  if (ep !== vaultEpoch || vaultBusy()) return; // stale: the vault changed meanwhile
  const v = st.vault || {};
  try { refreshActiveVaultUI(v); } catch (_) {}
  const open = vaultIsOpen(v);
  setVaultChrome(open, vaultIsAbsent(v));
  if ($("#vcSub")) {
    $("#vcSub").textContent = v.blob || v.root || v.path || (vaultIsAbsent(v) ? "No vault attached yet" : (open ? "" : "Enter the passcode to unlock"));
  }
  showVaultOther(!open && !!v.other_computer, v.vault_computer_label);
  const wipe = Number(v.wipe_after_failed_unlocks || 0);
  if ($("#wipeN") && document.activeElement !== $("#wipeN")) $("#wipeN").value = String(wipe);
  await refreshDrivesLive();
  await refreshMovableLive();
  if ($("#deleteVaultPanel")?.open) {
    try { await refreshDeleteVaultList(); } catch (_) {}
  }
}
let vaultStickData = false;  // 0.6.1: user confirmed "store vault on this drive"
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
    // 0.6.3: STICKLLM-DATA is first-class — one card only (no confirm gate / duplicate).
    const sd = res.stick_data;
    const sdHtml = "";
    const stickPaths = new Set();
    if (sd && sd.path) stickPaths.add(String(sd.path).replace(/\/+$/, ""));
    stickPaths.add("/mnt/stickllm-data");
    if (!sel.length && !mountable.length && !blocked.length && !sdHtml) {
      box.innerHTML = '<div class="row"><small>No browsable mounts and no STICKLLM-DATA partition. Use “Use free space on the stick” below, or plug in a drive and mount it.</small></div>';
      return;
    }
    let html = sdHtml;
    const seenMount = new Set();
    for (const d of sel) {
      const path = d.mount_path || d.path || "";
      const norm = String(path).replace(/\/+$/, "");
      if (!path || seenMount.has(norm)) continue;
      if (norm === "/mnt/stickllm-settings" || norm.includes("stickllm-settings")) continue;
      seenMount.add(norm);
      const isStick = stickPaths.has(norm) || d.kind === "usb_stick" || /STICKLLM-DATA/i.test(String(d.label || ""));
      const label = isStick ? "StickLLM stick" : (d.label || path);
      const free = d.free_gb != null
        ? `${d.free_gb} GiB free`
        : (d.avail ? `${d.avail} free` : "");
      const warn = d.warn ? `<small class="muted">${esc(d.warn)}</small>` : "";
      html += `<button class="drive" data-path="${esc(path)}" type="button">
        <div class="dh"><b>${esc(label)}</b></div>
        <small class="mono">${esc(path)}</small>
        <small>${esc(free)} · ${esc(isStick ? "STICKLLM-DATA" : (d.kind || d.fstype || d.fs || ""))}</small>
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
      if (sd && (el.dataset.path === "/mnt/stickllm-data" || el.dataset.path.startsWith("/mnt/stickllm-data/"))) {
        const sb = document.querySelector("[data-stickdata]");
        if (sb && !sb.disabled) { sb.click(); return; }
      }
      vaultPickerMount = el.dataset.path;
      vaultBrowsePath = el.dataset.path;
      $("#vaultPath").value = el.dataset.path;
      pickerPurpose = "vault";
      if ($("#fpTitle")) $("#fpTitle").textContent = "Choose folder / vault";
      openLivePicker(el.dataset.path);
    }));
    $$("[data-stickdata]").forEach((b) => (b.onclick = (e) => {
      e.stopPropagation();
      confirmBox({
        title: "No internal drive found – store vault on this drive?",
        text: (sd && sd.warning) || "The vault becomes an encrypted file on this drive's STICKLLM-DATA partition.",
        word: "STICK-DATA", ok: "Use this drive",
        cb: () => {
          vaultStickData = true;
          $("#vaultPath").value = b.dataset.stickdata;
          toast("Vault folder set to this drive. Choose a passcode and Create vault.");
          $("#np1")?.focus();
        },
      });
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
        refreshModels().catch(() => {});  // 0.6.1 (item 20): models on the new mount
        const mp = res.mount_path || "";
        toast(res.already_mounted ? (`Already mounted${mp ? " at " + mp : ""}`) : (`Mounted${mp ? " at " + mp : ""}`));
      } catch (err) { showError(err, "Mount failed"); }
    }));
  } catch (e) {
    $("#drives").innerHTML = `<div class="row"><small>${esc(e.message)}</small></div>`;
  }
}
async function renderPickerSide() {
  const side = $("#fpSide");
  if (!side) return;
  const cur = vaultBrowsePath || "—";
  let drivesHtml = "";
  try {
    const res = await control("vault_devices");
    const devices = Array.isArray(res.devices) ? res.devices : [];
    const sel = Array.isArray(res.selectable) ? res.selectable : devices.filter((d) => d && d.selectable);
    const seen = new Set();
    for (const d of sel) {
      const path = d.mount_path || d.path || "";
      const norm = String(path).replace(/\/+$/, "");
      if (!path || seen.has(norm)) continue;
      if (norm === "/mnt/stickllm-settings" || norm.includes("stickllm-settings") || norm.startsWith("/dev/mapper/")) continue;
      seen.add(norm);
      const isStick = norm === "/mnt/stickllm-data" || d.kind === "usb_stick" || /STICKLLM-DATA/i.test(String(d.label || ""));
      const free = d.free_gb != null ? d.free_gb + " GiB free" : "";
      drivesHtml += `<button class="fpDrive" type="button" data-fpdrive="${esc(path)}"><span><b>${esc(isStick ? "StickLLM stick" : (d.label || path))}</b><small>${esc(free)}</small></span></button>`;
    }
  } catch (_) {}
  side.innerHTML =
    '<div class="fpSideLab">Available drives</div>' + (drivesHtml || '<small class="muted">No mounted data drives</small>') +
    '<div class="fpSideLab" style="margin-top:12px">Search</div>' +
    '<button class="fpDrive" type="button" id="fpSideSearchVault"><span><b>Search for vault</b><small>stickllm-vault.img on mounts</small></span></button>' +
    '<button class="fpDrive" type="button" id="fpSideSearchModels"><span><b>Search for models</b><small>.gguf folders on this volume</small></span></button>' +
    '<div class="fpSideLab" style="margin-top:12px">Current</div>' +
    '<div class="row"><small class="mono">' + esc(cur) + "</small></div>";
  side.querySelectorAll("[data-fpdrive]").forEach((b) => {
    b.onclick = () => openLivePicker(b.dataset.fpdrive);
  });
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
    await renderPickerSide();
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
        } catch (e) { showError(e); }
      };
    }
    toast(`Found ${list.length} vault file(s)`);
  } catch (e) { showError(e); }
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
  } catch (e) { showError(e); }
}
$("#fpUp").onclick = async () => {
  try {
    const cur = await control("vault_list_dirs", { path: vaultBrowsePath });
    if (cur.parent) await browseLive(cur.parent);
  } catch (e) { showError(e); }
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
    } catch (e) { showError(e); }
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
    } catch (e) { showError(e); }
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
  } catch (e) { showError(e); }
};
$("#fpBackB").onclick = null; $("#fpFwd").onclick = null;

$("#refreshDrives").onclick = () => refreshDrivesLive().then(() => toast("Drives refreshed"));
$("#actClaim").onclick = () => {
  confirmBox({
    title: "Use free space on the stick?",
    text: "Creates a StickLLM data partition on this StickLLM USB stick only. Your own drives are never partitioned.",
    word: "USE-STICK-SPACE", ok: "Use free space",
    cb: async () => {
      // 0.6.1 (item 14): say what happened or why it could not.
      try {
        toast("Setting up stick space…");
        const res = await control("usb_claim");
        if (res && res.ok === false) {
          confirmBox({ title: "Couldn't use free stick space", text: res.error || res.message || "Unknown reason", ok: "OK" });
        } else toast((res && res.message) || "Stick space ready");
        await refreshStorage();
        await refreshDrivesLive().catch(() => {});
      } catch (e) { confirmBox({ title: "Couldn't use free stick space", text: e.message || String(e), ok: "OK" }); }
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
  let fallback = ($("#vaultPath").value || vaultBrowsePath || "").trim();
  if (fallback.startsWith("/mnt/stickllm-settings") || fallback.includes("stickllm-settings")) fallback = "";
  if (fallback.startsWith("/dev/mapper/")) fallback = "";
  const path = (purpose === "models_dir" && start.startsWith("/") && !start.includes("stickllm-settings")) ? start : (fallback || start);
  const applyTitle = () => {
    if ($("#fpTitle")) $("#fpTitle").textContent = title || (purpose === "models_dir" ? "Choose models folder" : "Choose folder / vault");
  };
  if (path && path.startsWith("/") && path !== "…") {
    await openLivePicker(path);
    applyTitle();
    return;
  }
  await refreshDrivesLive();
  let pick = null;
  const buttons = Array.from($$("#drives [data-path]"));
  // Prefer host SSD/HDD, then StickLLM DATA; never settings/crypt.
  pick = buttons.find((b) => {
    const p = b.dataset.path || "";
    return p && !p.includes("stickllm-settings") && !p.startsWith("/dev/mapper/") && p !== "/mnt/stickllm-data";
  }) || buttons.find((b) => (b.dataset.path || "").startsWith("/mnt/stickllm-data")) || buttons[0];
  if (pick) {
    await openLivePicker(pick.dataset.path);
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
    // Keep the typed passcode until unlock succeeds — clearing early made Enter
    // look like "asks for password again" when unlock failed or re-painted.
    const res = await control("vault_unlock", payload);
    if (!res.ok) throw new Error(res.error || res.stderr || "unlock failed");
    try { $("#vaultPass").value = ""; } catch (_) {}
    vaultUnlocking = false;
    toast("Vault unlocked");
    await enterVaultModeNow();
    await refreshStorage();
  } catch (err) {
    vaultUnlocking = false;
    setVaultChrome(false);
    const raw = String(err.message || "");
    if (VAULT_OTHER_RE.test(raw)) {
      const msg = (raw.split(VAULT_OTHER_RE)[1] || "Vault is on another computer.").split("\n")[0].replace(/^stickllm-vault:\s*/, "");
      showVaultOther(true, "");
      unlockMessage(msg);
      toast("Vault is on another computer");
      return;
    }
    unlockMessage("Unlock failed: " + raw);
    showError(raw, "Unlock failed");
  } finally {
    vaultUnlocking = false;
  }
};

$("#createVault").onclick = () => {
  let path = ($("#vaultPath").value || "").trim().replace(/\/+$/, "");
  if (path === "/mnt/stickllm-data") { path = "/mnt/stickllm-data/vault"; $("#vaultPath").value = path; }
  // 0.6.2 hotfix: DATA is first-class — no extra "Store vault on this drive" step.
  if (path === "/mnt/stickllm-data" || path.startsWith("/mnt/stickllm-data/")) vaultStickData = true;
  const size = String($("#vaultSize").value || "32");
  const p1 = $("#np1").value, p2 = $("#np2").value;
  if (!path) return toast("Choose a folder first");
  if (p1.length < 8) return toast("Passcode must be at least 8 characters");
  if (p1 !== p2) return toast("Passcodes don't match");
  confirmBox({
    title: "Create vault?",
    text: `Creates a ${size} GiB encrypted file in ${path}. Never formats your drive.`,
    ok: "Create vault", check: "I understand this creates an encrypted vault file (never formats the drive).",
    cb: async () => {
      try {
        showVaultCreating(true, "create");
        const onStickData = path === "/mnt/stickllm-data" || path.startsWith("/mnt/stickllm-data/");
        const res = await control("vault_setup", {
          path, size_gb: size, confirm: "CREATE-VAULT",
          recovery_confirm: "SHOW-ONCE", passcode: p1, passcode2: p2, space_confirm: "SPACE-OK",
          ...(onStickData ? { stick_data_confirm: "STICK-DATA" } : {}),
        });
        $("#np1").value = $("#np2").value = "";
        showVaultCreating(false);
        if (!res.ok) { const er = new Error(res.error || res.stderr || "setup failed"); er.title = "Could not create vault"; throw er; }
        // 0.6.7: enter vault mode immediately (backend already unlocked), then recovery.
        toast("Vault created");
        await enterVaultModeNow();
        await refreshStorage();
        await showRecoveryPhraseOnce(res.recovery_phrase || "");
        $("#np1").value = $("#np2").value = "";
      } catch (e) { showVaultCreating(false); showError(e); }
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
      } catch (e) { showError(e); }
    },
  });
};
$("#wipeBtn").onclick = () => {
  const n = String($("#wipeN").value || "0");
  if (n === "0") {
    control("vault_set_wipe", { n: "0", confirm: "OFF" }).then(() => toast("Wipe-after-N off")).catch((e) => showError(e));
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
      } catch (e) { showError(e); }
    },
  });
};

/** Label a vault blob path for the Delete vault picker (SSD / USB DATA / …). */
function vaultDeleteLabel(blob, root, source) {
  const p = String(blob || root || "");
  let kind = "Vault";
  if (/\/mnt\/stickllm-data(\/|$)/.test(p) || source === "usb_data_pointer") kind = "USB DATA";
  else if (/\/mnt\/stickllm-host(\/|$)/.test(p) || source === "host_scan") kind = "Host SSD";
  else if (/\/mnt\/stickllm-settings(\/|$)/.test(p) || source === "usb_settings") kind = "USB settings hint";
  else if (source) kind = String(source).replace(/_/g, " ");
  const short = p.length > 64 ? "…" + p.slice(-60) : p;
  return kind + " — " + (short || "(unknown path)");
}

function syncDeleteVaultBtn() {
  const btn = $("#deleteVaultBtn");
  if (!btn) return;
  const sel = $("#deleteVaultSelect");
  const conf = ($("#deleteVaultConfirm")?.value || "").trim();
  const pass = ($("#deleteVaultPass")?.value || "");
  btn.disabled = !(sel && sel.value && pass.length >= 1 && conf === "DELETE_VAULT");
}

async function refreshDeleteVaultList() {
  const sel = $("#deleteVaultSelect");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '<option value="">Searching…</option>';
  syncDeleteVaultBtn();
  const opts = [];
  const seen = new Set();
  const add = (blob, root, source) => {
    const b = String(blob || "").trim();
    if (!b || seen.has(b)) return;
    seen.add(b);
    opts.push({ blob: b, root: root || "", source: source || "" });
  };
  try {
    const st = await control("vault_status");
    if (st && st.blob) add(st.blob, st.root || "", "active");
  } catch (_) {}
  try {
    const res = await control("vault_find");
    const list = Array.isArray(res.candidates) ? res.candidates
      : (Array.isArray(res.hits) ? res.hits : []);
    for (const c of list) {
      add(c.blob || c.path, c.root || "", c.source || c.note || "");
    }
    if (res.best) add(res.best.blob || res.best.path, res.best.root || "", res.best.source || "best");
  } catch (_) {}
  if (!opts.length) {
    sel.innerHTML = '<option value="">No vault file found</option>';
    syncDeleteVaultBtn();
    return;
  }
  sel.innerHTML = opts.map((o) =>
    `<option value="${esc(o.blob)}">${esc(vaultDeleteLabel(o.blob, o.root, o.source))}</option>`
  ).join("");
  if (prev && seen.has(prev)) sel.value = prev;
  syncDeleteVaultBtn();
}

async function deleteVaultAction() {
  const blob = ($("#deleteVaultSelect")?.value || "").trim();
  const pass = $("#deleteVaultPass")?.value || "";
  const conf = ($("#deleteVaultConfirm")?.value || "").trim();
  const msg = $("#deleteVaultMsg");
  if (msg) { msg.hidden = true; msg.textContent = ""; }
  if (!blob) { toast("Select a vault location"); return; }
  if (conf !== "DELETE_VAULT") { toast("Type DELETE_VAULT to confirm"); return; }
  if (!pass) { toast("Vault passcode required"); return; }
  const btn = $("#deleteVaultBtn");
  if (btn) btn.disabled = true;
  // Reuse lock teardown: blank A0 embeds before control stops the agent + LUKS.
  if (vaultBusy()) { toast("Vault busy — wait for unlock/lock to finish"); syncDeleteVaultBtn(); return; }
  vaultLocking = true;
  try { stickllmAutoStartA0 = false; } catch (_) {}
  try {
    if (window.stickDesk && window.stickDesk.prepareForVaultLock) window.stickDesk.prepareForVaultLock();
    else if (window.stickDesk && window.stickDesk.closeAll) window.stickDesk.closeAll();
  } catch (_) {}
  try { clearOnLock(); } catch (_) {}
  try {
    const res = await control("vault_delete", {
      path: blob,
      passcode: pass,
      confirm: "DELETE_VAULT",
    });
    try { $("#deleteVaultPass").value = ""; } catch (_) {}
    try { $("#deleteVaultConfirm").value = ""; } catch (_) {}
    if (!res || res.ok === false) {
      const err = (res && (res.error || res.stderr)) || "delete failed";
      throw new Error(String(err));
    }
    toast("Vault deleted");
    setVaultChrome(false, true);
    try { await refreshStorage(); } catch (_) {}
    try { await refreshDeleteVaultList(); } catch (_) {}
    if (msg) {
      msg.hidden = false;
      msg.textContent = "Blob removed. Create or attach a vault to continue.";
    }
  } catch (e) {
    showError(e, "Could not delete vault");
    syncDeleteVaultBtn();
  } finally {
    vaultLocking = false;
    vaultEpoch += 1;
    syncDeleteVaultBtn();
  }
}

if ($("#deleteVaultConfirm")) $("#deleteVaultConfirm").oninput = syncDeleteVaultBtn;
if ($("#deleteVaultPass")) $("#deleteVaultPass").oninput = syncDeleteVaultBtn;
if ($("#deleteVaultSelect")) $("#deleteVaultSelect").onchange = syncDeleteVaultBtn;
if ($("#deleteVaultRefresh")) $("#deleteVaultRefresh").onclick = () => refreshDeleteVaultList().catch((e) => showError(e));
if ($("#deleteVaultBtn")) $("#deleteVaultBtn").onclick = () => deleteVaultAction();
if ($("#deleteVaultPanel")) {
  $("#deleteVaultPanel").addEventListener("toggle", () => {
    if ($("#deleteVaultPanel").open) refreshDeleteVaultList().catch(() => {});
  });
}
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
          } catch (e) { showError(e); }
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
  } catch (e) { showError(e); }
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
    deleteVaultChat(b.dataset.dc).catch((e) => showError(e));
  }));
}
$("#saveChat").onclick = () => saveCurrentChat(false).catch((e) => showError(e));

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

/** Sticky pair-code prompt on the stick: stays until dismiss or truthful expiry. */
const PAIR_CODE_UI_TTL_MS = 900 * 1000; // matches gateway PAIR_CODE_TTL_SECS
let pairCodeBanner = { code: "", expAt: 0, timer: null };
function dismissPairCodeBanner() {
  if (pairCodeBanner.timer) { clearInterval(pairCodeBanner.timer); pairCodeBanner.timer = null; }
  pairCodeBanner.code = ""; pairCodeBanner.expAt = 0;
  const el = $("#pairCodeBanner");
  if (el) { el.hidden = true; el.setAttribute("hidden", ""); }
}
function ensurePairCodeBanner() {
  let el = $("#pairCodeBanner");
  if (el) return el;
  el = document.createElement("div");
  el.id = "pairCodeBanner";
  el.className = "pairCodeBanner";
  el.hidden = true;
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-live", "polite");
  el.innerHTML = '<div class="pcbInner"><div class="pcbHead"><b>Pair code</b>'
    + '<button type="button" class="pcbX" aria-label="Dismiss">\u00d7</button></div>'
    + '<p class="pcbHint">Enter this code on the LAN browser. It stays until you dismiss it or it expires.</p>'
    + '<div class="pcbCode mono" id="pairCodeBannerDigits"></div>'
    + '<div class="pcbMeta"><span id="pairCodeBannerExp"></span>'
    + '<button type="button" class="btn sm pcbDismiss">Dismiss</button></div></div>';
  document.body.appendChild(el);
  el.querySelector(".pcbX").onclick = dismissPairCodeBanner;
  el.querySelector(".pcbDismiss").onclick = dismissPairCodeBanner;
  return el;
}
function showStickyPairCode(code, opts) {
  if (!detectLocalHost()) return;
  const digits = pairDigits(code);
  if (!digits) return;
  opts = opts || {};
  const el = ensurePairCodeBanner();
  const same = pairCodeBanner.code === digits && pairCodeBanner.expAt > Date.now();
  pairCodeBanner.code = digits;
  if (!same) pairCodeBanner.expAt = Date.now() + (opts.ttlMs || PAIR_CODE_UI_TTL_MS);
  if ($("#pairCodeShow")) $("#pairCodeShow").textContent = formatPairCode(digits);
  const dig = $("#pairCodeBannerDigits");
  if (dig) dig.textContent = formatPairCode(digits);
  el.hidden = false; el.removeAttribute("hidden");
  const tick = () => {
    const left = Math.max(0, pairCodeBanner.expAt - Date.now());
    const exp = $("#pairCodeBannerExp");
    if (exp) {
      if (left <= 0) exp.textContent = "Expired — press F9 or New code for another.";
      else {
        const s = Math.ceil(left / 1000);
        const m = Math.floor(s / 60), r = s % 60;
        exp.textContent = "Expires in " + m + ":" + String(r).padStart(2, "0");
      }
    }
    if (left <= 0) {
      if (pairCodeBanner.timer) { clearInterval(pairCodeBanner.timer); pairCodeBanner.timer = null; }
      // Keep digits visible but mark expired; user must dismiss or remint.
    }
  };
  tick();
  if (pairCodeBanner.timer) clearInterval(pairCodeBanner.timer);
  pairCodeBanner.timer = setInterval(tick, 1000);
}
function showPairCodeOnStick(code) {
  const c = String(code || "").trim();
  // The pair code is only ever painted on the stick's own screen.
  if (!detectLocalHost() || !/^\d{4,8}$/.test(c)) return;
  if ($("#pairCodeShow")) $("#pairCodeShow").textContent = formatPairCode(c);
  showStickyPairCode(c);
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
    showStickyPairCode(digits);
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
  showStickyPairCode(digits);
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
  } catch (e) { showError(e); }
}
function paintSshDetails(connect) {
  const box = $("#sshDetails");
  const line = $("#sshLine");
  if (!box || !line) return;
  const c = connect || {};
  const enabled = !!c.ssh_enabled;
  const pass = String(c.ssh_password || "").trim();
  const local = detectLocalHost();
  // Password only exists on loopback health; LAN never gets it.
  // No one-click Copy — select/highlight manually if needed (0.6.7).
  if (!local || !enabled) {
    box.hidden = true;
    return;
  }
  const user = c.ssh_user || "stickllm";
  const host = c.ssh_host || c.ip || "(LAN IP not up yet)";
  box.hidden = false;
  if (pass) {
    line.textContent = `${user}@${host}  password: ${pass}`;
  } else {
    line.textContent = `SSH is on (${user}@${host}) — password not ready yet; press F10 or wait a moment.`;
  }
}
async function issueSshHotkey() {
  // F10 from any StickLLM screen. The server only returns the password to this UI.
  try {
    const r = await fetch("/api/health", { cache: "no-store", headers: authHeaders() });
    const j = await r.json().catch(() => ({}));
    const c = j.connect || {};
    paintSshDetails(c);
    const pass = String(c.ssh_password || "").trim();
    const enabled = !!c.ssh_enabled;
    const user = c.ssh_user || "stickllm";
    // 0.6.1: real LAN IP only (never 127.0.0.1); say so while the network is not up.
    const host = c.ssh_host || c.ip || "<LAN IP not up yet - press F10 again in a moment>";
    if (enabled && pass) {
      if (detectLocalHost()) toast("SSH details updated under Pair code in Settings");
      else toast("SSH password is only shown on the stick screen");
      try { pushSystemMsg(`SSH: ${user}@${host}  password: ${pass}`); } catch (_) {}
    } else if (enabled) {
      toast("SSH on — password not available here yet");
    } else {
      toast("SSH disabled on this boot (use GRUB Test / Terminal)");
    }
  } catch (e) { showError(e); }
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
  // Desktop layout (0.5.6): Agent is its own window on the desktop.
  if (window.stickDesk && window.stickDesk.handles("agent") && window.stickDesk.openApp("agent")) return;
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
    await afterPairSuccess();
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
    await afterPairSuccess();
  } catch (ex) { err.hidden = false; err.textContent = ex.message; }
};

// ---- 0.5.9: live Settings pages (Network, System) and Settings > Advanced ----
function refreshSecLive(sec) {
  if (sec === "network") {
    refreshNetwork().catch(() => {});
    refreshWebMode().catch(() => {});
  }
  if (sec === "system" || sec === "about") refreshSystemInfo().catch(() => {});
  if (sec === "advanced") refreshAdvanced().catch((e) => toast(e.message || String(e)));
}
async function refreshNetwork() {
  if (!(await ensurePaired())) return;
  const j = await control("net_info");
  const n = (j && j.net) || {};
  const url = n.url || location.origin + "/";
  if ($("#netUrl")) $("#netUrl").textContent = url;
  const parts = [];
  if (n.type) parts.push(n.type + (n.iface ? " (" + n.iface + ")" : ""));
  if (n.type === "WiFi" && n.ssid) parts.push(n.ssid);
  if (n.ip) parts.push(n.ip);
  if ($("#netStatus")) $("#netStatus").textContent = parts.length ? parts.join(" · ") : "No network connection";
  const pill = $("#netPill");
  if (pill) { pill.textContent = n.ip ? "Connected" : "Offline"; pill.className = "pill" + (n.ip ? " ok" : ""); }
  // The SSID box stays empty unless a network was saved on this stick.
  const box = $("#ssid");
  if (box && !box.value && n.ssid) box.value = n.ssid;
}

// 0.6.11: Internet / Tor / No internet — stick Chromium (+ stick-origin fetches).
let webMode = "internet";
function paintWebMode(j) {
  const mode = (j && j.mode) || webMode || "internet";
  webMode = mode;
  const seg = $("#webModeSeg");
  if (seg) {
    seg.querySelectorAll("[data-web]").forEach((b) => {
      const on = b.dataset.web === mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-checked", String(on));
    });
  }
  const st = $("#webModeStatus");
  if (st) {
    let line = (j && j.note) || "";
    if (mode === "tor" && j && !j.tor_ready) line = line || "Tor is starting…";
    st.textContent = line;
    st.hidden = !line;
  }
  try {
    if (window.stickDesk && typeof window.stickDesk.syncWebMode === "function") {
      window.stickDesk.syncWebMode(j || { mode });
    }
  } catch (_) {}
}
async function refreshWebMode() {
  try {
    const r = await fetch("/api/web-mode", { cache: "no-store", headers: authHeaders() });
    const j = await r.json().catch(() => ({}));
    if (r.ok) paintWebMode(j);
    return j;
  } catch (_) {
    return { mode: webMode };
  }
}
async function setWebMode(mode, opts) {
  const quiet = !!(opts && opts.quiet);
  mode = String(mode || "").toLowerCase();
  if (!["internet", "tor", "none"].includes(mode)) throw new Error("Web mode must be internet, tor, or none");
  if (!quiet) toast(mode === "tor" ? "Starting Tor…" : mode === "none" ? "Blocking stick browser web…" : "Using normal internet…");
  const j = await control("web_mode_set", { mode });
  paintWebMode(j);
  if (!j.ok) throw new Error(j.error || j.note || "Web mode failed");
  if (!quiet) {
    if (mode === "tor" && !j.tor_ready) toast("Tor starting — verifying a Tor exit…");
    else if (mode === "tor") toast("Tor verified — Agent Zero and StickLLM apps use Tor for the internet");
    else if (mode === "none") toast("No internet — public web blocked in Browser");
    else toast("Internet — normal uplink");
  }
  return j;
}
$$("#webModeSeg [data-web]").forEach((b) => {
  b.onclick = () => setWebMode(b.dataset.web).catch((e) => toast(e.message || String(e)));
});
async function refreshSystemInfo() {
  if (!(await ensurePaired())) return;
  const j = await control("system_info");
  const sy = (j && j.system) || {};
  if ($("#sysGpu")) {
    const g = [];
    if (j.gpu) g.push((j.gpu_count > 1 ? j.gpu_count + " × " : "") + j.gpu);
    if (sy.driver) g.push("driver " + sy.driver);
    if (!g.length) g.push(j.gpu_backend === "cpu" ? "No supported GPU (CPU mode)" : (j.gpu_backend || "—"));
    $("#sysGpu").textContent = g.join(" · ");
  }
  if ($("#sysVram")) $("#sysVram").textContent = j.vram_gb ? j.vram_gb + " GB VRAM" : "—";
  if ($("#sysData")) $("#sysData").textContent = sy.data_free_gb != null ? sy.data_free_gb + " GiB free" : "Not mounted";
  if ($("#sysRam")) $("#sysRam").textContent = sy.ram_total_gb ? sy.ram_total_gb + " GB" : "—";
  if ($("#aboutLlama")) $("#aboutLlama").textContent = sy.llama_version || "—";
}
let advState = { gpus: [], allowed: [], pin: null, cacheTypes: [] };
function advNum(v) { const t = String(v ?? "").trim(); return t === "" ? null : t; }
async function refreshAdvanced() {
  if (!(await ensurePaired())) return;
  const g = await control("gpu_prefs_get");
  advState.gpus = Array.isArray(g.inventory) ? g.inventory : [];
  advState.power = Array.isArray(g.gpus) ? g.gpus : [];
  advState.allowed = Array.isArray(g.allowed) ? g.allowed : [];
  advState.pin = g.pin ?? null;
  renderAdvGpus();
  if (!lastCatalog || !lastCatalog.length) await refreshModels().catch(() => {});
  const sel = $("#advModel");
  const prev = sel.value;
  const list = (lastCatalog || []).filter((m) => m && m.installed);
  sel.innerHTML = list.length
    ? list.map((m) => `<option value="${esc(m.id)}">${esc(m.name || m.id)}</option>`).join("")
    : '<option value="">No models on this stick yet</option>';
  if (prev && list.some((m) => m.id === prev)) sel.value = prev;
  await loadAdvModel();
  if ($("#advAppAgent")) $("#advAppAgent").checked = appAgentOn;
}
function renderAdvGpus() {
  const box = $("#advGpus");
  const rows = advState.gpus;
  if (!rows.length) { box.innerHTML = '<div class="row"><small>Power and clock options are for NVIDIA cards. AMD and Intel cards run through Vulkan and need no setup here; they show in the Detected line on the Models page.</small></div>'; }
  else box.innerHTML = rows.map((r) => {
    const idx = Number(r.index);
    const pw = advState.power.find((p) => Number(p.index) === idx) || {};
    const pre = pw.presets || {};
    const on = !advState.allowed.length || advState.allowed.includes(idx);
    const btns = Object.keys(pre).length
      ? ["eco", "longJob", "default", "boost"].filter((k) => pre[k] != null).map((k) =>
          `<button type="button" class="btn sm${pw.limit_w && Math.round(pw.limit_w) === pre[k] ? " primary" : ""}" data-advpow="${idx}" data-preset="${k}" title="${pre[k]} W">${k === "longJob" ? "Long job" : k[0].toUpperCase() + k.slice(1)} ${pre[k]} W</button>`).join(" ")
      : '<small>No power limit control</small>';
    const mem = r.memory_total_mib || r.total_mib || r.memory_total || "";
    return `<div class="row"><div><label><input type="checkbox" data-advallow="${idx}"${on ? " checked" : ""}> <b>GPU${idx} · ${esc(r.name || "GPU")}</b></label><small>${mem ? esc(String(Math.round(Number(mem) / 1024))) + " GB · " : ""}${pw.limit_w ? "limit " + Math.round(pw.limit_w) + " W" : ""}${pw.draw_w != null ? " · drawing " + Math.round(pw.draw_w) + " W" : ""}</small></div><span>${btns}</span></div>`;
  }).join("");
  const opts = rows.map((r) => `<option value="${Number(r.index)}">GPU${Number(r.index)} · ${esc(r.name || "GPU")}</option>`).join("");
  $("#advPin").innerHTML = '<option value="">Automatic (one card if the model fits, split if it doesn\'t)</option>' + opts;
  $("#advPin").value = advState.pin == null ? "" : String(advState.pin);
  const mp = $("#advModelPin"); const keep = mp.value;
  mp.innerHTML = '<option value="">Use the GPU setting above</option>' + opts;
  mp.value = keep;
}
async function loadAdvModel() {
  const id = $("#advModel").value;
  const j = id ? await control("load_settings_get", { id }) : { settings: {}, cache_types: [] };
  const st = j.settings || {};
  advState.cacheTypes = j.cache_types && j.cache_types.length ? j.cache_types : advState.cacheTypes;
  const ct = '<option value="">auto</option>' + advState.cacheTypes.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  $("#advCtk").innerHTML = ct; $("#advCtv").innerHTML = ct;
  $("#advCtx").value = st.ctx ?? ""; $("#advNgl").value = st.ngl ?? ""; $("#advPar").value = st.parallel ?? "";
  $("#advCtk").value = st.ctk || ""; $("#advCtv").value = st.ctv || "";
  $("#advOt").value = st.override_tensor || "";
  $("#advMmap").checked = st.mmap !== false; $("#advMlock").checked = !!st.mlock;
  $("#advModelPin").value = st.gpu_pin == null ? "" : String(st.gpu_pin);
  $("#advLoadMsg").textContent = Object.keys(st).length ? "Custom settings saved for this model." : "Automatic.";
}
async function saveAdvModel(clear) {
  const id = $("#advModel").value;
  if (!id) return toast("Pick a model first");
  const settings = clear ? {} : {
    ctx: advNum($("#advCtx").value), ngl: advNum($("#advNgl").value), parallel: advNum($("#advPar").value),
    ctk: $("#advCtk").value, ctv: $("#advCtv").value, override_tensor: $("#advOt").value.trim(),
    mlock: $("#advMlock").checked, gpu_pin: advNum($("#advModelPin").value),
  };
  if (!clear && !$("#advMmap").checked) settings.mmap = false;
  try {
    const j = await control("load_settings_set", { id, settings });
    if (j && j.ok === false) throw new Error(j.error || "Could not save");
    toast(clear ? "Back to automatic for this model" : "Saved. Reload the model to use it.");
    await loadAdvModel();
  } catch (e) { $("#advLoadMsg").textContent = e.message || String(e); }
}
if ($("#sec-advanced")) {
  $("#advModel").onchange = () => loadAdvModel().catch((e) => showError(e));
  $("#advLoadSave").onclick = () => saveAdvModel(false);
  $("#advLoadClear").onclick = () => saveAdvModel(true);
  $("#advGpuSave").onclick = async () => {
    const all = advState.gpus.map((r) => Number(r.index));
    const allowed = $$("[data-advallow]").filter((b) => b.checked).map((b) => Number(b.dataset.advallow));
    if (all.length && !allowed.length) return toast("Leave at least one GPU on");
    const pinV = $("#advPin").value;
    try {
      const j = await control("gpu_prefs_set", { allowed: allowed.length === all.length ? [] : allowed, pin: pinV === "" ? null : Number(pinV) });
      if (j && j.ok === false) throw new Error(j.error || "Could not save");
      $("#advGpuMsg").textContent = "Saved. Used the next time a model loads.";
    } catch (e) { $("#advGpuMsg").textContent = e.message || String(e); }
  };
  $("#advGpus").addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("[data-advpow]");
    if (!b) return;
    b.disabled = true;
    try {
      const j = await control("gpu_power_set", { index: Number(b.dataset.advpow), preset: b.dataset.preset });
      if (j && j.ok === false) throw new Error(j.error || "Could not set the power limit");
      if (Array.isArray(j.gpus)) advState.power = j.gpus;
      toast(`GPU${j.index} power limit ${j.watts} W (resets on reboot)`);
      renderAdvGpus();
    } catch (err) { showError(err); b.disabled = false; }
  });
  $("#advAppAgent").onchange = async (e) => {
    const want = e.target.checked;
    try { localStorage.setItem("stickllm-appagent-exp", want ? "1" : "0"); } catch (_) {}
    if (want !== appAgentOn) await appAgentToggle();
    renderAppAgentBar();
  };
}
$("#copyUrl").onclick = () => {
  const pick = (el) => { const t = el?.textContent?.trim() || ""; return /^https?:\/\/[^…]+$/.test(t) ? t : ""; };
  const u = pick($("#netUrl")) || pick($("#lanUrl2")) || location.origin + "/";
  navigator.clipboard?.writeText(u).catch(() => {});
  toast("Address copied");
};
$("#wifiBtn").onclick = async () => {
  const ssid = ($("#ssid").value || "").trim();
  const password = $("#wpass").value || "";
  if (!ssid) return toast("Enter a network name");
  try {
    toast("Connecting to " + ssid + "…");
    const hidden = !!($("#wifiHidden") && $("#wifiHidden").checked);
    const res = await control("wifi_connect", { ssid, password, hidden });
    $("#wpass").value = "";
    toast(res.online ? "Online via WiFi" : "WiFi profile saved — waiting for uplink");
    await refreshStatus();
    // 0.6.1: show the new address right away, then follow DHCP for ~20 s.
    await refreshNetwork().catch(() => {});
    for (let i = 0; i < 10 && !(res.net && res.net.ip); i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const j = await control("net_info").catch(() => null);
      if (j && j.net && j.net.ip) { res.net = j.net; await refreshNetwork().catch(() => {}); break; }
    }
  } catch (e) { $("#wpass").value = ""; showError(e); }
};
// 0.6.1: WiFi scan list (tap a network to fill the name).
if ($("#wifiScan")) $("#wifiScan").onclick = async () => {
  const list = $("#wifiList");
  try {
    toast("Scanning for WiFi…");
    const j = await control("wifi_scan");
    list.textContent = "";
    list.hidden = false;
    const nets = (j && j.networks) || [];
    if (!j.ok || !nets.length) {
      const p = document.createElement("p");
      p.className = "muted small";
      p.style.padding = "8px 12px";
      p.textContent = j.ok ? "No networks found. Type the network name above (works for hidden SSIDs too)." : (j.error || "Scan failed");
      list.appendChild(p);
      return;
    }
    nets.forEach((n) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "option");
      const name = document.createElement("span");
      name.textContent = n.ssid + (n.in_use ? " (connected)" : "");
      const sig = document.createElement("span");
      sig.className = "sig";
      sig.textContent = (n.secure ? "🔒 " : "") + n.signal + "%";
      b.append(name, sig);
      b.onclick = () => {
        $("#ssid").value = n.ssid;
        (n.secure ? $("#wpass") : $("#wifiBtn")).focus();
      };
      list.appendChild(b);
    });
  } catch (e) { showError(e); }
};



/* ---- 0.6.3: Move Agent Zero to SSD / Run from stick ---- */
let a0MovePoll = null;
function a0MoveButtons() {
  return ["a0MoveSsd", "a0RunStick", "agentMoveSsdBtn", "agentRunStickBtn"]
    .map((id) => $("#" + id)).filter(Boolean);
}
function renderA0Drive(s) {
  const d = (s && s.drive) || {};
  const move = d.move || {};
  const busy = move.state === "running";
  const loc = d.location || "";
  const msg = $("#a0DriveMsg") || $("#agentCatalogMsg") || $("#agentInstallMsg");
  if (msg) {
    if (busy) msg.textContent = move.message || "Copying Agent Zero…";
    else if (loc === "ssd") msg.textContent = "Agent Zero is on the host SSD (faster).";
    else msg.textContent = "Agent Zero runs from the stick (preinstalled). Optionally move it to an SSD for speed.";
  }
  const bar = $("#a0MoveBar") || $("#agentMoveBar");
  const pctEl = $("#a0MovePct") || $("#agentMovePct");
  if (bar) {
    bar.hidden = !busy;
    if (pctEl) pctEl.style.width = Math.max(0, Math.min(100, Number(move.progress) || 0)) + "%";
  }
  const moveBtn = $("#a0MoveSsd") || $("#agentMoveSsdBtn");
  const stickBtn = $("#a0RunStick") || $("#agentRunStickBtn");
  if (moveBtn) {
    moveBtn.disabled = busy || !d.can_move_to_ssd || loc === "ssd";
    moveBtn.hidden = loc === "ssd" && !busy;
    moveBtn.textContent = busy && move.target === "ssd"
      ? ("Moving… " + (move.progress || 0) + "%")
      : "Move Agent Zero to SSD (faster)";
  }
  if (stickBtn) {
    stickBtn.hidden = loc !== "ssd" && !(busy && move.target === "usb");
    stickBtn.disabled = busy;
    stickBtn.textContent = busy && move.target === "usb"
      ? ("Switching… " + (move.progress || 0) + "%")
      : "Run from stick";
  }
  for (const btn of agentInstallButtons()) {
    if (s && (s.preinstalled || s.image_present || d.seed_ready)) btn.hidden = true;
  }
  const catInstall = $("#agentCatalogInstall");
  if (catInstall && (s && (s.preinstalled || s.image_present || d.seed_ready))) catInstall.hidden = true;
}
async function moveAgentDrive(target) {
  for (const b of a0MoveButtons()) b.disabled = true;
  try {
    const r = await fetch("/api/agent/docker-drive", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
      body: JSON.stringify({ target }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) {
      toast(j.message || "Could not move Agent Zero");
      for (const b of a0MoveButtons()) b.disabled = false;
      return;
    }
    toast(j.message || (target === "ssd" ? "Moving Agent Zero to SSD…" : "Switching to stick…"));
    if (a0MovePoll) clearInterval(a0MovePoll);
    a0MovePoll = setInterval(async () => {
      try {
        const st = await fetch("/api/agent/status", {
          headers: token ? { Authorization: "Bearer " + token } : {},
        }).then((x) => x.json());
        renderA0Drive(st);
        const mv = st.drive && st.drive.move;
        if (!mv || mv.state !== "running") {
          clearInterval(a0MovePoll); a0MovePoll = null;
          if (mv && mv.state === "done") toast(mv.message || "Done");
          if (mv && mv.state === "error") toast(mv.message || "Copy failed");
        }
      } catch (_) {}
    }, 1500);
  } catch (e) {
    showError(e, "Could not move Agent Zero");
    for (const b of a0MoveButtons()) b.disabled = false;
  }
}
function wireA0DriveButtons() {
  const ms = $("#a0MoveSsd") || $("#agentMoveSsdBtn");
  const rs = $("#a0RunStick") || $("#agentRunStickBtn");
  if (ms) ms.onclick = () => moveAgentDrive("ssd");
  if (rs) rs.onclick = () => moveAgentDrive("usb");
}
wireA0DriveButtons();

/* 0.6.3: Agent Zero is the main chat — auto-start after vault/model ready. */
let stickllmAutoStartA0 = false;
async function ensureAgentZeroStarted() {
  try {
    // First-boot wizard: never open/start A0 until setup finishes.
    if (setupBlocksAgent()) return null;
    // Intentional Lock vault: never restart A0 while umount is in flight.
    if (vaultLocking || vaultBusy()) return null;
    const st = await fetch("/api/agent/status", {
      headers: token ? { Authorization: "Bearer " + token } : {},
      cache: "no-store",
    }).then((r) => r.json());
    renderA0Drive(st);
    // 0.6.7: never start while vault/settings are locked — clears stale "Open Agent Zero".
    if (!st.vault_unlocked && !state.vaultOpen) {
      stickllmAutoStartA0 = false;
      return st;
    }
    if (st.state === "running") {
      stickllmAutoStartA0 = true;
      return st;
    }
    if (st.state === "starting" || st.state === "installing") return st;
    if (st.preinstalled || st.image_present || (st.drive && st.drive.seed_ready) || st.bundled || st.state === "stopped") {
      if (!stickllmAutoStartA0) toast("Starting Agent Zero…");
      stickllmAutoStartA0 = true;
      await fetch("/api/agent/start", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
        body: "{}",
        cache: "no-store",
      });
      agentFastPoll();
    }
    return st;
  } catch (_) { return null; }
}

/* ---- 0.6.7 first-boot / vault setup ----
   1) Mount SSD if present; look for an existing vault.
   2) Vault found → passcode only (reuse Wi‑Fi/settings) — no full wizard.
   3) No vault → Open model (7B Q4) → Network → Storage → Vault → Ready.
   Setup-complete lives on STICKLLM-DATA (stickllm-setup.json), not only localStorage. */
const SETUP_KEY = "stickllm.setup.v067";
const SETUP_KEY_OLD = ["stickllm.setup.v066", "stickllm.setup.v063"];
const STARTER_MODEL_ID = "qwen25-7b-q4km";
let setupStateCache = null; // { setup_complete, vault_unlocked, vault_path, … }
let setupGateBusy = false;
function setupDoneLocal() {
  try {
    if (localStorage.getItem(SETUP_KEY) === "1") return true;
    return SETUP_KEY_OLD.some((k) => localStorage.getItem(k) === "1");
  } catch (_) { return false; }
}
function clearSetupDoneLocal() {
  try {
    localStorage.removeItem(SETUP_KEY);
    SETUP_KEY_OLD.forEach((k) => localStorage.removeItem(k));
  } catch (_) {}
}
function setupDone() {
  // Prefer last server answer. Stale localStorage after a vault wipe must not
  // suppress the first-boot wizard when STICKLLM-DATA says setup is incomplete.
  if (setupStateCache && setupStateCache._fromServer) {
    return !!setupStateCache.setup_complete;
  }
  if (setupStateCache && setupStateCache.setup_complete) return true;
  return setupDoneLocal();
}
function markSetupDone(extra) {
  try {
    localStorage.setItem(SETUP_KEY, "1");
    SETUP_KEY_OLD.forEach((k) => localStorage.setItem(k, "1"));
  } catch (_) {}
  if (setupStateCache) {
    setupStateCache.setup_complete = true;
    setupStateCache._fromServer = true;
  }
  control("setup_mark_complete", extra && typeof extra === "object" ? extra : {}).catch(() => {});
}
async function refreshSetupState(force) {
  if (!force && setupStateCache && (Date.now() - (setupStateCache._at || 0)) < 15000) {
    return setupStateCache;
  }
  try {
    const st = await control("setup_status");
    if (st && st.ok !== false) {
      setupStateCache = { ...st, _at: Date.now(), _fromServer: true };
      if (st.setup_complete) {
        try {
          localStorage.setItem(SETUP_KEY, "1");
          SETUP_KEY_OLD.forEach((k) => localStorage.setItem(k, "1"));
        } catch (_) {}
      } else {
        // Wipe / first-boot: drop browser markers that outlive STICKLLM-DATA.
        clearSetupDoneLocal();
      }
      return setupStateCache;
    }
  } catch (_) {}
  setupStateCache = {
    ok: true,
    setup_complete: setupDoneLocal(),
    vault_unlocked: !!state.vaultOpen,
    vault_path: "",
    source: setupDoneLocal() ? "local" : "none",
    _at: Date.now(),
    _fromServer: false,
  };
  return setupStateCache;
}

/** Mount host SSDs (never format) and look for stickllm-vault.img. */
async function probeBootVault() {
  const out = { found: false, path: "", blob: "", drives: [], unmounted: [] };
  try {
    let targets = await control("storage_targets").catch(() => null);
    if (!targets) return out;
    out.drives = targets.drives || [];
    out.unmounted = targets.unmounted || [];
    for (const u of (out.unmounted || []).slice(0, 6)) {
      try {
        await control("mount_host_partition", { device: u.device, path: u.suggested_mount });
      } catch (_) {}
    }
    targets = await control("storage_targets").catch(() => targets);
    out.drives = (targets && targets.drives) || out.drives;
    out.unmounted = (targets && targets.unmounted) || [];
    const order = [...out.drives].sort((a, b) => {
      const rank = (d) => (d.kind === "ssd" ? 0 : d.kind === "stick" ? 1 : 2);
      return rank(a) - rank(b);
    });
    for (const d of order) {
      const base = String(d.suggested_vault || d.path || "").replace(/\/+$/, "");
      if (!base) continue;
      try {
        const found = await control("vault_find", { path: base });
        const hits = (found && (found.vaults || found.hits || found.paths)) || [];
        const blob = base + "/stickllm-vault.img";
        const parentBlob = String(d.path || "").replace(/\/+$/, "") + "/stickllm-vault.img";
        const exists = !!(found && (found.exists || found.blob)) || hits.some((h) => {
          const p = typeof h === "string" ? h : (h.path || h.blob || "");
          return p === blob || p === parentBlob || p === base || String(p).endsWith("stickllm-vault.img");
        });
        if (exists) {
          out.found = true;
          out.path = base;
          out.blob = String((found && found.blob) || blob);
          if ($("#vaultPath")) $("#vaultPath").value = base;
          return out;
        }
      } catch (_) {}
    }
    const st = await refreshSetupState(true);
    if (st && (st.blob || (st.vault_configured && st.vault_path))) {
      out.found = true;
      out.path = st.vault_path || "";
      out.blob = st.blob || "";
    }
  } catch (_) {}
  return out;
}

/** Prior vault found but locked: password only (no Wi‑Fi/storage steps). */
async function openVaultUnlockOnly(opts) {
  const force = !!(opts && opts.force);
  if ($("#setupWizard")?.classList.contains("show") && !force) return;
  const st = await refreshSetupState(true);
  if (st.vault_unlocked || state.vaultOpen) {
    markSetupDone({ vault_path: st.vault_path || (opts && opts.vaultPath) || "" });
    await enterVaultModeNow();
    return;
  }
  let overlay = $("#setupWizard");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "setupWizard";
    overlay.innerHTML = `
<div class="setup-card" role="dialog" aria-modal="true" aria-labelledby="setupTitle">
  <h2 id="setupTitle">Unlock vault</h2>
  <div id="setupBody"></div>
  <div class="setup-actions">
    <button type="button" id="setupBack" class="ghost" hidden>Back</button>
    <button type="button" id="setupSkip" class="ghost">Full setup</button>
    <button type="button" id="setupNext" class="primary">Unlock</button>
  </div>
  <p id="setupErr" class="err persistent" hidden></p>
</div>`;
    document.body.appendChild(overlay);
  }
  overlay.classList.add("show");
  setSetupChrome(true);
  const body = $("#setupBody");
  const err = $("#setupErr");
  const showErr = (m) => { if (!m) { err.hidden = true; err.textContent = ""; return; } err.hidden = false; err.textContent = m; };
  const vaultPath = ((opts && opts.vaultPath) || st.vault_path || ($("#vaultPath") && $("#vaultPath").value) || "").trim();
  if (vaultPath && $("#vaultPath")) $("#vaultPath").value = vaultPath;
  $("#setupTitle").textContent = "Welcome back";
  $("#setupBack").hidden = true;
  $("#setupSkip").textContent = "Full setup";
  $("#setupSkip").hidden = false;
  $("#setupNext").textContent = "Unlock";
  body.innerHTML = `
<form autocomplete="off" onsubmit="return false">
<p>A vault was found on this computer. Enter the passcode to unlock — Wi‑Fi and settings come back from the vault.</p>
<label class="field"><span>Vault passcode</span><input id="wizP1" type="text" class="secret" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" data-lpignore="true" data-1p-ignore data-form-type="other" readonly></label>
<p class="muted small">Vault: <code id="wizVaultShow"></code></p>
</form>`;
  $("#wizVaultShow").textContent = vaultPath || st.blob || "(saved location)";
  hardenVaultPassFields($("#wizP1"));
  wireVaultPassEnterToSetupNext(body);
  setTimeout(() => $("#wizP1")?.focus(), 50);
  $("#setupSkip").onclick = () => {
    overlay.classList.remove("show");
    setSetupChrome(false);
    openSetupWizard({ force: true }).catch(() => {});
  };
  $("#setupNext").onclick = async () => {
    showErr("");
    const pass = ($("#wizP1")?.value || "");
    if (pass.length < 1) { showErr("Enter the vault passcode"); return; }
    try {
      showVaultCreating(true, "open");
      if (vaultPath) {
        await control("vault_attach", { path: vaultPath }).catch(() => {});
      }
      const res = await control("vault_unlock", { passcode: pass, ...(vaultPath ? { path: vaultPath } : {}) });
      showVaultCreating(false);
      if (!res || res.ok === false) throw new Error((res && (res.error || res.message)) || "Unlock failed");
      markSetupDone({ vault_path: vaultPath });
      overlay.classList.remove("show");
      setSetupChrome(false);
      toast("Vault unlocked");
      await enterVaultModeNow();
      try { await refreshStorage(); } catch (_) {}
      await refreshSetupState(true);
    } catch (e) {
      showVaultCreating(false);
      showErr(String(e.message || e));
    }
  };
}

async function openSetupWizard(opts) {
  const force = !!(opts && opts.force);
  {
    const st = await refreshSetupState(true);
    // Already unlocked: do not steal an in-progress wizard (recovery / ready).
    if (st.vault_unlocked || state.vaultOpen) {
      if (setupWizardShowing() && !force) return;
      if (!force) {
        markSetupDone({ vault_path: st.vault_path || "" });
        dismissSetupWizard();
        try { await enterVaultModeNow({ quiet: true }); } catch (_) {}
        return;
      }
      // force=true: continue into wizard UI even if unlocked (storage remount).
    }
    if (!force) {
      if (st.setup_complete || st.vault_configured || st.blob) {
        return openVaultUnlockOnly({ vaultPath: st.vault_path || "" });
      }
      if (setupDoneLocal()) return;
    }
  }
  // Open model → Network → Storage → Vault → Recovery → System ready.
  // Recovery is a wizard step (not #confirm): confirm was z-index 60 under
  // #setupWizard (9999), so the phrase modal never appeared and create looked stuck.
  const STEP_MODEL = 0, STEP_NET = 1, STEP_STOR = 2, STEP_VAULT = 3, STEP_RECOVERY = 4, STEP_READY = 5;
  const LAST = STEP_READY;
  let step = STEP_MODEL;
  let vaultStepBusy = false;
  const wiz = {
    drive: null,
    vaultPath: "",
    modelsPath: "",
    dockerPath: "",
    pass1: "",
    pass2: "",
    ssid: "",
    wpass: "",
    vaultMode: "create", // or "unlock" when stickllm-vault.img already exists
    vaultDone: false,
    // Create must show recovery once; poll/rescue must not skip it.
    needsRecoveryPhrase: false,
    recoveryShown: false,
    recoveryPhrase: "",
    createInFlight: false,
    recoveryAck: false,
  };
  /** Vault create success: enter vault mode → Recovery step → System ready. */
  let advanceCreateLock = null;
  async function advanceAfterVaultCreate(phrase) {
    if (advanceCreateLock) return advanceCreateLock;
    advanceCreateLock = (async () => {
      showVaultCreating(false);
      wiz.createInFlight = false;
      wiz.vaultMode = "unlock";
      wiz.vaultDone = true;
      wiz.needsRecoveryPhrase = true;
      const words = (phrase || wiz.recoveryPhrase || "").trim();
      wiz.recoveryPhrase = words || "(no phrase in response — check stick logs)";
      toast("Vault created");
      try { await enterVaultModeNow({ duringSetup: true, quiet: true }); } catch (_) {}
      step = STEP_RECOVERY;
      render();
    })();
    try { return await advanceCreateLock; }
    finally { advanceCreateLock = null; }
  }
  let overlay = $("#setupWizard");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "setupWizard";
    overlay.innerHTML = `
<div class="setup-card" role="dialog" aria-modal="true" aria-labelledby="setupTitle">
  <h2 id="setupTitle">Welcome to StickLLM</h2>
  <div id="setupBody"></div>
  <div class="setup-actions">
    <button type="button" id="setupBack" class="ghost">Back</button>
    <button type="button" id="setupSkip" class="ghost">Skip</button>
    <button type="button" id="setupNext" class="primary">Continue</button>
  </div>
  <p id="setupErr" class="err persistent" hidden></p>
</div>`;
    document.body.appendChild(overlay);
  }
  overlay.classList.add("show");
  setSetupChrome(true);
  const body = $("#setupBody");
  const err = $("#setupErr");
  const showErr = (m) => { if (!m) { err.hidden = true; err.textContent = ""; return; } err.hidden = false; err.textContent = m; };
  const targets = await control("storage_targets").catch(() => ({ drives: [], unmounted: [] }));
  const drives = (targets && targets.drives) || [];
  const unmounted = (targets && targets.unmounted) || [];
  wiz.drive = drives.find((d) => d.kind === "ssd") || drives.find((d) => d.kind === "stick") || drives[0] || null;
  if (wiz.drive) {
    wiz.vaultPath = wiz.drive.suggested_vault || (wiz.drive.path + "/vault");
    wiz.modelsPath = wiz.drive.suggested_models || (wiz.drive.path + "/models");
    wiz.dockerPath = wiz.drive.suggested_docker || (wiz.drive.path + "/stickllm-docker");
  }

  async function joinWifi(ssid, password) {
    if (!ssid) return { ok: true, skipped: true };
    const res = await control("wifi_connect", { ssid, password: password || "" });
    if (res && res.ok === false) throw new Error(res.error || res.message || "Wi‑Fi join failed");
    return res || { ok: true };
  }

  function paintWifiList(listEl, nets) {
    listEl.hidden = false;
    listEl.textContent = "";
    listEl.className = "wifiList";
    if (!nets.length) {
      const p = document.createElement("p");
      p.className = "muted small";
      p.style.padding = "8px 12px";
      p.textContent = "No networks found. Type a name above (works for hidden SSIDs too).";
      listEl.appendChild(p);
      return;
    }
    nets.forEach((n) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "option");
      b.classList.toggle("selected", n.ssid === wiz.ssid);
      const name = document.createElement("span");
      name.textContent = n.ssid + (n.in_use ? " (connected)" : "");
      const sig = document.createElement("span");
      sig.className = "sig";
      sig.textContent = (n.secure ? "🔒 " : "") + (n.signal != null ? n.signal + "%" : "");
      b.append(name, sig);
      b.onclick = () => {
        wiz.ssid = n.ssid;
        $("#wizSsid").value = n.ssid;
        listEl.querySelectorAll("button").forEach((x) => x.classList.remove("selected"));
        b.classList.add("selected");
        (n.secure ? $("#wizWpass") : $("#wizJoin")).focus();
      };
      listEl.appendChild(b);
    });
  }

  function starterModel() {
    return findModel(STARTER_MODEL_ID)
      || (lastCatalog || []).find((m) => m && (m.id === STARTER_MODEL_ID || /qwen2\.?5-?7b.*q4/i.test(String(m.id || "") + " " + String(m.name || ""))))
      || null;
  }

  function render() {
    showErr("");
    $("#setupBack").disabled = step <= 0;
    $("#setupBack").hidden = step <= 0;
    $("#setupSkip").hidden = false;
    $("#setupSkip").textContent = step >= LAST ? "Close" : "Skip";
    $("#setupNext").textContent = step >= LAST ? "Finish" : "Continue";
    // Hung create can leave Continue disabled with no busy overlay — always clear on paint.
    try {
      const busy = $("#vaultCreatingOverlay");
      if (!(busy && busy.classList.contains("show"))) $("#setupNext").disabled = false;
    } catch (_) {}
    if (step === STEP_MODEL) {
      $("#setupTitle").textContent = "Open model";
      const m = starterModel();
      const label = (m && (m.name || m.id)) || "Qwen2.5-7B Instruct Q4_K_M";
      const where = m ? modelWhere(m) : "stick";
      body.innerHTML = `
<p>Our default installed model is <strong>${esc(label)}</strong> (Qwen2.5-7B Instruct Q4_K_M) — open now or Skip and download your own later.</p>
<div class="card" style="margin:12px 0;padding:12px">
  <div><b>${esc(label)}</b></div>
  <div class="muted small">On the ${esc(where)} · id <code>${esc(STARTER_MODEL_ID)}</code></div>
</div>
<p class="muted small">Continue loads this model. Skip leaves the model picker for later.</p>`;
      $("#setupSkip").textContent = "Skip";
      $("#setupNext").textContent = "Open now";
    } else if (step === STEP_NET) {
      $("#setupTitle").textContent = "Network";
      body.innerHTML = `
<p class="muted">Connect to Wi‑Fi or plug in a cable. Continue joins the selected network before moving on.</p>
<label class="field"><span>Network name (SSID)</span><input id="wizSsid" autocomplete="off"></label>
<label class="field"><span>Password</span><input id="wizWpass" type="text" class="secret" autocomplete="off"></label>
<div id="wizWifiList" class="wifiList" role="listbox" aria-label="Nearby Wi‑Fi networks" hidden></div>
<div class="actions"><button type="button" id="wizScan" class="btn">Scan</button>
<button type="button" id="wizJoin" class="btn">Join Wi‑Fi</button></div>`;
      $("#wizSsid").value = wiz.ssid;
      $("#wizWpass").value = wiz.wpass;
      $("#wizScan").onclick = async () => {
        try {
          const j = await control("wifi_scan");
          paintWifiList($("#wizWifiList"), (j && j.networks) || []);
        } catch (e) { showErr(String(e.message || e)); }
      };
      $("#wizJoin").onclick = async () => {
        wiz.ssid = $("#wizSsid").value.trim(); wiz.wpass = $("#wizWpass").value;
        try {
          if (!wiz.ssid) throw new Error("Enter or pick a network name");
          showErr("");
          const res = await joinWifi(wiz.ssid, wiz.wpass);
          toast(res.online ? "Online via Wi‑Fi" : "Wi‑Fi profile saved — waiting for uplink");
        } catch (e) { showErr(String(e.message || e)); }
      };
    } else if (step === STEP_STOR) {
      $("#setupTitle").textContent = "Storage";
      const rows = drives.map((d) => {
        const sel = wiz.drive && wiz.drive.id === d.id;
        return `<button type="button" class="drive-pick${sel ? " selected" : ""}" data-id="${d.id}">
<strong>${d.label}</strong> · ${d.free_gb != null ? d.free_gb + " GB free" : ""}
<div class="muted small">${d.path}</div></button>`;
      }).join("") || `<p class="muted">No mounted data drives found yet.</p>`;
      const um = unmounted.map((u) =>
        `<button type="button" class="drive-pick" data-mount="${u.device}" data-mp="${u.suggested_mount}">
Mount ${u.label}<div class="muted small">${u.device} → ${u.suggested_mount} (never formats)</div></button>`
      ).join("");
      body.innerHTML = `
<p>Choose where to keep the vault, models, and Agent Zero. Prefers an internal SSD when one is available; the stick works fine alone.</p>
<div class="drive-list">${rows}${um}</div>
<label class="field"><span>Vault folder</span><input id="wizVault"></label>
<label class="field"><span>Models / downloads folder</span><input id="wizModels"></label>
<label class="field"><span>Agent Zero / Docker folder</span><input id="wizDocker"></label>
<div class="card" id="wizA0Drive" style="margin-top:10px">
  <p class="muted small">Agent Zero is preinstalled on the stick. Moving it to an SSD makes it start faster (one-time copy).</p>
  <button type="button" class="btn" id="wizMoveA0">Move Agent Zero to SSD (faster)</button>
  <button type="button" class="btn ghost" id="wizRunStick" hidden>Run from stick</button>
  <div class="progress" id="wizMoveBar" hidden><div id="wizMovePct" style="width:0%"></div></div>
</div>`;
      $("#wizVault").value = wiz.vaultPath;
      $("#wizModels").value = wiz.modelsPath;
      $("#wizDocker").value = wiz.dockerPath;
      const wizMove = $("#wizMoveA0");
      const wizStick = $("#wizRunStick");
      if (wizMove) wizMove.onclick = () => moveAgentDrive("ssd");
      if (wizStick) wizStick.onclick = () => moveAgentDrive("usb");
      fetch("/api/agent/status", { headers: token ? { Authorization: "Bearer " + token } : {} })
        .then((r) => r.json()).then((st) => {
          const d = st.drive || {};
          if (wizMove) { wizMove.disabled = !d.can_move_to_ssd; wizMove.hidden = d.location === "ssd"; }
          if (wizStick) wizStick.hidden = d.location !== "ssd";
          const box = $("#wizA0Drive");
          if (box) box.hidden = !d.ssd_available && d.location !== "ssd";
        }).catch(() => {});
      body.querySelectorAll(".drive-pick[data-id]").forEach((b) => {
        b.onclick = () => {
          wiz.drive = drives.find((d) => d.id === b.dataset.id);
          if (wiz.drive) {
            wiz.vaultPath = wiz.drive.suggested_vault;
            wiz.modelsPath = wiz.drive.suggested_models;
            wiz.dockerPath = wiz.drive.suggested_docker;
            render();
          }
        };
      });
      body.querySelectorAll(".drive-pick[data-mount]").forEach((b) => {
        b.onclick = async () => {
          try {
            const r = await control("mount_host_partition", { device: b.dataset.mount, path: b.dataset.mp });
            if (!r.ok) throw new Error(r.error || "mount failed");
            toast("Mounted " + b.dataset.mount);
            overlay.classList.remove("show");
            openSetupWizard({ force: true });
          } catch (e) { showErr(String(e.message || e)); }
        };
      });
    } else if (step === STEP_VAULT) {
      // Create finished — never re-paint passcode; go Recovery then Ready.
      if (wiz.vaultDone || (wiz.needsRecoveryPhrase && wiz.recoveryPhrase)) {
        wiz.vaultMode = "unlock";
        step = wiz.recoveryShown ? STEP_READY : STEP_RECOVERY;
        render();
        return;
      }
      $("#setupTitle").textContent = wiz.vaultMode === "unlock" ? "Unlock vault" : "Vault passcode";
      $("#setupSkip").hidden = true; // vault step: no skip past create/unlock
      body.innerHTML = `
<form autocomplete="off" onsubmit="return false">
<p>${wiz.vaultMode === "unlock"
  ? "A vault file already exists at this path. Enter the passcode to unlock it."
  : "Encrypt chats and settings. Models can live beside the vault on the same drive."}</p>
<label class="field"><span>Passcode (8+ characters)</span><input id="wizP1" type="text" class="secret" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" data-lpignore="true" data-1p-ignore data-form-type="other" readonly></label>
<label class="field" ${wiz.vaultMode === "unlock" ? "hidden" : ""}><span>Confirm passcode</span><input id="wizP2" type="text" class="secret" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" data-lpignore="true" data-1p-ignore data-form-type="other" readonly></label>
<p class="muted small">Vault path: <code id="wizVaultShow"></code></p>
<p class="muted small" id="wizVaultHint" hidden></p>
</form>`;
      $("#wizVaultShow").textContent = wiz.vaultPath || "(choose storage first)";
      $("#wizP1").value = wiz.pass1;
      if ($("#wizP2")) $("#wizP2").value = wiz.pass2;
      hardenVaultPassFields($("#wizP1"), $("#wizP2"));
      wireVaultPassEnterToSetupNext(body);
      if (wiz.vaultMode === "unlock") {
        const h = $("#wizVaultHint");
        if (h) { h.hidden = false; h.textContent = "Existing stickllm-vault.img found — unlock instead of create."; }
      }
      // Mid-create hang: vault may already be unlocked under us — never flip to
      // unlock-passcode just because the blob appeared mid-create (that caused
      // "back to Vault passcode" after a successful create).
      const vaultPaintStep = step;
      refreshSetupState(true).then(async (st) => {
        if (!setupWizardShowing() || step !== vaultPaintStep || step !== STEP_VAULT) return;
        if (wiz.createInFlight || wiz.needsRecoveryPhrase || vaultStepBusy) {
          if (st.vault_unlocked || state.vaultOpen) {
            try { await advanceAfterVaultCreate(wiz.recoveryPhrase); } catch (_) {}
          }
          return;
        }
        if (st.vault_unlocked || state.vaultOpen) {
          // Create path must still show recovery → ready (never markSetupDone / dismiss here).
          if (wiz.needsRecoveryPhrase || (!wiz.vaultDone && wiz.vaultMode === "create")) {
            try { await advanceAfterVaultCreate(wiz.recoveryPhrase); } catch (_) {}
            return;
          }
          wiz.vaultDone = true;
          wiz.vaultMode = "unlock";
          showVaultCreating(false);
          try { await enterVaultModeNow({ duringSetup: true, quiet: true }); } catch (_) {}
          step = wiz.recoveryShown ? STEP_READY : STEP_RECOVERY;
          render();
          return;
        }
        // Only switch create→unlock UI when idle (not mid-create) and a blob
        // already existed before this session's create attempt.
        if ((st.blob || st.vault_configured) && wiz.vaultMode !== "unlock" && !wiz.createInFlight && !wiz.needsRecoveryPhrase && !wiz.vaultDone) {
          wiz.vaultMode = "unlock";
          if (st.vault_path) wiz.vaultPath = st.vault_path;
          render();
        }
      }).catch(() => {});
    } else if (step === STEP_RECOVERY) {
      $("#setupTitle").textContent = "Save your recovery phrase";
      $("#setupSkip").hidden = true;
      $("#setupBack").hidden = true;
      body.innerHTML = `
<p>This is the only time it's shown. Write it down and keep it somewhere safe.</p>
<pre class="recovery" id="wizRecoveryPhrase"></pre>
<label class="checkRow"><input type="checkbox" id="wizRecoveryAck"> <span>I wrote down the recovery phrase.</span></label>`;
      const pre = $("#wizRecoveryPhrase");
      if (pre) pre.textContent = wiz.recoveryPhrase || "(no phrase in response — check stick logs)";
      const ack = $("#wizRecoveryAck");
      $("#setupNext").disabled = true;
      $("#setupNext").textContent = "Continue";
      if (ack) {
        ack.checked = !!wiz.recoveryAck;
        $("#setupNext").disabled = !ack.checked;
        ack.onchange = () => {
          wiz.recoveryAck = !!ack.checked;
          $("#setupNext").disabled = !ack.checked;
        };
      }
    } else {
      $("#setupTitle").textContent = "System ready";
      $("#setupSkip").hidden = true;
      body.innerHTML = `
<ul class="setup-check">
<li>Setup is complete. Open <strong>Agent Zero</strong> from the desktop when you want to chat.</li>
<li>Open <strong>Settings → Storage</strong> any time to change folders or re-run this wizard.</li>
<li>Load another model from Models when you want a larger one — the on-stick 7B works offline.</li>
</ul>`;
    }
  }

  $("#setupBack").onclick = () => { if (step > 0 && step !== STEP_RECOVERY) { step -= 1; render(); } };

  $("#setupSkip").onclick = () => {
    if (step >= LAST) {
      markSetupDone({ vault_path: wiz.vaultPath || "" });
      overlay.classList.remove("show");
      setSetupChrome(false);
      enterVaultModeNow().catch(() => {});
      return;
    }
    if (step === STEP_VAULT) return; // skip hidden
    step += 1; render();
  };
  $("#setupNext").onclick = async () => {
    showErr("");
    try {
      if (step === STEP_MODEL) {
        try { await refreshModels(); } catch (_) {}
        const m = starterModel();
        if (m) {
          try {
            selectedModelId = m.id;
            beginModelLoadUi(m.id, m.name || m.id);
            startLoadPoll();
            const res = await control("model_activate", {
              id: m.id,
              ctx_size: +($("#ctx")?.value || 32768),
              kv_type: { f16: "f16", q8: "q8_0", q4: "q4_0" }[state.kv] || "f16",
            });
            loadActivateSettled = true;
            if (res && res.ok === false && res.error) throw new Error(res.error);
            toast("Loading " + (m.name || m.id) + "…");
          } catch (e) {
            showErr("Could not start the on-stick model: " + (e.message || e) + " — Continue again or Skip.");
            return;
          }
        } else {
          toast("On-stick model not listed yet — you can load it from Models later");
        }
      }
      if (step === STEP_NET) {
        wiz.ssid = ($("#wizSsid")?.value || "").trim();
        wiz.wpass = $("#wizWpass")?.value || "";
        if (wiz.ssid) {
          const res = await joinWifi(wiz.ssid, wiz.wpass);
          toast(res.online ? "Online via Wi‑Fi" : "Wi‑Fi profile saved");
          if (res.ok === false) throw new Error(res.error || "Wi‑Fi join failed");
        }
      }
      if (step === STEP_STOR) {
        wiz.vaultPath = ($("#wizVault")?.value || "").trim();
        wiz.modelsPath = ($("#wizModels")?.value || "").trim();
        wiz.dockerPath = ($("#wizDocker")?.value || "").trim();
        if (!wiz.vaultPath || !wiz.modelsPath) throw new Error("Choose vault and models folders");
        if (wiz.modelsPath) {
          const r = await control("set_models_dir", { path: wiz.modelsPath });
          if (r && r.ok === false) throw new Error(r.error || "Could not set models folder");
        }
        if ($("#vaultPath")) $("#vaultPath").value = wiz.vaultPath;
        try {
          const found = await control("vault_find", { path: wiz.vaultPath });
          const hits = (found && (found.vaults || found.hits || found.paths)) || [];
          const path = wiz.vaultPath.replace(/\/+$/, "");
          const blob = path + "/stickllm-vault.img";
          const exists = hits.some((h) => {
            const p = typeof h === "string" ? h : (h.path || h.blob || "");
            return p === blob || p === path || String(p).endsWith("stickllm-vault.img");
          }) || !!(found && found.exists);
          if (exists || (found && found.ok && found.blob)) wiz.vaultMode = "unlock";
          else wiz.vaultMode = "create";
        } catch (_) { wiz.vaultMode = "create"; }
      }
      if (step === STEP_RECOVERY) {
        if (!$("#wizRecoveryAck")?.checked && !wiz.recoveryAck) {
          throw new Error("Tick the box after you write down the recovery phrase");
        }
        wiz.recoveryAck = true;
        wiz.recoveryShown = true;
        wiz.needsRecoveryPhrase = false;
        step = STEP_READY;
        render();
        return;
      }
      if (step === STEP_VAULT) {
        if (vaultStepBusy) return;
        // Already finished create/unlock this session — never re-enter create.
        if (wiz.vaultDone) {
          wiz.vaultMode = "unlock";
          step = wiz.recoveryShown ? STEP_READY : STEP_RECOVERY;
          render();
          return;
        }
        // Rescue: create finished under a hung UI — vault already open.
        {
          const stNow = await refreshSetupState(true);
          if (stNow.vault_unlocked || state.vaultOpen) {
            if (wiz.needsRecoveryPhrase || wiz.vaultMode === "create") {
              await advanceAfterVaultCreate(wiz.recoveryPhrase);
              return;
            }
            showVaultCreating(false);
            try { await enterVaultModeNow({ duringSetup: true, quiet: true }); } catch (_) {}
            wiz.vaultDone = true;
            wiz.vaultMode = "unlock";
            step = wiz.recoveryShown ? STEP_READY : STEP_RECOVERY;
            render();
            return;
          }
          wiz.pass1 = $("#wizP1")?.value || "";
          wiz.pass2 = wiz.vaultMode === "unlock" ? wiz.pass1 : ($("#wizP2")?.value || "");
          if (wiz.pass1.length < 8) throw new Error("Passcode must be at least 8 characters");
          if (wiz.vaultMode !== "unlock" && wiz.pass1 !== wiz.pass2) throw new Error("Passcodes don't match");
          const path = wiz.vaultPath.replace(/\/+$/, "");
          const onStick = path === "/mnt/stickllm-data" || path.startsWith("/mnt/stickllm-data/");
          // Blob already there — never call create again (avoids exists-loop + disabled Continue).
          if (wiz.vaultMode !== "unlock") {
            try {
              const found = await control("vault_find", { path });
              const hits = (found && (found.vaults || found.hits || found.paths)) || [];
              const blob = path + "/stickllm-vault.img";
              const exists = hits.some((h) => {
                const p = typeof h === "string" ? h : (h.path || h.blob || "");
                return p === blob || p === path || String(p).endsWith("stickllm-vault.img");
              }) || !!(found && (found.exists || found.blob));
              if (exists) wiz.vaultMode = "unlock";
            } catch (_) {}
          }
          vaultStepBusy = true;
          $("#setupNext").disabled = true;
          showVaultCreating(true, wiz.vaultMode === "unlock" ? "open" : "create");
          try {
            let res;
            if (wiz.vaultMode === "unlock") {
              await control("vault_attach", { path }).catch(() => {});
              res = await control("vault_unlock", { passcode: wiz.pass1, path });
              showVaultCreating(false);
              if (!res || res.ok === false) throw new Error((res && (res.error || res.message)) || "Unlock failed");
              toast("Vault unlocked");
              await enterVaultModeNow({ duringSetup: true, quiet: true });
              wiz.vaultDone = true;
              wiz.vaultMode = "unlock";
              wiz.recoveryShown = true; // unlock path — no new phrase
              wiz.needsRecoveryPhrase = false;
              step = STEP_READY;
              render();
              return;
            } else {
              // Long create on USB: poll ONLY for unlocked (never for bare blob).
              // Treating blob-exists as done flipped UI back to Vault passcode mid-create.
              wiz.needsRecoveryPhrase = true;
              wiz.createInFlight = true;
              let createSettled = false;
              const pollUnlocked = (async () => {
                for (let i = 0; i < 120 && !createSettled; i++) {
                  await new Promise((r) => setTimeout(r, 2500));
                  if (createSettled) return null;
                  try {
                    const st = await refreshSetupState(true);
                    if (st.vault_unlocked || state.vaultOpen) return { unlocked: true, st };
                  } catch (_) {}
                }
                return null;
              })();
              const setupP = control("vault_setup", {
                path, size_gb: "32", confirm: "CREATE-VAULT",
                recovery_confirm: "SHOW-ONCE", passcode: wiz.pass1, passcode2: wiz.pass2,
                space_confirm: "SPACE-OK",
                ...(onStick ? { stick_data_confirm: "STICK-DATA" } : {}),
              }).then((r) => ({ kind: "setup", r }));
              const raced = await Promise.race([
                setupP,
                pollUnlocked.then((r) => (r ? { kind: "poll", r } : new Promise(() => {}))),
              ]);
              createSettled = true;
              if (raced.kind === "poll") {
                // Vault is open — still prefer recovery_phrase from the create RPC.
                let phrase = wiz.recoveryPhrase || "";
                try {
                  const late = await Promise.race([
                    setupP.then((x) => x && x.r),
                    new Promise((r) => setTimeout(() => r(null), 8000)),
                  ]);
                  if (late && late.recovery_phrase) phrase = late.recovery_phrase;
                } catch (_) {}
                await advanceAfterVaultCreate(phrase);
                return;
              }
              res = raced.r;
              if (!res || res.ok === false) {
                const errMsg = String((res && (res.error || res.stderr)) || "vault setup failed");
                wiz.createInFlight = false;
                if (/already exists/i.test(errMsg)) {
                  showVaultCreating(false);
                  // Create already finished (blob on disk). Never bounce to Unlock
                  // passcode — that is the post-create loop. Prefer recovery → ready.
                  try {
                    const stEx = await refreshSetupState(true);
                    if (stEx.vault_unlocked || state.vaultOpen || wiz.needsRecoveryPhrase) {
                      await advanceAfterVaultCreate(wiz.recoveryPhrase || (res && res.recovery_phrase) || "");
                      return;
                    }
                  } catch (_) {}
                  if (wiz.needsRecoveryPhrase || wiz.recoveryPhrase) {
                    await advanceAfterVaultCreate(wiz.recoveryPhrase || "");
                    return;
                  }
                  wiz.vaultMode = "unlock";
                  render();
                  showErr("A vault already exists here — enter the passcode to unlock.");
                  return;
                }
                throw new Error(errMsg);
              }
              // Correct sequence: vault mode → recovery (no Cancel) → System ready. Never create twice.
              await advanceAfterVaultCreate(res.recovery_phrase || "");
              return;
            }
          } catch (e) {
            showVaultCreating(false);
            const msg = String(e.message || e);
            // Create may have finished despite a client timeout/error.
            try {
              const stFail = await refreshSetupState(true);
              if (stFail.vault_unlocked || state.vaultOpen) {
                if (wiz.needsRecoveryPhrase || wiz.vaultMode === "create") {
                  await advanceAfterVaultCreate(wiz.recoveryPhrase);
                  return;
                }
                try { await enterVaultModeNow({ duringSetup: true, quiet: true }); } catch (_) {}
                wiz.vaultDone = true;
                wiz.vaultMode = "unlock";
                step = wiz.recoveryShown ? STEP_READY : STEP_RECOVERY;
                render();
                return;
              }
              if (/already exists/i.test(msg) || stFail.blob || stFail.vault_configured) {
                // Mid/post-create: blob exists is success path → recovery, not unlock form.
                if (wiz.needsRecoveryPhrase || wiz.vaultMode === "create" || stFail.vault_unlocked || state.vaultOpen) {
                  await advanceAfterVaultCreate(wiz.recoveryPhrase || "");
                  return;
                }
                wiz.vaultMode = "unlock";
                render();
                showErr("A vault already exists here — enter the passcode to unlock.");
                return;
              }
              throw e;
            } catch (e2) {
              if (/already exists/i.test(msg)) {
                wiz.needsRecoveryPhrase = false;
                wiz.vaultMode = "unlock";
                render();
                showErr("A vault already exists here — enter the passcode to unlock.");
                return;
              }
              throw e2;
            }
          } finally {
            vaultStepBusy = false;
            // RPC path finished (success or fail). Leave needsRecoveryPhrase alone.
            if (!wiz.recoveryShown) wiz.createInFlight = false;
            $("#setupNext").disabled = false;
          }
        }
      }
      if (step >= LAST) {
        markSetupDone({ vault_path: wiz.vaultPath || "" });
        overlay.classList.remove("show");
        setSetupChrome(false);
        try { await refreshSetupState(true); } catch (_) {}
        try { await refreshStorage(); } catch (_) {}
        try { await enterVaultModeNow(); } catch (_) {}
        return;
      }
      step += 1;
      render();
    } catch (e) {
      showErr(String(e.message || e));
    }
  };
  // Prefetch catalog so the Open model step can name the 4B.
  refreshModels().catch(() => {});
  render();
}


async function maybeOfferSetupOrUnlock() {
  const stickLocalUi = !!(isLocalMode) || !!(detectLocalHost && detectLocalHost());
  if (!stickLocalUi || setupGateBusy) return;
  // Stuck create page (Continue disabled / vault already open): rescue even while wizard is showing.
  if (setupWizardShowing()) {
    setupGateBusy = true;
    try { await rescueStuckVaultWizard(); } finally { setupGateBusy = false; }
    return;
  }
  setupGateBusy = true;
  try {
    // 0.6.7: mount SSD first and prefer an existing vault over full setup.
    const probe = await probeBootVault();
    const st = await refreshSetupState(true);
    if (st.vault_unlocked || state.vaultOpen) {
      if (st.setup_complete || setupDoneLocal() || probe.found) markSetupDone({ vault_path: st.vault_path || probe.path || "" });
      // Sync unlock chrome only. Never force Vault session mode here —
      // enterVaultModeNow was stealing Ephemeral on every health poll.
      if (!state.vaultOpen) setVaultChrome(true);
      return;
    }
    if (probe.found || st.setup_complete || st.vault_configured) {
      await openVaultUnlockOnly({ vaultPath: probe.path || st.vault_path || "" });
      return;
    }
    if (!setupDoneLocal()) await openSetupWizard();
  } catch (_) {
    if (!setupDoneLocal()) openSetupWizard().catch(() => {});
  } finally {
    setupGateBusy = false;
  }
}



async function refreshStatus() {
  // A refresh must not paint Loading until this browser is paired.
  if (!browserPaired) return;
  maybeOfferSetupOrUnlock().catch(() => {});
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
      const warm = (j.llama_warmup && j.llama_warmup.status) || "";
      const warming = /^(queued|waiting|running)$/i.test(String(warm));
      $("#chipModel").textContent = warming ? "Warming up…" : readyName;
      if (warming) {
        setChipLoad(true, 95, readyName, "Loading model… first reply takes a long time", false);
      } else {
        setChipLoad(false, 100, readyName);
      }
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
        const warm = (j.llama_warmup && j.llama_warmup.status) || "";
        const warming = /^(queued|waiting|running)$/i.test(String(warm));
        pop.textContent = warming ? `Warming up… — ${named || "model"}` : (named || "ready");
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
    const url = j.connect?.url
      || (j.connect?.ip ? `https://${j.connect.ip}/` : "")
      || (location.protocol === "https:" ? location.origin + "/" : httpsStickUrl())
      || location.origin + "/";
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
    // 0.6.5: SSH password under pair code on the stick screen (GRUB test/term only).
    paintSshDetails(j.connect);
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
    const setM = settingsModal();
    if ($("#ablAck") && !$("#ablAck").hidden) $("#ablAck").hidden = true;
    else if (!$("#confirm").hidden) $("#confirm").hidden = true;
    else if (!$("#picker").hidden) $("#picker").hidden = true;
    else if (setM && setM.classList.contains("setNavOpen")) setNavMenuOpen(false);
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
    const hit = syncPresetHighlight() || "fast";
    applyTune({ ctx: TUNE_PRESETS[hit].ctx, kv: TUNE_PRESETS[hit].kv, temp: TUNE_PRESETS[hit].temp, top_p: 0.9, top_k: 40, repeat_penalty: 1.1, max_tokens: CHAT_TOKENS });
    saveTune(); renderModelsList();
    toast("Reset to preset");
  };
}
try {
  const saved = JSON.parse(localStorage.getItem(TUNE_KEY) || "null");
  if (saved) applyTune(saved);
  else applyPreset("fast");
} catch (_) { applyPreset("fast"); }
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
    showError(e);
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
      } catch (e) { showError(e); }
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
  if (!add || micHallucination(add)) {
    // Voice listen: quiet miss — composerNote height changes flicker the kiosk.
    if (!voiceMode) speechFail(prefix + "No speech detected.");
    return false;
  }
  if (sent) showComposerLine(sent, false);
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
    // Do not connect to ctx.destination: on the HDMI kiosk that opens ALSA
    // playback while MediaRecorder holds capture → "Device or resource busy"
    // retries and compositor flicker (SwiftShader). A silent MediaStream sink
    // keeps the analyser graph alive without touching the hardware output.
    const ctx = new Ctx({ latencyHint: "interactive" });
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.4;
    source.connect(analyser);
    const tap = ctx.createGain();
    tap.gain.value = 0;
    const sink = ctx.createMediaStreamDestination();
    analyser.connect(tap);
    tap.connect(sink);
    micCtx = ctx;
    micSource = source;
    micAnalyser = analyser;
    const buf = new Float32Array(analyser.fftSize);
    const tickMs = 250;
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
        voiceSpeechMs += tickMs;
        voiceQuietMs = 0;
      } else if (voiceSpeechMs >= VOICE_MIN_SPEECH_MS) {
        voiceQuietMs += tickMs;
        if (voiceQuietMs >= VOICE_SILENCE_MS) finishMic();
      } else if (voiceHeard) {
        voiceQuietMs += tickMs;
        if (voiceQuietMs >= VOICE_SILENCE_MS) {
          voiceHeard = false;
          voiceSpeechMs = 0;
          voiceQuietMs = 0;
        }
      }
    }, tickMs);
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
    // Voice mode: skip empty-note thrash (composer height flicker).
    if (stop || !voiceMode) speechFail("The recording was empty");
    if (!stop && voiceMode) resumeVoiceListen();
    return;
  }
  const sent = sentLabel(raw.length);
  // Defer "Sent N KB" until a real transcript — avoids layout thrash on noise.
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
      if (stop || !voiceMode) speechFail(sent + " " + msg);
      return;
    }
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
function httpsStickUrl() {
  const shown = ($("#lanUrl2") && $("#lanUrl2").textContent || "").trim();
  if (/^https:\/\//i.test(shown)) return shown.replace(/\/?$/, "/");
  if (/^http:\/\//i.test(shown)) return shown.replace(/^http/i, "https").replace(/\/?$/, "/");
  try {
    const u = new URL(location.href);
    const host = String(u.hostname || "").trim();
    if (host && host !== "localhost" && host !== "127.0.0.1") return "https://" + host + "/";
  } catch (_) {}
  return "";
}
function secureMicMessage() {
  // Chromium blocks getUserMedia on plain http://LAN — only HTTPS or localhost.
  const https = httpsStickUrl();
  if (https) {
    return "Microphone needs HTTPS. Open " + https + " — trust the stick certificate once, then Allow the mic.";
  }
  return "Microphone needs HTTPS. Open https://<stick-ip>/ — trust the stick certificate once, then Allow the mic.";
}
// Dismissed Allow prompts can be re-asked; permanent Block cannot.
let micNeedsAllow = false;
let micPermBlocked = false;
const MIC_PERM_RETRIES = 2;
function micPermDeniedName(name) {
  return name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError";
}
async function micPermissionState() {
  try {
    if (!navigator.permissions || !navigator.permissions.query) return "";
    const st = await navigator.permissions.query({ name: "microphone" });
    return (st && st.state) || "";
  } catch (_) {
    return "";
  }
}
function micOriginLabel() {
  try {
    return location.origin || (location.protocol + "//" + location.host);
  } catch (_) {
    return "http://127.0.0.1";
  }
}
function micBlockedHint() {
  const origin = micOriginLabel();
  return "Microphone is blocked for " + origin + ". Chromium padlock → Site settings → Microphone → Allow (or chrome://settings/content/microphone), then press the mic or turn Voice off/on.";
}
function micRetryHint() {
  return "Microphone was not allowed. Press the mic, or turn Voice off and on, then Allow when Chromium asks.";
}
function markMicNeedsAllow(blocked) {
  micNeedsAllow = true;
  micPermBlocked = !!blocked;
  const btn = $("#micBtn");
  if (btn) {
    btn.title = blocked ? "Microphone blocked — open site settings" : "Allow microphone";
    btn.setAttribute("aria-label", btn.title);
  }
  const voiceBtn = $("#voiceModeBtn");
  if (voiceBtn && voiceMode) {
    voiceBtn.title = blocked
      ? "Mic blocked — reset in site settings"
      : "Allow microphone — click to ask again";
  }
}
function clearMicNeedsAllow() {
  if (!micNeedsAllow && !micPermBlocked) return;
  micNeedsAllow = false;
  micPermBlocked = false;
  if (micState === "idle") {
    const btn = $("#micBtn");
    if (btn && voiceMode) {
      btn.title = "Voice input";
      btn.setAttribute("aria-label", "Voice input");
    }
  }
  const voiceBtn = $("#voiceModeBtn");
  if (voiceBtn && voiceMode) voiceBtn.title = "Voice on";
}
async function getUserMediaAudio(audioConstraint, opts) {
  const retries = opts && opts.retries != null ? opts.retries : MIC_PERM_RETRIES;
  const shouldAbort = (opts && opts.shouldAbort) || (() => false);
  let last = null;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (shouldAbort()) {
      const err = new Error("aborted");
      err.name = "AbortError";
      throw err;
    }
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: audioConstraint });
    } catch (e) {
      last = e;
      if (!micPermDeniedName(e && e.name) || attempt >= retries) throw e;
      // Permanent Block: further getUserMedia calls will not re-prompt.
      if ((await micPermissionState()) === "denied") throw e;
      // Short yields — stay near the user gesture when Chromium still allows a re-prompt.
      await new Promise((r) => setTimeout(r, attempt === 0 ? 120 : 450));
    }
  }
  throw last || new Error("getUserMedia failed");
}
async function handleMicPermissionFailure(err) {
  if (!window.isSecureContext) {
    const msg = secureMicMessage();
    speechFail(msg);
    toast(msg, { warn: true, force: true });
    return;
  }
  const state = await micPermissionState();
  const blocked = state === "denied";
  markMicNeedsAllow(blocked);
  const msg = blocked ? micBlockedHint() : micRetryHint();
  speechFail(msg);
  toast(msg, { warn: true, force: true });
  if (err && err.name) {
    try { console.warn("mic permission:", err.name, state || "(unknown)"); } catch (_) {}
  }
}
async function ensureMicPermission() {
  if (!window.isSecureContext) {
    const msg = secureMicMessage();
    speechFail(msg);
    toast(msg, { warn: true, force: true });
    return false;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    speechFail("This browser cannot use the microphone.");
    return false;
  }
  try {
    const stream = await getUserMediaAudio(true, { retries: MIC_PERM_RETRIES });
    stream.getTracks().forEach((t) => t.stop());
    clearMicNeedsAllow();
    setMicNote("");
    return true;
  } catch (e) {
    if (e && e.name === "AbortError") return false;
    if (e && (e.name === "NotFoundError" || e.name === "DevicesNotFoundError")) {
      speechFail("No microphone was found. Plug in a USB mic (or headset), then try Voice again.");
      toast("No microphone was found. Plug in a USB mic (or headset), then try Voice again.", { warn: true, force: true });
      return false;
    }
    if (micPermDeniedName(e && e.name)) {
      await handleMicPermissionFailure(e);
      return false;
    }
    speechFail("Could not use the microphone.");
    toast("Could not use the microphone.", { warn: true, force: true });
    return false;
  }
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
      const msg = secureMicMessage();
      speechFail(msg);
      toast(msg, { warn: true, force: true });
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
    const gumOpts = {
      retries: MIC_PERM_RETRIES,
      shouldAbort: () => gen !== micGen || micStopWanted || !voiceMode,
    };
    try {
      const preferId = await realMicId();
      const withId = preferId ? Object.assign({ deviceId: { exact: preferId } }, micAudio) : micAudio;
      try {
        stream = await getUserMediaAudio(withId, gumOpts);
      } catch (err) {
        const name = err && err.name;
        if (name !== "OverconstrainedError" && name !== "NotSupportedError" && name !== "ConstraintNotSatisfiedError") throw err;
        stream = await getUserMediaAudio(true, gumOpts);
      }
      const opened = stream.getAudioTracks()[0];
      if (opened && virtualMic(opened.label)) {
        const id = await realMicId();
        if (id) {
          try {
            const next = await getUserMediaAudio(
              Object.assign({ deviceId: { exact: id } }, micAudio),
              { retries: 0, shouldAbort: gumOpts.shouldAbort }
            );
            stream.getTracks().forEach((t) => t.stop());
            stream = next;
          } catch (_) {}
        }
      }
      clearMicNeedsAllow();
    } catch (e) {
      if (e && e.name === "AbortError") {
        setMicUi("idle");
        return;
      }
      const name = e && e.name;
      if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        speechFail("No microphone was found. Plug in a USB mic (or headset), then try Voice again.");
      } else if (micPermDeniedName(name)) {
        await handleMicPermissionFailure(e);
      } else speechFail("Could not use the microphone.");
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
      // 250 ms timeslices hammer GC/compositor on the SwiftShader kiosk.
      // 1 s is enough for VAD end-of-utterance; final stop still flushes.
      rec.start(1000);
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
    if (!on) btn.title = "Voice off";
    else if (micNeedsAllow) {
      btn.title = micPermBlocked
        ? "Mic blocked — reset in site settings"
        : "Allow microphone — click to ask again";
    } else btn.title = "Voice on";
  }
}
async function setVoiceMode(on) {
  if (voicePowerBusy) return;
  on = !!on;
  if (on && !window.isSecureContext) {
    const msg = secureMicMessage();
    speechFail(msg);
    toast(msg, { warn: true, force: true });
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
    micNeedsAllow = false;
    micPermBlocked = false;
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
    // Request mic while the Voice click still counts as a user gesture.
    if (on) await ensureMicPermission();
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
if ($("#voiceModeBtn")) $("#voiceModeBtn").onclick = () => {
  // Re-trigger Allow without turning Voice off when a prior prompt was dismissed.
  if (voiceMode && micNeedsAllow && !micPermBlocked) {
    unlockSpeech();
    ensureMicPermission();
    return;
  }
  setVoiceMode(!voiceMode);
};
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
// Remote LAN on plain HTTP cannot use the mic (Chromium secure-context rule).
// Gateway redirects navigations to https:// when TLS is up; one quiet tip if not.
if (!window.isSecureContext && !detectLocalHost()) {
  try {
    const key = "stickllm.micHttpsHint";
    if (!sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, "1");
      setTimeout(() => toast(secureMicMessage(), { warn: true }), 1500);
    }
  } catch (_) {}
}

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
  // Desktop layout: starter apps (and Agent Zero's open_app for them) open in
  // a window on this page, so no pop-up permission is needed.
  if (window.stickDesk && window.stickDesk.handles(id)) return window.stickDesk.openApp(id);
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
function openAgentUrl(url, title) {
  if (!/^https?:\/\//i.test(url)) return false;
  const local = /^http:\/\/127\.0\.0\.1(?::\d+)?\/browser-pages\//.test(url);
  const desk = window.stickDesk;
  if (detectLocalHost() && desk && desk.openBrowser) { desk.openBrowser(url, title || "Agent Zero"); return true; }
  if (local) { toast("Agent Zero opened a page on the StickLLM screen; it can only be shown there."); return false; }
  const w = window.open(url, "_blank", "noopener");
  if (!w) toast("Agent Zero wants to open " + url + " — allow pop-ups for StickLLM.");
  return !!w;
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
// 0.6.1 (item 22): Agent Zero's open_url / open_file show a page in the
// user's browser (the kiosk browser window, or a new tab on a LAN browser).
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
  let authStop = false;

  function teardown() {
    if (!es) return;
    es.onerror = null;
    es.onopen = null;
    try { es.close(); } catch (e) { /* already closed */ }
    es = null;
  }

  function stopReconnect() {
    authStop = true;
    clearTimeout(timer);
    timer = null;
    teardown();
    gen++;
  }

  async function connect() {
    const mine = ++gen;
    clearTimeout(timer);
    teardown();
    // Abandoned Cursor Simple Browser / background tab: do not reconnect.
    if (document.visibilityState === "hidden") return;
    if (authStop || pairUiState === "unpaired") return;
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
      if (r.status === 401) {
        // Unpaired / lost session: stop the reconnect storm (no alert spam).
        stopReconnect();
        if (!detectLocalHost()) pairLost("This browser is no longer paired with the stick.");
        return;
      }
      if (r.ok) {
        const j = await r.json();
        if (j && j.t) url = "/api/ui/events?t=" + encodeURIComponent(j.t);
      }
    } catch (e) { /* cookie or loopback can still subscribe */ }
    if (mine !== gen || document.visibilityState === "hidden") return;
    es = new EventSource(url);
    es.onopen = () => { delay = 1000; authStop = false; };
    es.addEventListener("open_app", (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data || "{}"); } catch (err) { return; }
      if (data && data.id) openStickApp(String(data.id), typeof data.doc === "string" ? data.doc : "");
    });
    es.addEventListener("open_url", (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data || "{}"); } catch (err) { return; }
      if (data && typeof data.url === "string") openAgentUrl(data.url, String(data.title || ""));
    });
    es.addEventListener("install_started", (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data || "{}"); } catch (err) { return; }
      if (data && data.id) followAgentInstall(String(data.id), String(data.name || data.id));
    });
    es.addEventListener("install_confirm", (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data || "{}"); } catch (err) { return; }
      if (data && data.id) showAgentInstall(String(data.id), String(data.name || data.id));
    });
    es.onerror = () => {
      if (mine !== gen) return;
      teardown();
      if (document.visibilityState === "hidden" || pairUiState === "unpaired" || authStop) return;
      // 0.6.5: slower reconnect so flaky Wi‑Fi does not hammer the gateway
      // (and the remote client) with connection noise.
      const wait = delay;
      delay = Math.min(Math.max(delay * 2, 2000), 30000);
      clearTimeout(timer);
      timer = setTimeout(connect, wait);
    };
  }

  function resubscribe() {
    if (document.visibilityState === "hidden") return;
    if (pairUiState === "unpaired") return;
    authStop = false;
    if (es && es.readyState !== EventSource.CLOSED) return;
    delay = 1000;
    connect();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      stopReconnect();
      authStop = false; // allow resume when visible again
      return;
    }
    resubscribe();
  });
  window.addEventListener("pagehide", () => { stopReconnect(); });
  window.addEventListener("focus", resubscribe);
  startOpenAppEvents.resubscribe = resubscribe;
  startOpenAppEvents.stop = stopReconnect;
  connect();
}

// Desktop layout (desktop.js): the few page actions its launcher and tray
// call. app.js is an IIFE, so they are published here explicitly.
// The app URL for a desktop window: a paired LAN browser signs in to an
// add-on through its one-time open link (Agent: /api/agent/handoff); the
// kiosk and same-origin pages use the plain URL.
// 0.6.0 (B3): a stopped add-on is started from the launcher with progress,
// never opened as a dead page. Gives up waiting after 3 min; the app page
// itself keeps reloading until the app answers.
async function startAddon(id, a) {
  const name = (a && (a.display_name || a.name)) || id;
  const p = progressToast("Starting " + name + "…");
  const t0 = Date.now();
  try {
    while (Date.now() - t0 < 180000) {
      const r = await fetch("/api/apps/start", {
        method: "POST", cache: "no-store",
        headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ id }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { p.done(j.message || ("Could not start " + name)); return false; }
      if (j.running) { a.running = true; p.done(name + " is ready"); return true; }
      if (j.state && !["starting", "installing"].includes(j.state)) { p.done(j.message || (name + " did not start")); return false; }
      p.update("Starting " + name + "… " + Math.round((Date.now() - t0) / 1000) + " s");
      await new Promise((res) => setTimeout(res, 1500));
    }
  } catch (_) {}
  p.done(name + " is still starting");
  return false;
}
// 0.6.0 (A6): Agent Zero's install_app started a verified add-on's install
// (the Apps page's own stickllm-addon-install@ unit). This screen shows the
// progress, refreshes the catalog so the desktop icon appears, then opens the
// app in its own window. Gives up following after 30 min; the Apps page still
// shows the state.
const agentInstalls = new Set();
async function followAgentInstall(id, name) {
  if (!/^[a-z][a-z-]{0,23}$/.test(id) || agentInstalls.has(id)) return;
  agentInstalls.add(id);
  const p = progressToast("Installing " + name + "…");
  const t0 = Date.now();
  try {
    while (Date.now() - t0 < 1800000) {
      await new Promise((res) => setTimeout(res, 2000));
      await refreshApps().catch(() => {});
      const a = catalogApps.get(id);
      if (a && a.installed) {
        p.done(name + " is installed");
        openStickApp(id, "");
        return;
      }
      if (a && a.state && !["installing", "pulling", "starting", "not_installed", ""].includes(a.state)) {
        p.done(String(a.message || a.label || (name + " did not install")));
        return;
      }
      p.update("Installing " + name + "… " + Math.round((Date.now() - t0) / 1000) + " s");
    }
    p.done(name + " is still installing (see Apps)");
  } finally {
    agentInstalls.delete(id);
  }
}
async function deskAppUrl(id, opts) {
  if (id === "agent") {
    // Chat iframe + stick kiosk: always /agent-zero/ (never raw :5099).
    // LAN pop-out only: mint :5443 handoff.
    if (!(opts && opts.embed === false) || detectLocalHost()) {
      return agentPageUrl(agentLastStatus, { embed: true });
    }
    let fallback = ($("#agentLink") && $("#agentLink").href) || "";
    if (fallback.indexOf("/agent-zero") >= 0) fallback = "";
    if (agentUrlIsLoopback(fallback)) fallback = "";
    if (!fallback) fallback = agentPageUrl(agentLastStatus, { embed: false });
    if (fallback && fallback.indexOf("/agent-zero") >= 0) fallback = "";
    if (agentUrlIsLoopback(fallback)) fallback = agentPageUrl(null, { embed: false });
    if (token) {
      try {
        const r = await fetch("/api/agent/handoff", {
          method: "POST", cache: "no-store",
          headers: authHeaders({ "Content-Type": "application/json" }), body: "{}",
        });
        const j = await r.json().catch(() => ({}));
        if (r.ok && j.url && !agentUrlIsLoopback(j.url)) return j.url;
      } catch (_) {}
    }
    return fallback || agentPageUrl(agentLastStatus, { embed: true });
  }
  const a = catalogApps.get(id);
  if (!a || !a.open_url) return "";
  if (a.installer === "stickllm-addon" && a.installed && !a.running) await startAddon(id, a);
  if (a.open_link && !detectLocalHost() && token) {
    try {
      const r = await fetch(a.open_link, {
        method: "POST", cache: "no-store",
        headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ id }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.url) return j.url;
    } catch (_) {}
  }
  return a.open_url;
}
function deskCatalog() {
  return [...catalogApps.values()].filter(deskAppOpenable).map((a) => {
    const g = DESK_APP_GLYPHS[a.id] || { label: a.tile || a.name || a.id, color: "#475569", svg: '<rect x="4" y="4" width="16" height="16" rx="3"/>' };
    return { id: a.id, title: a.display_name || a.name || g.label, label: g.label, color: g.color, svg: g.svg,
      frame: a.frame !== false, running: !!a.running, state: a.state || "" };
  });
}
function deskAgent() {
  const link = $("#agentLink");
  const s = agentLastStatus || {};
  const seed = !!(s.preinstalled || s.image_present || (s.drive && s.drive.seed_ready));
  const installed = !!(link && !link.hidden) || agentIsInstalled(s) || seed
    || s.state === "stopped" || s.state === "running" || s.state === "starting";
  // Prefer API running flag; never require a non-existent "upstream" field.
  const running = !!(s.running || s.state === "running");
  // Only true Install when the gateway says so — not when status is still empty.
  const needsInstall = !!(s.needs_install || s.state === "needs_install" || s.state === "pull_failed")
    && !seed && !running && s.state !== "stopped" && s.state !== "starting";
  return { installed: installed, href: (link && link.href) || agentPageUrl(s),
    state: ($("#agentLinkState") && $("#agentLinkState").textContent) || "",
    status: s.state || "", running: running,
    message: agentProgressLine(s) || s.message || "", progress: s.progress, step: s.step, steps: s.steps,
    needsInstall: needsInstall,
    busy: s.state === "installing" || s.state === "starting",
    preinstalled: seed,
    vaultUnlocked: !!(s.vault_unlocked || state.vaultOpen) };
}
window.stickApp = Object.freeze({
  openSettings, closeSettings, showSec, lockVault, showApps, toast,
  setSessionMode, setWebMode, refreshWebMode, focusVaultUnlock, refreshApps, refreshAgentLink, refreshModels, installAgent,
  ensureAgentZeroStarted, moveAgentDrive, renderA0Drive, agentHttpReady,
  deskAppUrl, deskCatalog, deskAgent, control, agentFastPoll, authHeaders,
  sessionMode: () => state.mode, webMode: () => webMode, vaultOpen: () => !!state.vaultOpen,
  setupDone: () => setupDone(), setupBlocksAgent: () => setupBlocksAgent(),
});
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

// 0.6.1 (item 25): Settings > Agent Zero > Unlock all plugins.
(function a0PluginsSwitch() {
  const box = document.getElementById("a0PluginsUnlocked");
  const msg = document.getElementById("a0PluginsMsg");
  if (!box) return;
  const load = () => fetch("/api/agent/plugins", { cache: "no-store", headers: authHeaders() })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => { if (j && typeof j.unlocked === "boolean") box.checked = j.unlocked; })
    .catch(() => {});
  box.addEventListener("change", async () => {
    const want = box.checked;
    try {
      const r = await fetch("/api/agent/plugins", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
        body: JSON.stringify({ unlocked: want }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) { box.checked = !want; toast((j && j.message) || "Could not save the plugin setting"); return; }
      if (msg) msg.textContent = j.message || "Saved.";
    } catch (e) { box.checked = !want; toast("Could not save the plugin setting"); }
  });
  load();
})();

if ($("#setupWizardBtn")) $("#setupWizardBtn").onclick = () => openSetupWizard({ force: true });


async function refreshActiveVaultUI(v) {
  const pathEl = $("#activeVaultPath");
  if (!pathEl) return;
  const root = (v && (v.root || v.path || v.mount || v.blob)) || "";
  const st = (v && (v.status || v.state)) || "";
  pathEl.textContent = root ? (String(root) + (st ? " · " + st : "")) : "No vault unlocked";
}
async function loadVaultChoices() {
  const box = $("#vaultChoices");
  if (!box) return;
  box.hidden = false;
  box.innerHTML = "<small>Searching…</small>";
  try {
    const res = await control("vault_search", {});
    const hits = Array.isArray(res.hits) ? res.hits : (Array.isArray(res.vaults) ? res.vaults : (Array.isArray(res.results) ? res.results : []));
    if (!hits.length) {
      box.innerHTML = "<small class=\"muted\">No vault files found. Use Choose… under Create, or Search for vault.</small>";
      return;
    }
    box.innerHTML = hits.map((h) => {
      const p = h.path || h.blob || h;
      return `<button class="drive-pick" type="button" data-vaultpick="${esc(String(p))}"><b>${esc(String(p))}</b><small>${esc(h.label || h.kind || "")}</small></button>`;
    }).join("");
    box.querySelectorAll("[data-vaultpick]").forEach((b) => {
      b.onclick = async () => {
        const path = b.dataset.vaultpick;
        if ($("#vaultPath")) $("#vaultPath").value = path.replace(/\/stickllm-vault\.img$/, "").replace(/\/$/, "");
        try {
          await control("vault_bind", { path });
        } catch (_) {
          try { await control("vault_use", { path }); } catch (e2) { showError(e2, "Could not select vault"); return; }
        }
        toast("Vault selected — unlock with your passcode");
        box.hidden = true;
        try { await refreshStorage(); } catch (_) {}
      };
    });
  } catch (e) {
    box.innerHTML = "<small class=\"muted\">Search unavailable — use Search for vault below.</small>";
  }
}
if ($("#switchVaultBtn")) $("#switchVaultBtn").onclick = () => loadVaultChoices();


/* 0.6.5: StickLLM chat UI + Chat icon retired — Agent Zero is the only chat.
   Hide composer / New chat / chat-slide chrome (not merely disable). In deskMode
   #app is no longer mounted as Chat, so park/hide the whole shell so it cannot
   paint through the transparent desktop wall. */
(function hideStickllmChatChrome() {
  try {
    document.documentElement.classList.add("a0-main-chat");
    const style = document.createElement("style");
    style.id = "a0-main-chat-hide";
    style.textContent = `
      html.a0-main-chat #app .thread,
      html.a0-main-chat #app #thread,
      html.a0-main-chat #app .chatThread,
      html.a0-main-chat #app .composer,
      html.a0-main-chat #app #composer,
      html.a0-main-chat #app #composerNote,
      html.a0-main-chat #app #composerPerf,
      html.a0-main-chat #app .composerNote,
      html.a0-main-chat #app .top,
      html.a0-main-chat #app .chatTitle,
      html.a0-main-chat #app #chatTitle,
      html.a0-main-chat #app #menuBtn,
      html.a0-main-chat #app #collapseBtn,
      html.a0-main-chat #app .sidebar,
      html.a0-main-chat #app #sidebar,
      html.a0-main-chat #app #newChatBtn,
      html.a0-main-chat #app #convList,
      html.a0-main-chat #app .convList,
      html.a0-main-chat #app .sideHint,
      html.a0-main-chat #app .modeSeg,
      html.a0-main-chat #app .a0Toggle,
      html.a0-main-chat #a0Toggle,
      html.a0-main-chat .a0Full,
      html.a0-main-chat body.deskMode > #app,
      html.a0-main-chat body.deskMode #app.collapsed #menuBtn,
      body.deskMode #app > .main > .thread,
      body.deskMode #app > .main > #thread,
      body.deskMode #app > .main > .composer,
      body.deskMode #app > .main > .top,
      body.deskMode #app > .sidebar,
      body.deskMode .wallIcon[data-app="chat"] { display: none !important; }
      .sshDetails{margin-top:10px;padding-top:10px;border-top:1px solid var(--line,rgba(255,255,255,.12))}
      .sshDetails .mono{font-size:13px;word-break:break-all;margin:6px 0}
      .wifiList button.selected{background:rgba(58,160,255,.18)}
    `;
    document.head.appendChild(style);
  } catch (_) {}
})();
// Do not auto-start Agent Zero on model-ready / vault-unlock / timer — first-boot
// and wizard-end opens break A0; user opens Chat from the desktop when ready.
document.addEventListener("stickllm:vault-unlocked", () => {
  try { refreshAgentLink(); } catch (_) {}
});
try { hardenVaultPassFields($("#vaultPass"), $("#np1"), $("#np2"), $("#deleteVaultPass")); } catch (_) {}
