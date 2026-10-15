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
let sessionModeBusy = false;
let activeChatId = null;
let lastRemintId = null;
let lastCatalog = [];
let selectedModelId = null;
let dlPollTimer = null;
let vaultBrowsePath = "";
let vaultPickerMount = "";
let vaultBrowseBlobPath = "";
const messages = [{
  role: "system",
  content: "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful.",
}];
const state = {
  mode: "ephemeral", vaultOpen: false, web: true, theme: "dark",
  chats: [], ephemeral: [], current: null, attach: [],
};

function authHeaders(extra = {}) {
  const h = { "X-StickLLM-Client": "ui", ...extra };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}
function clearPairSession() {
  token = ""; localStorage.removeItem(TOKEN_KEY);
}
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
    clearPairSession();
    toast("Pair required — enter the code from the stick screen");
    openSettings("devices");
    throw new Error("Pair required");
  }
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || j.message || `HTTP ${r.status}`);
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
  $("#composerNote").textContent = m === "vault"
    ? "Vault session · runs locally"
    : "Ephemeral · runs locally";
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
      if (st === "absent" || !st) {
        applyModeUi(prev);
        toast("No vault yet — create or attach one in Storage");
        openSettings("storage");
        return;
      }
      if (!(st === "unlocked" || vault.mounted)) {
        applyModeUi(prev);
        toast("Unlock the vault first");
        openSettings("storage");
        $("#vaultPass")?.focus();
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

function setVaultChrome(open) {
  state.vaultOpen = open;
  $("#vaultCard")?.classList.toggle("open", open);
  if ($("#vcState")) $("#vcState").textContent = open ? "Vault unlocked" : "Vault locked";
  if ($("#unlockForm")) $("#unlockForm").hidden = open;
  if ($("#lockBtn2")) $("#lockBtn2").hidden = !open;
  if ($("#lockBtn")) $("#lockBtn").hidden = !open;
  if ($("#popVault")) $("#popVault").textContent = open ? "Unlocked" : "Locked";
}

async function lockVault() {
  try {
    const res = await control("vault_lock");
    toast(res.ok !== false ? "Vault locked" : ("Lock failed: " + (res.error || "unknown")));
    setVaultChrome(false);
    if (sessionMode === "vault") await setSessionMode("ephemeral");
  } catch (e) { toast("Lock failed: " + e.message); }
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
function msgHtml(m) {
  const src = m.src?.length
    ? `<details class="sources"><summary>${m.src.length} web source${m.src.length > 1 ? "s" : ""}</summary>${m.src.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>`).join("")}</details>`
    : "";
  const cls = m.r === "system" ? "system" : m.r;
  const av = m.r === "ai" ? "S" : m.r === "system" ? "!" : "";
  return `<div class="msg ${cls}"><div class="av">${av}</div><div class="body">${m.pending ? '<span class="typing"><i></i><i></i><i></i></span>' : md(m.t)}${src}</div></div>`;
}
function renderThread() {
  const th = $("#thread"), c = state.current;
  $("#chatTitle").textContent = c ? c.title : "New chat";
  if (!c || !c.msgs.length) {
    th.innerHTML = `<div class="empty"><span class="logo lg"></span><h2>What can I help with?</h2>
      <p>Everything runs on this stick. ${state.mode === "vault" ? "Vault mode." : "Ephemeral — lost at reboot."}</p>
      <div class="sugg"><button>Summarize a long article I paste in</button><button>Write a bash script to rename photos by date</button>
      <button>Explain how LUKS encryption works</button><button>Draft a polite follow-up email</button></div></div>`;
    $$(".sugg button", th).forEach((b) => (b.onclick = () => { $("#input").value = b.textContent; send(); }));
    return;
  }
  th.innerHTML = `<div class="msgs">${c.msgs.map(msgHtml).join("")}</div>`;
  th.scrollTop = th.scrollHeight;
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
    html += state.chats.map((c) =>
      `<button class="conv ${state.current && state.current.id === c.id ? "on" : ""}" data-v="${esc(c.id)}"><span>${esc(c.title || c.id)}</span></button>`
    ).join("");
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
  const ul = $("#unlockLink"); if (ul) ul.onclick = () => { openSettings("storage"); setTimeout(() => $("#vaultPass").focus(), 50); };
}
function openChat(c) { state.current = c; activeChatId = c?.id || null; renderThread(); renderConvs(); }
function newChat() {
  state.current = null; activeChatId = null;
  messages.length = 1;
  messages[0] = { role: "system", content: "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful." };
  renderThread(); renderConvs(); $("#input").focus();
}
$("#newChatBtn").onclick = () => { newChat(); if (mobile()) toggleNav(false); };

async function ensurePaired(force = false) {
  try {
    const st = await pairStatus();
    if (st.local) { isLocalMode = true; return true; }
    if (!st.require_pair) return true;
    if (token && !force) {
      const t = await fetch("/api/storage", { headers: authHeaders(), cache: "no-store" });
      if (t.ok) return true;
      if (t.status === 401) clearPairSession();
    }
    openSettings("devices");
    toast("Enter the pair code from the stick screen");
    return false;
  } catch (_) { return true; }
}

function formatPerfBits(stats) {
  if (!stats) return "";
  const bits = [];
  if (stats.genTps != null) bits.push(`${stats.genTps.toFixed(1)} tok/s`);
  if (stats.promptTps != null) bits.push(`prompt ${stats.promptTps.toFixed(1)} tok/s`);
  if (stats.genTok != null) bits.push(`${stats.genTok} tok`);
  if (stats.ms != null) bits.push(`${(stats.ms / 1000).toFixed(1)}s`);
  if (stats.est) bits.push("~est");
  return bits.join(" · ");
}
function updatePerfStrip(stats) {
  const text = formatPerfBits(stats);
  // Bottom line under composer (under the composer) — primary place.
  const bottom = $("#composerPerf");
  if (bottom) {
    bottom.textContent = text ? " · " + text : "";
    bottom.hidden = !text;
  }
  // Keep a copy on the yellow TEST banner too.
  const top = $("#testPerf");
  if (top) {
    top.textContent = text ? " · " + text : "";
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
    ms: wallMs,
    est: true,
  };
}

async function send() {
  const inp = $("#input");
  const text = inp.value.trim();
  if (!text) return;
  if (!(await ensurePaired())) return;
  if (!state.current) {
    const c = { id: Date.now(), title: text.slice(0, 40), msgs: [] };
    state.ephemeral.unshift(c); state.current = c;
  }
  const c = state.current;
  c.msgs.push({ r: "user", t: text });
  const pend = { r: "ai", pending: true }; c.msgs.push(pend);
  messages.push({ role: "user", content: text });
  inp.value = ""; autosize(); renderThread(); renderConvs();
  $("#sendBtn").disabled = true;
  const t0 = performance.now();
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        model: "stickllm", messages, stream: false, temperature: 0.7,
        web: state.web ? "on" : "off",
      }),
    });
    if (r.status === 401) {
      clearPairSession();
      pend.pending = false; pend.t = "Pair required — enter the code from the stick screen.";
      pend.r = "system";
      openSettings("devices");
      return;
    }
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { const err = await r.json(); msg = err.message || err.error || msg; } catch (_) {}
      throw new Error(msg);
    }
    const data = await r.json();
    const wallMs = performance.now() - t0;
    let reply = data?.choices?.[0]?.message?.content?.trim() || "(empty response)";
    const webInfo = data?.stickllm_web;
    let src = [];
    if (webInfo?.used && webInfo.results?.length) {
      src = webInfo.results.slice(0, 3).map((x) => x.url).filter(Boolean);
    }
    messages.push({ role: "assistant", content: reply });
    pend.pending = false; pend.t = reply; if (src.length) pend.src = src;
    updatePerfStrip(perfFromChatResponse(data, wallMs, reply));
    if (sessionMode === "vault" && state.vaultOpen) saveCurrentChat(true).catch(() => {});
  } catch (e) {
    pend.pending = false; pend.r = "system"; pend.t = "Error: " + e.message;
  } finally {
    $("#sendBtn").disabled = false; renderThread(); renderConvs(); $("#input").focus();
  }
}
$("#composer").onsubmit = (e) => { e.preventDefault(); send(); };
const autosize = () => { const i = $("#input"); i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 200) + "px"; };
$("#input").addEventListener("input", autosize);
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
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
  if (sec === "models") refreshModels().catch((e) => toast(e.message));
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
$$(".setNav [data-sec]").forEach((b) => (b.onclick = () => showSec(b.dataset.sec)));
$$("[data-sec-go]").forEach((b) => (b.onclick = () => showSec(b.dataset.secGo)));
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

function renderModelsList() {
  const list = $("#modelList");
  if (!lastCatalog.length) {
    list.innerHTML = '<div class="row"><small>No catalog entries. Refresh after pairing.</small></div>';
    return;
  }
  list.innerHTML = lastCatalog.map((m) => {
    const id = m.id;
    const name = m.name || id;
    const q = m.quant || m.q || "";
    const gbRaw = m.approx_size_gb ?? m.size_gb ?? (m.bytes != null ? m.bytes / 1e9 : null);
    const gb = gbRaw != null && gbRaw !== "" ? Number(gbRaw).toFixed(Number(gbRaw) >= 10 ? 1 : 2) : "?";
    const have = !!m.installed;
    const active = !!m.active;
    const run = !!m.running;
    const loading = active && !run;
    const rec = !!m.recommended;
    const sel = id === selectedModelId;
    const sizeBit = have ? `${gb} GB on disk` : `~${gb} GB`;
    return `<label class="model ${sel ? "sel" : ""}">
      <input type="radio" name="model" value="${esc(id)}" ${sel ? "checked" : ""}>
      <div class="mi"><b>${esc(name)}</b> <span class="muted small">${esc(q)}</span>
      <small>${sizeBit}${have ? "" : " · not downloaded"}${m.runnable === false && have ? " · won't fit" : ""}</small></div>
      ${run ? '<span class="pill ok">running</span>' : ""}${loading ? '<span class="pill warn">loading</span>' : ""}${rec ? '<span class="pill acc">recommended</span>' : ""}${!have ? '<span class="pill">download</span>' : ""}
    </label>`;
  }).join("");
  $$("#modelList input").forEach((i) => (i.onchange = () => {
    selectedModelId = i.value; renderModelsList(); syncModelActions();
  }));
  syncModelActions();
}
function syncModelActions() {
  const m = lastCatalog.find((x) => x.id === selectedModelId);
  if (!m) { $("#selHint").textContent = "Select a model"; return; }
  $("#selHint").textContent = `Selected: ${m.name || m.id}`;
  $("#dlModel").hidden = !!m.installed;
  $("#activate").hidden = !m.installed || m.runnable === false;
  $("#delModel").hidden = !m.deletable;
  $("#activate").textContent = m.running ? "Reload with these settings" : (m.active ? "Still loading… (tap to retry)" : "Load model");
  const max = Number(m.ctx_max || m.ctxMax || 32768);
  $("#ctx").max = max;
  if (+$("#ctx").value > max) $("#ctx").value = max;
  $("#ctxVal").textContent = (+$("#ctx").value).toLocaleString();
}
async function refreshModels() {
  if (!(await ensurePaired())) return;
  const st = await control("status");
  lastCatalog = st.catalog || [];
  const probe = st.probe || {};
  const run = lastCatalog.find((m) => m.running || m.active) || lastCatalog.find((m) => m.installed);
  if (!selectedModelId && run) selectedModelId = run.id;
  if (!selectedModelId && lastCatalog[0]) selectedModelId = lastCatalog[0].id;
  const sum = $("#sec-models .summary");
  if (sum) {
    const name = st.connect?.model || run?.name || "none";
    const rec = probe.recommend_id || probe.recommend || "—";
    $$("#sec-models .summary b")[0] && ($$("#sec-models .summary b")[0].textContent = name);
    const pill = $("#sec-models .summary .pill");
    if (pill) {
      const activeLoading = lastCatalog.some((m) => m.active && !m.running);
      if (st.llama_ok || st.llama?.status === "ok") {
        pill.textContent = "running";
        pill.className = "pill ok";
      } else if (activeLoading) {
        pill.textContent = "loading";
        pill.className = "pill warn";
      } else {
        pill.textContent = "not loaded";
        pill.className = "pill";
      }
    }
    if ($$("#sec-models .summary b")[1]) $$("#sec-models .summary b")[1].textContent = String(rec);
    if ($("#modelDir")) $("#modelDir").textContent = st.download_dir || st.models_dir || "…";
  }
  renderDownload(st.download || {});
  renderModelsList();
}
function renderDownload(d) {
  const box = $("#dlBox");
  const state_ = d?.state || "idle";
  if (!["downloading", "verifying", "starting", "failed", "done"].includes(state_)) {
    box.hidden = true; return;
  }
  box.hidden = false;
  $("#dlName").textContent = (state_ === "done" ? "Downloaded " : "Downloading ") + (d.name || d.id || "model");
  const pct = d.percent == null ? (state_ === "done" ? 100 : 10) : Number(d.percent);
  $("#dlFill").style.width = Math.max(2, Math.min(100, pct)) + "%";
  $("#dlPct").textContent = Math.round(pct) + "%";
  $("#dlMeta").textContent = d.note || `${fmtBytes(d.bytes_done)} / ${fmtBytes(d.bytes_total)}`;
}
function startDlPoll() {
  stopDlPoll();
  dlPollTimer = setInterval(async () => {
    try {
      const st = await control("status");
      renderDownload(st.download || {});
      const s = st.download?.state;
      if (!s || s === "idle" || s === "done" || s === "failed") {
        stopDlPoll();
        lastCatalog = st.catalog || lastCatalog;
        renderModelsList();
      }
    } catch (_) {}
  }, 1500);
}
function stopDlPoll() { if (dlPollTimer) { clearInterval(dlPollTimer); dlPollTimer = null; } }

$("#ctx").addEventListener("input", () => {
  $("#ctxVal").textContent = (+$("#ctx").value).toLocaleString();
});
$$("#presets button").forEach((b) => (b.onclick = () => {
  const map = { fast: 4096, balanced: 8192, long: 32768 };
  const v = map[b.dataset.preset] || 8192;
  $("#ctx").value = Math.min(v, +$("#ctx").max);
  $("#ctxVal").textContent = (+$("#ctx").value).toLocaleString();
  $$("#presets button").forEach((x) => x.classList.toggle("on", x === b));
  toast("Context preset → " + $("#ctx").value + " (sampling knobs greyed)");
}));
$("#probeBtn").onclick = async () => {
  try { toast("Probing GPU…"); await control("model_probe"); await refreshModels(); toast("Probe done"); }
  catch (e) { toast(e.message); }
};
$("#refreshCatalog").onclick = () => refreshModels().then(() => toast("Catalog refreshed")).catch((e) => toast(e.message));
let loadPollTimer = null;
function stopLoadPoll() { if (loadPollTimer) { clearInterval(loadPollTimer); loadPollTimer = null; } }
function startLoadPoll(expectName) {
  stopLoadPoll();
  let ticks = 0;
  loadPollTimer = setInterval(async () => {
    ticks += 1;
    try {
      await refreshStatus();
      await refreshModels().catch(() => {});
      const r = await fetch("/api/health", { cache: "no-store" });
      const j = await r.json().catch(() => ({}));
      if (j.llama_ok) {
        stopLoadPoll();
        toast("Model ready" + (expectName ? `: ${expectName}` : ""));
        await refreshStatus();
        return;
      }
      // Soft progress while llama is still coming up (weights load has no exact %).
      const soft = Math.min(92, 8 + ticks * 3);
      setChipLoad(true, soft, expectName);
      if (ticks > 120) { stopLoadPoll(); toast("Still loading — check Models"); }
    } catch (_) {}
  }, 2000);
}
function setChipLoad(loading, pct, name) {
  const chip = $("#statusChip");
  const bar = $("#chipLoad");
  const fill = $("#chipLoadFill");
  if (!chip) return;
  chip.classList.toggle("loading", !!loading);
  chip.classList.toggle("ready", !loading && !!name && name !== "none");
  if (bar) bar.hidden = !loading;
  if (fill && loading) fill.style.width = Math.max(4, Math.min(100, Number(pct) || 10)) + "%";
  if ($("#chipModel")) {
    if (loading) {
      const label = name && name !== "none" ? name : "model";
      const p = pct != null ? ` ${Math.round(pct)}%` : "";
      $("#chipModel").textContent = `loading ${label}${p}`;
    }
  }
  $("#statusChip .dot")?.classList.toggle("ok", !loading);
  $("#statusChip .dot")?.classList.toggle("busy", !!loading);
}

$("#activate").onclick = async () => {
  const m = lastCatalog.find((x) => x.id === selectedModelId);
  if (!m) return toast("Select a model");
  try {
    const name = m.name || m.id;
    setChipLoad(true, 5, name);
    toast("Loading " + name + "…");
    const res = await control("model_activate", { id: m.id, ctx_size: +$("#ctx").value });
    if (!res.ok && res.error) throw new Error(res.error);
    if (res.running || res.load_state === "running") {
      stopLoadPoll();
      setChipLoad(false, 100, name);
      toast("Model running: " + name);
    } else {
      toast("Model loading into GPU/RAM…");
      startLoadPoll(name);
    }
    await refreshModels(); await refreshStatus();
  } catch (e) {
    stopLoadPoll();
    setChipLoad(false, 0, null);
    toast(e.message);
  }
};
$("#dlModel").onclick = async () => {
  const m = lastCatalog.find((x) => x.id === selectedModelId);
  if (!m) return;
  try {
    const res = await control("model_download", { id: m.id });
    renderDownload(res.download || { state: "starting", id: m.id, name: m.name });
    startDlPoll(); toast("Download started");
  } catch (e) { toast(e.message); }
};
$("#delModel").onclick = () => {
  const m = lastCatalog.find((x) => x.id === selectedModelId);
  if (!m?.deletable) return toast("This model cannot be deleted");
  confirmBox({
    title: "Delete model files?",
    text: `Permanently delete ${m.name || m.id}?`,
    word: "ARE YOU SURE", ok: "Delete files",
    cb: async () => {
      try {
        await control("model_delete", { id: m.id, confirm: "ARE YOU SURE" });
        toast("Deleted"); await refreshModels();
      } catch (e) { toast(e.message); }
    },
  });
};

async function refreshStorage() {
  if (!(await ensurePaired())) return;
  const st = await control("status");
  const v = st.vault || {};
  const open = String(v.status || "").toLowerCase() === "unlocked" || !!v.mounted;
  setVaultChrome(open);
  if ($("#vcSub")) {
    $("#vcSub").textContent = v.blob || v.root || v.path || (v.status || "absent");
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
async function openLivePicker(startPath) {
  $("#picker").hidden = false;
  $("#fpTitle").textContent = "Choose folder / vault";
  $("#fpFileTools").hidden = true;
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
    $("#fpSide").innerHTML = '<div class="fpSideLab">Current</div><div class="row"><small class="mono">' + esc(vaultBrowsePath) + "</small></div>";
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
  $("#picker").hidden = true;
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
$("#actFindVault").onclick = async () => {
  try {
    toast("Searching…");
    const res = await control("vault_find");
    const box = $("#findHits"); box.hidden = false;
    const hits = res.hits || res.found || (res.best ? [res.best] : []);
    if (!hits.length && !res.blob && !res.path) {
      box.innerHTML = `<div class="row"><small>${esc(res.note || "No stickllm-vault.img found")}</small></div>`;
      return;
    }
    const best = res.best || hits[0] || { blob: res.blob || res.path };
    const blob = best.blob || best.path || "";
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
  } catch (e) { toast(e.message); }
};
$("#actFindModels").onclick = async () => {
  try {
    const res = await control("vault_find_models");
    const box = $("#findHits"); box.hidden = false;
    const hits = res.models || res.hits || [];
    if (!hits.length) {
      box.innerHTML = '<div class="row"><small>No .gguf models found on scanned mounts.</small></div>';
      return;
    }
    box.innerHTML = hits.slice(0, 12).map((m) =>
      `<div class="row"><div><b>${esc(m.name || m.path)}</b><small class="mono">${esc(m.path || "")}</small></div></div>`
    ).join("");
    toast(`Found ${hits.length} model(s)`);
  } catch (e) { toast(e.message); }
};
$("#pickVault").onclick = () => {
  if (vaultBrowsePath || $("#vaultPath").value) openLivePicker($("#vaultPath").value || vaultBrowsePath || "/mnt");
  else refreshDrivesLive().then(() => {
    const first = $("#drives [data-path]");
    if (first) openLivePicker(first.dataset.path);
    else toast("Mount a drive first");
  });
};
$("#pickCreate").onclick = () => $("#pickVault").click();

$("#unlockForm").onsubmit = async (e) => {
  e.preventDefault();
  const pass = $("#vaultPass").value || "";
  if (!pass) return toast("Enter the vault passcode");
  try {
    const payload = { passcode: pass };
    const bind = ($("#vaultPath").value || "").trim();
    if (bind) payload.path = bind;
    const res = await control("vault_unlock", payload);
    $("#vaultPass").value = "";
    if (!res.ok) throw new Error(res.error || res.stderr || "unlock failed");
    setVaultChrome(true);
    toast("Vault unlocked");
    await setSessionMode("vault");
    await refreshStorage();
  } catch (err) { toast("Unlock failed: " + err.message); }
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
  $$("[data-dc]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this chat?")) return;
    try {
      const r = await fetch("/api/chats", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ delete: true, id: b.dataset.dc }),
      });
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || "delete failed");
      await loadVaultChats(); toast("Deleted");
    } catch (e) { toast(e.message); }
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
  if (!/^\d{4,8}$/.test(c)) return;
  if ($("#pairCodeShow")) $("#pairCodeShow").textContent = formatPairCode(c);
  pushSystemMsg(
    `New PAIR CODE: ${c} — open the LAN URL on phone/desktop and enter this code. Previous paired browsers were unpaired.`
  );
}
/** Stick kiosk: pick up codes reminted from a LAN browser (never sent over the wire). */
function announceRemintFromConnect(connect) {
  if (!(isLocalMode || detectLocalHost())) return;
  const c = connect || {};
  const rid = String(c.remint_id || "").trim();
  const code = String(c.pair_code || "").trim();
  if (lastRemintId === null) {
    lastRemintId = rid;
    return;
  }
  if (!rid || rid === lastRemintId) return;
  lastRemintId = rid;
  if (!/^\d{4,8}$/.test(code)) return;
  showPairCodeOnStick(code);
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
  try {
    clearPairSession();
    const j = await remintPairCode();
    const rid = String(j.remint_id || "").trim();
    if (rid) lastRemintId = rid;
    const code = String(j.pair_code || "").trim();
    if (code) {
      isLocalMode = true;
      showPairCodeOnStick(code);
      toast("PAIR CODE in chat — press F9 again for a new one");
    } else {
      if ($("#pairCodeShow")) $("#pairCodeShow").textContent = "(see stick screen)";
      pushSystemMsg("New pair code minted on the stick. Enter the PAIR CODE shown on the stick screen chat.");
      toast("Look at the stick screen for the new PAIR CODE");
    }
    await refreshStatus();
  } catch (e) { toast(e.message); }
}
async function issueSshHotkey() {
  // Show SSH password on stick (loopback). Never on LAN.
  try {
    const r = await fetch("/api/health", { cache: "no-store" });
    const j = await r.json().catch(() => ({}));
    const c = j.connect || {};
    const pass = String(c.ssh_password || "").trim();
    const enabled = !!c.ssh_enabled;
    const user = c.ssh_user || "stickllm";
    const host = c.ssh_host || c.ip || "127.0.0.1";
    if (!(isLocalMode || detectLocalHost())) {
      toast("SSH password only on the stick screen (press F10 there)");
      pushSystemMsg("SSH password is only shown on the stick itself — press F10 on the Server/kiosk screen.");
      return;
    }
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
$("#pairForm").onsubmit = async (e) => {
  e.preventDefault();
  const v = $("#pairIn").value.trim();
  const err = $("#pairErr");
  if (!/^\d{4,8}$/.test(v)) { err.hidden = false; err.textContent = "Enter the code from the stick screen"; return; }
  try {
    const r = await fetch("/api/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-StickLLM-Client": "ui" },
      body: JSON.stringify({ code: v }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.message || j.error || "Pair failed");
    token = j.token; localStorage.setItem(TOKEN_KEY, token);
    err.hidden = true; $("#pairIn").value = "";
    toast("Browser paired"); closeSettings();
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
    toast(res.online ? "Online via WiFi" : "WiFi profile saved — waiting for uplink");
    await refreshStatus();
  } catch (e) { toast(e.message); }
};

async function refreshStatus() {
  try {
    const r = await fetch("/api/health", { cache: "no-store" });
    if (!r.ok && r.status !== 503) throw new Error("health " + r.status);
    const j = await r.json();
    if (j.pair?.local || detectLocalHost()) isLocalMode = true;
    if (j.session_mode) applyModeUi(j.session_mode === "vault" ? "vault" : "ephemeral");
    const rawName = String(j.connect?.model || "").trim();
    const pathName = String(j.connect?.model_path || "").split(/[/\\]/).pop() || "";
    const named = rawName && !/^none\b/i.test(rawName) && !/^loading/i.test(rawName) ? rawName : pathName;
    const backend = String(j.backend || j.connect?.backend || "").toUpperCase() || "—";
    const loading = !j.llama_ok && !!(named || rawName && !/^none\b/i.test(rawName));
    if (j.llama_ok) {
      stopLoadPoll();
      const readyName = named || "ready";
      $("#chipModel").textContent = readyName;
      setChipLoad(false, 100, readyName);
    } else if (loading) {
      // Keep soft % if poll already owns the bar; otherwise show loading label.
      if (!loadPollTimer) setChipLoad(true, 12, named || "model");
      else if ($("#chipModel") && !String($("#chipModel").textContent || "").startsWith("loading"))
        setChipLoad(true, 12, named || "model");
    } else {
      stopLoadPoll();
      $("#chipModel").textContent = "none";
      setChipLoad(false, 0, null);
    }
    $("#chipMeta").textContent = backend;
    $("#statusChip .dot")?.classList.toggle("ok", !!j.llama_ok);
    if ($("#popModel")) {
      $("#popModel").textContent = j.llama_ok
        ? (j.connect?.model_path || named || "ready")
        : (loading ? `loading — ${j.connect?.model_path || named || "…"}` : "none — Activate in Models");
    }
    if ($("#popBackend")) $("#popBackend").textContent = backend;
    if ($("#popUplink")) $("#popUplink").textContent = (j.online || j.web) ? "Online" : "No uplink";
    if ($("#popCtx")) $("#popCtx").textContent = "—";
    const url = j.connect?.url || (j.connect?.ip ? `http://${j.connect.ip}/` : location.origin + "/");
    if ($("#lanUrl2")) $("#lanUrl2").textContent = url;
    announceRemintFromConnect(j.connect);
    const code = j.connect?.pair_code;
    if (code && isLocalMode && $("#pairCodeShow")) {
      const c = String(code);
      // Only overwrite banner with a live numeric code (not the "(paired…)" placeholder).
      if (/^\d{4,8}$/.test(c)) $("#pairCodeShow").textContent = formatPairCode(c);
      else if (!/^\d{4,8}$/.test(String($("#pairCodeShow").textContent || "").replace(/\s/g, "")))
        $("#pairCodeShow").textContent = c;
    } else if (!isLocalMode && $("#pairCodeShow")) {
      $("#pairCodeShow").textContent = "(see stick screen)";
    }
    try {
      const m = await fetch("/stickllm.json", { cache: "no-store" });
      if (m.ok) {
        const meta = await m.json();
        if (meta.version && $("#aboutVer")) $("#aboutVer").textContent = meta.version + " ";
        const boot = String(meta.mode || "").toLowerCase();
        if (boot === "local" || boot === "chat") isLocalMode = true;
      }
    } catch (_) {}
    // vault chrome from health if present
    if (j.vault) {
      const open = String(j.vault.status || "").toLowerCase() === "unlocked" || !!j.vault.mounted;
      setVaultChrome(open);
    }
  } catch (_) {
    $("#chipModel").textContent = "waiting…";
  }
}

