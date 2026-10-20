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
let loadedCtx = 0;
let lastPerf = null;
let sessionModeBusy = false;
let activeChatId = null;
let lastRemintId = null;
let lastCatalog = [];
let hfHits = [];
let hfBusy = false;
let hfErr = "";
let hfTimer = null;
let selectedModelId = null;
/** Optimistic card badge while llama loads (cleared on running / failure). */
let loadingModelId = null;
let dlPollTimer = null;
let vaultBrowsePath = "";
let vaultPickerMount = "";
let vaultBrowseBlobPath = "";
let pickerPurpose = "vault"; // vault | models_dir | folder
let hwInfo = { vram: 24, vramEach: 24, gpuCount: 1, ram: 64, gpu: "", name: "This machine" };
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
  mf: { target: "this", fits: false, ctx: 8192, trust: ALL_TRUST(), abl: "include", quant: "any", lic: "any", vis: "any", q: "", sort: "fit" },
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
  $("#composerNote").textContent = "";
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
  const pics = (m.imgs || []).map((u) => `<img class="msgImg" alt="" src="${esc(u)}">`).join("");
  const warn = m.warn ? `<div class="attWarn">${esc(m.warn)}</div>` : "";
  return `<div class="msg ${cls}"><div class="av">${av}</div><div class="body">${pics}${m.pending ? '<span class="typing"><i></i><i></i><i></i></span>' : md(m.t || "")}${warn}${src}</div></div>`;
}
function renderThread() {
  const th = $("#thread"), c = state.current;
  $("#chatTitle").textContent = c ? c.title : "New chat";
  if (!c || !c.msgs.length) {
    th.innerHTML = `<div class="empty"><span class="logo lg"></span><h2>What can I help with?</h2>
      <p>${esc(heroModeLine(state.mode))}</p>
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
let sendStop = false;
function setSending(on) {
  sendBusy = on;
  const sendBtn = $("#sendBtn");
  const stopBtn = $("#stopBtn");
  if (sendBtn) sendBtn.hidden = !!on;
  if (stopBtn) stopBtn.hidden = !on;
}
function stopReply() {
  if (!sendBusy) return;
  sendStop = true;
  fetch("/api/chat/stop", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: "{}",
  }).catch(() => {});
  if (sendAbort) sendAbort.abort();
}
async function send() {
  if (sendBusy) return;
  const inp = $("#input");
  const text = inp.value.trim();
  const imgs = state.attach.filter((a) => a.kind !== "file").slice(0, PHOTO_MAX);
  const docs = state.attach.filter((a) => a.kind === "file");
  if (docs.some((a) => a.status === "converting")) return toast("Still converting a file");
  const readyDocs = docs.filter((a) => a.status === "ready" || a.status === "truncated");
  if (!text && !imgs.length && !readyDocs.length) return;
  sendStop = false;
  setSending(true);
  inp.value = "";
  autosize();
  let pend = null;
  try {
    if (!(await ensurePaired()) || sendStop) {
      inp.value = text;
      autosize();
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
    state.attach = [];
    renderAttach();
    renderThread(); renderConvs();
    const t0 = performance.now();
    sendAbort = new AbortController();
    const r = await fetch("/api/chat", {
      method: "POST",
      signal: sendAbort.signal,
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
    if (data?.stopped || sendStop) {
      pend.pending = false; pend.r = "system"; pend.t = "Stopped.";
      return;
    }
    if (data?.stickllm_attachments?.truncated && data.stickllm_attachments.note) {
      const userMsg = c.msgs[c.msgs.length - 2];
      if (userMsg) userMsg.warn = data.stickllm_attachments.note;
    }
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
    const stopped = sendStop || e.name === "AbortError";
    if (pend) {
      pend.pending = false; pend.r = "system"; pend.t = stopped ? "Stopped." : ("Error: " + e.message);
    } else if (!stopped) {
      inp.value = text;
      autosize();
    }
  } finally {
    sendAbort = null;
    setSending(false);
    renderThread(); renderConvs(); $("#input").focus();
  }
}
$("#composer").onsubmit = (e) => { e.preventDefault(); send(); };
const autosize = () => { const i = $("#input"); i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 200) + "px"; };
$("#input").addEventListener("input", autosize);
$("#input").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.repeat) return;
  e.preventDefault();
  if (sendBusy) return;
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
    if ($("#ctxVal")) $("#ctxVal").textContent = (+$("#ctx").value).toLocaleString();
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
async function refreshModels() {
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
  if ($("#recGpuLabel")) {
    $("#recGpuLabel").textContent = gpuCount > 1 ? `Recommended for these ${gpuCount} GPUs` : "Recommended for this GPU";
  }
  const run = lastCatalog.find((m) => m.running || m.active) || lastCatalog.find((m) => m.installed);
  if (loadingModelId) {
    const lm = lastCatalog.find((m) => m.id === loadingModelId);
    if (lm?.running || st.llama_ok) loadingModelId = null;
  }
  if (!selectedModelId && run) selectedModelId = run.id;
  if (!selectedModelId && lastCatalog[0]) selectedModelId = lastCatalog[0].id;
  const name = st.loaded?.name || run?.name || "none";
  if ($("#runName")) $("#runName").textContent = name;
  if ($("#recName")) $("#recName").textContent = String(probe.recommend_id || probe.recommend || "—");
  const pill = $("#runPill");
  if (pill) {
    const activeLoading = !!loadingModelId || lastCatalog.some((m) => m.active && !m.running);
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
function startLoadPoll(expectName) {
  stopLoadPoll();
  let ticks = 0;
  loadPollTimer = setInterval(async () => {
    ticks += 1;
    try {
      await refreshStatus();
      await refreshModels().catch(() => {});
      const running = lastCatalog.find((x) => x.running);
      if (running && (!loadingModelId || running.id === loadingModelId)) {
        loadingModelId = null;
        stopLoadPoll();
        setChipLoad(false, 100, expectName || running.name);
        renderModelsList();
        toast("Model ready" + (expectName ? `: ${expectName}` : ""));
        await refreshStatus();
        return;
      }
      const r = await fetch("/api/health", { cache: "no-store" });
      const j = await r.json().catch(() => ({}));
      if (j.llama_ok) {
        loadingModelId = null;
        stopLoadPoll();
        setChipLoad(false, 100, expectName);
        renderModelsList();
        toast("Model ready" + (expectName ? `: ${expectName}` : ""));
        await refreshStatus();
        return;
      }
      const view = llamaView(j);
      if (view.crashed || view.giveUp) {
        setChipLoad(true, 0, expectName, loadPhaseText(view), true);
        showFewerLayers(view.giveUp);
        if (view.giveUp && ticks > 2) {
          // Stay on the error. Do not keep a percent climbing while llama is stopped.
        }
      } else {
        showFewerLayers(false);
        const pct = view.alive ? view.pct : 1;
        setChipLoad(true, pct, expectName, loadPhaseText(view), false);
      }
      // Large RAM mmap loads can take many minutes — keep polling, but not a fake 95%.
      if (!view.crashed && ticks > 450) {
        stopLoadPoll();
        loadingModelId = null;
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
  const label = name && name !== "none" ? name : "model";
  const phaseText = phase || "Loading weights…";
  if ($("#loadStatusText")) $("#loadStatusText").textContent = `${phaseText} — ${label}`;
  const n = failed ? 0 : Math.max(1, Math.min(92, Number(pct) || 1));
  if ($("#loadStatusFill")) $("#loadStatusFill").style.width = n + "%";
  if ($("#loadStatusPct")) $("#loadStatusPct").textContent = failed ? "" : (Math.round(n) + "%");
}
function setChipLoad(loading, pct, name, phase, failed) {
  const chip = $("#statusChip");
  const bar = $("#chipLoad");
  const fill = $("#chipLoadFill");
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
      $("#chipModel").textContent = "GPU load failed";
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
  loadingModelId = id;
  selectedModelId = id;
  const m = lastCatalog.find((x) => x.id === id);
  loadSizeGb = modelSizeGb(m);
  loadShownPct = 1;
  loadFailed = false;
  loadTickLabel = name || "";
  loadTickPhase = "Starting llama…";
  loadStartedAt = Date.now();
  renderModelsList();
  setChipLoad(true, 1, name, "Starting llama…");
  toast("Loading " + name + "…");
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
    startLoadPoll(name);
    await paintSoon();
    const res = await control("model_activate", { id: m.id, ctx_size: +$("#ctx").value });
    if (!res.ok && res.error) throw new Error(res.error);
    if (res.running || res.load_state === "running") {
      stopLoadPoll();
      loadingModelId = null;
      setChipLoad(false, 100, name);
      toast("Model running: " + name);
    } else {
      const view = llamaView(null);
      setChipLoad(true, view.pct || 1, name, loadPhaseText(view), view.crashed);
      showFewerLayers(view.giveUp);
    }
    await refreshModels(); await refreshStatus();
  } catch (e) {
    stopLoadPoll();
    loadingModelId = null;
    setChipLoad(false, 0, null);
    renderModelsList();
    toast(e.message);
  }
};

async function retryFewerLayers() {
  try {
    const res = await control("llama_fewer_layers", {});
    const n = res.n_gpu_layers || "?";
    toast("Retrying with " + n + " GPU layers");
    const m = lastCatalog.find((x) => x.id === selectedModelId) || lastCatalog.find((x) => x.active);
    beginModelLoadUi(m?.id || selectedModelId || "", m?.name || "model");
    startLoadPoll(m?.name || "model");
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
async function doModelDownload(m) {
  try {
    const dest = ($("#modelDir")?.textContent || "").trim();
    const params = { id: m.id };
    if (m.repo && m.file) {
      params.repo = m.repo;
      params.file = m.file;
      if (m.sha256) params.sha256 = m.sha256;
      if (m.bytes) params.bytes = m.bytes;
      if (m.name) params.name = m.name;
    }
    if (dest && dest !== "…" && dest.startsWith("/")) params.dest = dest;
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
function pairDigits(raw) {
  const c = String(raw || "").trim().replace(/\s/g, "");
  return /^\d{4,8}$/.test(c) ? c : "";
}
/** Paint the F9 banner from the latest code. Does not consume remint id. */
function paintF9PairCode(connect) {
  if (!(isLocalMode || detectLocalHost()) || !$("#pairCodeShow")) return "";
  const c = connect || {};
  const digits = pairDigits(c.remint_code) || pairDigits(c.pair_code);
  if (!digits) return "";
  const shown = String($("#pairCodeShow").textContent || "").replace(/\s/g, "");
  if (shown !== digits) $("#pairCodeShow").textContent = formatPairCode(digits);
  return digits;
}
/** Stick kiosk: chat line when a LAN browser mints a new code. */
function announceRemintFromConnect(connect) {
  if (!(isLocalMode || detectLocalHost())) return;
  const c = connect || {};
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
if ($("#showSsh")) $("#showSsh").onclick = () => { issueSshHotkey(); };
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
    // Before anything else that can throw — F9 must follow a browser New code.
    announceRemintFromConnect(j.connect);
    if (j.session_mode) applyModeUi(j.session_mode === "vault" ? "vault" : "ephemeral");
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
    const loading = !j.llama_ok && !!(named || loadingModelId);
    if (j.llama_ok) {
      stopLoadPoll();
      loadingModelId = null;
      const readyName = named || "ready";
      $("#chipModel").textContent = readyName;
      setChipLoad(false, 100, readyName);
    } else if (loading) {
      if (!loadStartedAt) {
        loadStartedAt = Date.now();
        const m = lastCatalog.find((x) => x.id === loadingModelId) || lastCatalog.find((x) => x.name === named);
        loadSizeGb = m ? modelSizeGb(m) : guessSizeGb(named);
      }
      if (!loadPollTimer) {
        const view = llamaView(j);
        setChipLoad(true, view.crashed ? 0 : (view.pct || 1), named || "model", loadPhaseText(view), view.crashed || view.giveUp);
        showFewerLayers(view.giveUp);
        startLoadPoll(named || "model");
      }
    } else {
      stopLoadPoll();
      loadingModelId = null;
      $("#chipModel").textContent = "none";
      setChipLoad(false, 0, null);
    }
    $("#chipMeta").textContent = modelVision && j.llama_ok ? backend + " · vision" : backend;
    $("#statusChip .dot")?.classList.toggle("ok", !!j.llama_ok);
    if ($("#popModel")) {
      const pop = $("#popModel");
      if (j.llama_ok) {
        pop.textContent = named || "ready";
        pop.title = modelPath || named || "";
      } else if (loading) {
        pop.textContent = named ? `loading — ${named}` : "loading…";
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
    if (isLocalMode && $("#pairCodeShow")) {
      const digits = paintF9PairCode(j.connect);
      if (!digits) {
        const c = String(code || "");
        const shown = String($("#pairCodeShow").textContent || "").replace(/\s/g, "");
        if (c && !/^\d{4,8}$/.test(shown)) $("#pairCodeShow").textContent = c;
      }
    } else if (!isLocalMode && $("#pairCodeShow")) {
      const shown = String($("#pairCodeShow").textContent || "").replace(/\s/g, "");
      if (!/^\d{4,8}$/.test(shown)) $("#pairCodeShow").textContent = "(see stick screen)";
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

// Capture phase so F9/F10 still fire from Settings, Models, or the chat box.
window.addEventListener("keydown", (e) => {
  if (e.key !== "F9" && e.key !== "F10") return;
  e.preventDefault();
  e.stopPropagation();
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
  if (st?.saved || st?.hf_token_saved) { el.textContent = "Saved in the vault."; return; }
  if (st?.vault_unlocked) el.textContent = "Saved in the vault when you enter a token. Not kept in the models folder.";
  else el.textContent = "Unlock the vault to keep this token across a reboot.";
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
