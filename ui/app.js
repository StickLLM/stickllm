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
let pickerPurpose = "vault"; // vault | models_dir | folder
let hwInfo = { vram: 24, ram: 64, gpu: "", name: "This machine" };
const messages = [{
  role: "system",
  content: "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful.",
}];
const TRUST = {
  verified: { l: "Verified", c: "t-ok", d: "StickLLM hash + tested" },
  community: { l: "Community verified", c: "t-acc", d: "Official publisher, hash matches" },
  unverified: { l: "Unverified", c: "t-warn", d: "Known source, not hash-checked" },
  untrusted: { l: "Untrusted", c: "t-bad", d: "Unknown source" },
  blocked: { l: "Blocked", c: "t-blk", d: "Hash mismatch" },
};
const ALL_TRUST = () => new Set(Object.keys(TRUST));
const state = {
  mode: "ephemeral", vaultOpen: false, web: true, theme: "dark",
  chats: [], ephemeral: [], current: null, attach: [],
  mtab: "browse", ablAck: false, kv: "f16",
  mf: { target: "this", fits: false, ctx: 8192, trust: ALL_TRUST(), abl: "include", quant: "any", lic: "any", q: "", sort: "fit" },
  policy: { verifiedOnly: false, hideUnc: false },
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
$$(".setNav [data-sec]").forEach((b) => (b.onclick = () => {
  showSec(b.dataset.sec);
  if (b.dataset.sec === "models") refreshModels().catch((e) => toast(e.message));
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

function modelTrust(m) {
  const t = String(m.trust || m.trust_level || "").toLowerCase();
  if (TRUST[t]) return t;
  if (m.hash_ok === false || m.blocked) return "blocked";
  if (m.source === "host_ssd" || m.source === "local") return "unverified";
  if (m.sha256 || m.pinned) return "verified";
  return "community";
}
function modelGb(m) {
  const gbRaw = m.approx_size_gb ?? m.size_gb ?? (m.bytes != null ? m.bytes / 1e9 : null);
  return gbRaw != null && gbRaw !== "" ? Number(gbRaw) : 0;
}
function modelQuant(m) {
  return String(m.quant || m.q || "Q4_K_M");
}
function fitOf(m) {
  const hw = state.mf.target === "custom"
    ? { vram: +$("#cVram")?.value || 0, ram: +$("#cRam")?.value || 0 }
    : hwInfo;
  const gb = modelGb(m) || Number(m.min_vram_gb || 0) || 4;
  const kvMul = { f16: 1, q8: 0.53, q4: 0.28 }[state.kv] || 1;
  const kv = Math.max(0.5, (gb / 8) * (state.mf.ctx / 8192) * kvMul);
  const need = gb + kv + 1;
  if (need <= hw.vram) return { k: "gpu", need, kv, label: "Fits on GPU", cls: "fit-ok" };
  if (need <= hw.vram + hw.ram - 8) return { k: "offload", need, kv, label: "Fits with CPU offload", cls: "fit-warn" };
  return { k: "no", need, kv, label: "Won't fit", cls: "fit-no" };
}
function modelVisible(m) {
  const f = state.mf;
  const trust = modelTrust(m);
  if (state.mtab === "local" ? !m.installed : false) return false;
  if (state.policy.verifiedOnly && trust !== "verified") return false;
  if (state.policy.hideUnc && m.abliterated) return false;
  if (!f.trust.has(trust)) return false;
  if (f.abl === "only" && !m.abliterated) return false;
  if (f.abl === "exclude" && m.abliterated) return false;
  if (f.quant !== "any" && modelQuant(m).toUpperCase() !== f.quant.toUpperCase()) return false;
  // GGUF only — llama.cpp does not run safetensors
  if (String(m.format || "GGUF").toLowerCase() === "safetensors") return false;
  if (f.lic === "commercial" && m.license_noncommercial) return false;
  if (f.lic === "noncommercial" && !m.license_noncommercial) return false;
  if (f.q && !(String(m.name || "") + " " + String(m.id || "")).toLowerCase().includes(f.q.toLowerCase())) return false;
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
  if ($("#localTune")) $("#localTune").hidden = state.mtab !== "local";
  if ($("#hfTokenBox")) $("#hfTokenBox").hidden = state.mtab !== "browse";
  if ($("#mfTarget")) $("#mfTarget").value = state.mf.target;
  if ($("#customHw")) $("#customHw").hidden = state.mf.target !== "custom";
  if ($("#hwLine")) {
    $("#hwLine").textContent = state.mf.target === "custom"
      ? "Enter VRAM and RAM"
      : `Detected: ${hwInfo.gpu ? hwInfo.gpu + " " : ""}${hwInfo.vram} GB VRAM · RAM ${hwInfo.ram} GB`;
  }
  if ($("#mfFits")) $("#mfFits").checked = state.mf.fits;
  if ($("#mfCtx")) $("#mfCtx").value = String(state.mf.ctx);
  if ($("#mfQuant")) $("#mfQuant").value = state.mf.quant;
  if ($("#mfSort")) $("#mfSort").value = state.mf.sort;
  $$("#mfTrust input").forEach((i) => { i.checked = state.mf.trust.has(i.dataset.t); });
  $$("#mfAbl button").forEach((b) => b.classList.toggle("on", b.dataset.v === state.mf.abl));
  $$("#mfLic button").forEach((b) => b.classList.toggle("on", b.dataset.v === state.mf.lic));
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
  if (!lastCatalog.length) {
    list.innerHTML = '<div class="emptyCards">No catalog entries. Pair this browser, then Refresh.</div>';
    syncModelActions();
    return;
  }
  let rows = lastCatalog.filter(modelVisible);
  const order = { gpu: 0, offload: 1, no: 2 };
  rows.sort((a, b) => {
    if (state.mf.sort === "size") return modelGb(b) - modelGb(a);
    if (state.mf.sort === "name") return String(a.name || a.id).localeCompare(String(b.name || b.id));
    return (order[fitOf(a).k] - order[fitOf(b).k]) || (Number(!!b.recommended) - Number(!!a.recommended));
  });
  if ($("#modelCount")) {
    $("#modelCount").textContent = `${rows.length} model${rows.length === 1 ? "" : "s"}${state.mtab === "browse" ? " in catalog" : " on this stick"} · fit at ${state.mf.ctx / 1024}k context`;
  }
  list.innerHTML = rows.map((m) => {
    const id = m.id;
    const name = m.name || id;
    const q = modelQuant(m);
    const gb = modelGb(m);
    const gbTxt = gb ? (gb >= 10 ? gb.toFixed(1) : gb.toFixed(2)) + " GB" : "?";
    const have = !!m.installed;
    const run = !!m.running;
    const loading = !!m.active && !run;
    const rec = !!m.recommended;
    const sel = id === selectedModelId;
    const trust = modelTrust(m);
    const t = TRUST[trust];
    const fit = fitOf(m);
    const where = String(m.path || m.location || "").includes("vault") || sessionMode === "vault" ? "vault/SSD" : "stick";
    let actions = "";
    if (trust === "blocked") {
      actions = m.deletable ? `<button class="btn sm danger ghost" data-delf="${esc(id)}" type="button">Delete file</button>` : "";
    } else if (have) {
      actions = `<span class="pill ok">installed</span><button class="btn sm primary" data-load="${esc(id)}" type="button" ${fit.k === "no" && m.runnable === false ? "disabled" : ""}>${run ? "Running" : loading ? "Loading…" : "Load"}</button>`;
    } else {
      actions = `<button class="btn sm ${fit.k === "no" ? "" : "primary"}" data-dl="${esc(id)}" type="button">Download</button>`;
    }
    return `<article class="mcard ${trust === "blocked" ? "blocked" : ""} ${sel ? "sel" : ""}" data-id="${esc(id)}" tabindex="0">
      <div class="mcTop">
        <div class="mcName"><b>${esc(name)}</b><small>${esc(q)} · ${have ? gbTxt + " on disk" : "~" + gbTxt}${have ? " · on " + where : ""}${rec ? " · recommended" : ""}</small></div>
        ${run ? '<span class="pill ok">running</span>' : ""}${loading ? '<span class="pill warn">loading</span>' : ""}${rec ? '<span class="pill acc">recommended</span>' : ""}
      </div>
      <div class="tags"><span class="trust ${t.c}" title="${t.d}">${t.l}</span>${m.abliterated ? '<span class="pill abl">⚠ uncensored</span>' : ""}<span class="pill cap">GGUF</span></div>
      <div class="mcFoot">
        <span class="fit ${fit.cls}" title="Needs ~${fit.need.toFixed(1)} GB">${fit.label}</span>
        <span class="grow"></span>${actions}
      </div>
    </article>`;
  }).join("") || '<div class="emptyCards">No models match these filters. <button class="link" id="mfReset2" type="button">Reset filters</button></div>';
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
  $$("#modelList [data-load]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); selectedModelId = b.dataset.load; $("#activate").click(); }));
  $$("#modelList [data-delf]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); selectedModelId = b.dataset.delf; $("#delModel").click(); }));
  syncModelActions();
}
function syncModelActions() {
  const m = lastCatalog.find((x) => x.id === selectedModelId);
  if (!m) {
    if ($("#selHint")) $("#selHint").textContent = "Select a model";
    updateVramBar({});
    return;
  }
  if ($("#selHint")) $("#selHint").textContent = `Selected: ${m.name || m.id}`;
  if ($("#dlModel")) $("#dlModel").hidden = !!m.installed;
  if ($("#activate")) {
    $("#activate").hidden = !m.installed || (m.runnable === false && !m.running && !m.active);
    $("#activate").textContent = m.running ? "Reload with these settings" : (m.active ? "Still loading… (tap to retry)" : "Load model");
  }
  if ($("#delModel")) $("#delModel").hidden = !m.deletable;
  const max = Number(m.ctx_max || m.ctxMax || 32768);
  if ($("#ctx")) {
    $("#ctx").max = max;
    if (+$("#ctx").value > max) $("#ctx").value = max;
    if ($("#ctxVal")) $("#ctxVal").textContent = (+$("#ctx").value).toLocaleString();
  }
  updateVramBar(m);
}
function resetModelFilters() {
  state.mf = { ...state.mf, fits: false, trust: ALL_TRUST(), abl: "include", quant: "any", lic: "any", q: "", sort: "fit" };
  if ($("#mfSearch")) $("#mfSearch").value = "";
  renderModelsList();
}
async function refreshModels() {
  if (!(await ensurePaired())) return;
  const st = await control("status");
  lastCatalog = st.catalog || [];
  const probe = st.probe || {};
  hwInfo = {
    vram: Number(st.vram_gb || probe.vram_gb || hwInfo.vram) || 24,
    ram: Number(st.ram_gb || hwInfo.ram) || 64,
    gpu: String(probe.gpu || st.gpu || hwInfo.gpu || ""),
    name: "This machine",
  };
  const run = lastCatalog.find((m) => m.running || m.active) || lastCatalog.find((m) => m.installed);
  if (!selectedModelId && run) selectedModelId = run.id;
  if (!selectedModelId && lastCatalog[0]) selectedModelId = lastCatalog[0].id;
  const name = st.loaded?.name || run?.name || "none";
  if ($("#runName")) $("#runName").textContent = name;
  if ($("#recName")) $("#recName").textContent = String(probe.recommend_id || probe.recommend || "—");
  const pill = $("#runPill");
  if (pill) {
    const activeLoading = lastCatalog.some((m) => m.active && !m.running);
    if (st.llama_ok || st.llama?.status === "ok" || run?.running) {
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
  if (m.abliterated && !state.ablAck) {
    askAblAck(() => $("#dlModel").click());
    return;
  }
  if (modelTrust(m) === "untrusted") {
    confirmBox({
      title: "Download an untrusted model?",
      text: "This model comes from an unknown source and its hash may not be checkable.",
      word: "DOWNLOAD", ok: "Download",
      cb: () => doModelDownload(m),
    });
    return;
  }
  await doModelDownload(m);
};
async function doModelDownload(m) {
  try {
    const dest = ($("#modelDir")?.textContent || "").trim();
    const params = { id: m.id };
    if (dest && dest !== "…" && dest.startsWith("/")) params.dest = dest;
    const res = await control("model_download", params);
    if (res.download_dir && $("#modelDir")) $("#modelDir").textContent = res.download_dir;
    renderDownload(res.download || { state: "starting", id: m.id, name: m.name });
    startDlPoll();
    toast(res.download_dir ? `Downloading to ${res.download_dir}` : "Download started");
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
async function searchForVault({ inPicker = false } = {}) {
  try {
    toast("Searching…");
    const res = await control("vault_find");
    const hits = res.hits || res.found || (res.best ? [res.best] : []);
    if (!hits.length && !res.blob && !res.path) {
      const note = res.note || "No stickllm-vault.img found";
      if (inPicker) {
        $("#fpList").innerHTML = `<div class="fpEmpty">${esc(note)}</div>`;
      } else {
        const box = $("#findHits");
        if (box) { box.hidden = false; box.innerHTML = `<div class="row"><small>${esc(note)}</small></div>`; }
      }
      toast(note);
      return;
    }
    const list = hits.length ? hits : [{ blob: res.blob || res.path, path: res.blob || res.path }];
    if (inPicker) {
      let rows = "";
      for (const h of list.slice(0, 20)) {
        const blob = h.blob || h.path || "";
        const folder = String(blob).replace(/\/stickllm-vault\.img$/i, "");
        rows += `<div class="fpRow" data-file="${esc(blob)}" data-kind="vault" data-folder="${esc(folder)}" role="option"><span class="fpName vault"><span class="nm">${esc(blob.split("/").pop() || blob)}</span><span class="pill acc">vault</span></span><span class="muted">${esc(folder)}</span><span class="muted">—</span></div>`;
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
    const hits = res.models || res.hits || [];
    const jump = res.best?.path || res.jump_dir || res.start_dir || "";
    if (inPicker) {
      if (jump && (!hits.length || res.best)) {
        // Prefer jumping into the best model folder, then show remaining hits as rows.
        try { await browseLive(jump); } catch (_) {}
      }
      if (!hits.length) {
        if (!jump) $("#fpList").innerHTML = '<div class="fpEmpty">No .gguf models found on this volume</div>';
        toast(res.note || "No .gguf models found");
        return;
      }
      let rows = "";
      for (const m of hits.slice(0, 40)) {
        const p = m.path || m.dir || "";
        const name = m.name || m.relative || (p.split("/").pop() || p);
        const folder = m.dir || (/\.gguf$/i.test(p) ? p.replace(/\/[^/]+$/, "") : p);
        rows += `<div class="fpRow" data-dir="${esc(folder || p)}" role="option"><span class="fpName model"><span class="nm">${esc(name)}</span><span class="pill">model</span></span><span class="muted">${esc(folder || p)}</span><span class="muted">—</span></div>`;
      }
      $("#fpList").innerHTML = rows;
      $("#fpCrumbs").innerHTML = '<button class="crumbBtn" type="button">Search results — models</button>';
      $$("#fpList [data-dir]").forEach((r) => {
        r.ondblclick = () => browseLive(r.dataset.dir);
        r.onclick = () => {
          $$("#fpList .fpRow").forEach((x) => x.classList.remove("sel"));
          r.classList.add("sel");
          $("#fpSel").textContent = r.dataset.dir;
          $("#fpOk").dataset.path = r.dataset.dir;
          $("#fpOk").dataset.kind = "folder";
          $("#fpOk").textContent = "Use this folder";
          $("#fpOk").disabled = false;
        };
      });
      toast(`Found ${hits.length} model location(s)`);
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
        ).join("");
      }
    }
    if (jump && $("#picker") && !$("#picker").hidden) await browseLive(jump).catch(() => {});
    toast(hits.length ? `Found ${hits.length} model(s)` : (res.note || "No models found"));
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
    if ($("#ablAck") && !$("#ablAck").hidden) $("#ablAck").hidden = true;
    else if (!$("#confirm").hidden) $("#confirm").hidden = true;
    else if (!$("#picker").hidden) $("#picker").hidden = true;
    else if (!$("#settings").hidden) closeSettings();
    else if (!$("#statusPop").hidden) $("#statusPop").hidden = true;
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
// Advanced sampling: UI active for presets/context; KV/sampling stored locally until llama wire-up
$$("#kvSeg button").forEach((b) => (b.onclick = () => {
  state.kv = b.dataset.kv || "f16";
  $$("#kvSeg button").forEach((x) => x.classList.toggle("on", x === b));
  renderModelsList();
}));
["#temp", "#topp"].forEach((sel) => {
  const el = $(sel); if (!el) return;
  el.addEventListener("input", () => {
    const lab = sel === "#temp" ? $("#tempVal") : $("#toppVal");
    if (lab) lab.textContent = el.value;
  });
});
if ($("#resetPreset")) {
  $("#resetPreset").onclick = () => {
    const on = $("#presets button.on");
    if (on) on.click();
    toast("Reset to preset");
  };
}
if ($("#attachBtn")) { $("#attachBtn").disabled = true; $("#attachBtn").title = "Attach files — coming later"; }
if ($("#micBtn")) { $("#micBtn").disabled = true; $("#micBtn").title = "Voice input — coming later"; }

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
$$("#mfAbl button").forEach((b) => (b.onclick = () => { state.mf.abl = b.dataset.v; renderModelsList(); }));
$$("#mfLic button").forEach((b) => (b.onclick = () => { state.mf.lic = b.dataset.v; renderModelsList(); }));
if ($("#mfQuant")) $("#mfQuant").onchange = (e) => { state.mf.quant = e.target.value; renderModelsList(); };
if ($("#mfSort")) $("#mfSort").onchange = (e) => { state.mf.sort = e.target.value; renderModelsList(); };
if ($("#mfSearch")) $("#mfSearch").addEventListener("input", (e) => { state.mf.q = e.target.value; renderModelsList(); });
if ($("#mfReset")) $("#mfReset").onclick = resetModelFilters;
if ($("#hfShow")) $("#hfShow").onclick = () => { const i = $("#hfToken"); if (i) i.type = i.type === "password" ? "text" : "password"; };
if ($("#hfTest")) $("#hfTest").onclick = () => toast("HF token test — live gated downloads come later; catalog downloads need no token");

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