window.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea" || e.target?.isContentEditable;
  const k = e.key.toLowerCase();
  // F9 = new PAIR CODE (kiosk, no mouse). Not bare P.
  if (e.key === "F9") {
    e.preventDefault();
    issuePairHotkey();
    return;
  }
  // F10 = show SSH password on stick on stick
  if (e.key === "F10") {
    e.preventDefault();
    issueSshHotkey();
    return;
  }
  if (e.ctrlKey && e.shiftKey && k === "l") { e.preventDefault(); lockVault(); }
  else if (e.ctrlKey && e.shiftKey && k === "o") { e.preventDefault(); newChat(); }
  else if (e.ctrlKey && k === "b") { e.preventDefault(); toggleNav(); }
  else if (e.ctrlKey && k === ",") { e.preventDefault(); openSettings(); }
  else if (e.key === "Escape") {
    if (!$("#confirm").hidden) $("#confirm").hidden = true;
    else if (!$("#picker").hidden) $("#picker").hidden = true;
    else if (!$("#settings").hidden) closeSettings();
    else if (!$("#statusPop").hidden) $("#statusPop").hidden = true;
    else if (app.classList.contains("navOpen")) toggleNav(false);
  }
});

// Disable greyed / coming-soon controls that still have handlers in markup
["#offline", "#exportAll", "#deleteAll", "#revokeAll", "#checkUpd", "#pickModelDir"].forEach((sel) => {
  const el = $(sel); if (!el) return;
  el.onclick = (e) => { e.preventDefault(); toast("Coming soon"); };
  if ("onchange" in el) el.onchange = (e) => { e.preventDefault(); el.checked = false; toast("Coming soon"); };
});
$$("#backendSeg button").forEach((b) => {
  b.disabled = true;
  b.onclick = (e) => { e.preventDefault(); toast("Coming soon — backend is auto-selected"); };
});
$$("#kvSeg button, #temp, #topp, #topk, #rep, #maxtok, #resetPreset").forEach((el) => {
  if (!el) return;
  el.disabled = true;
  el.title = "Coming soon — visual only on stick";
});
$("#attachBtn").disabled = true; $("#micBtn").disabled = true;

applyModeUi("ephemeral");
newChat();
if (detectLocalHost()) isLocalMode = true;
refreshStatus();
// Stick kiosk polls faster so LAN Pair remints show in chat promptly.
setInterval(() => { refreshStatus(); }, isLocalMode || detectLocalHost() ? 2000 : 3000);
ensurePaired(false).then(async () => {
  try {
    const st = await pairStatus();
    if (st.local || detectLocalHost()) isLocalMode = true;
  } catch (_) {}
});

})();
