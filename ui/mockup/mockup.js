(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const app = $("#app");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ICON_FOLDER = '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>';

const state = {
  mode: "ephemeral", vaultOpen: false, web: true, theme: "dark",
  chats: [
    { id: 1, title: "Explain KV cache quantization", saved: true, day: "Today", msgs: [
      { r: "user", t: "What does a q8 KV cache actually trade off?" },
      { r: "ai", t: "The KV cache stores attention keys and values for every token in the context. Storing them as **q8_0** instead of f16 roughly halves the memory they use, so you can fit about twice the context in the same VRAM.\n\nThe cost is a small loss in precision. On most chat tasks it's barely noticeable. **q4_0** saves even more memory, but quality can drop on long, detail-heavy prompts.", src: ["https://github.com/ggerganov/llama.cpp/discussions"] },
    ]},
    { id: 2, title: "Draft: landlord email", saved: true, day: "Today", msgs: [{ r: "user", t: "Help me write a polite email about the broken heater." }, { r: "ai", t: "Sure. Here's a short, polite draft you can adjust…" }]},
    { id: 3, title: "Bash one-liner for dedupe", saved: true, day: "Yesterday", msgs: [{ r: "user", t: "Dedupe lines but keep the order" }, { r: "ai", t: "Use `awk '!seen[$0]++' file.txt`. It keeps the first time each line appears." }]},
    { id: 4, title: "Trip packing list", saved: true, day: "Previous 7 days", msgs: [{ r: "user", t: "Packing list for 4 days hiking" }, { r: "ai", t: "Here's a compact list…" }]},
  ],
  ephemeral: [],
  current: null,
  models: [
    { id: "q7", name: "Qwen2.5-7B-Instruct", q: "Q5_K_M", gb: 5.2, have: true, run: true, rec: true, ctxMax: 32768 },
    { id: "l8", name: "Llama-3.1-8B-Instruct", q: "Q4_K_M", gb: 4.9, have: true, ctxMax: 32768 },
    { id: "p3", name: "Phi-3.5-mini-instruct", q: "Q6_K", gb: 3.1, have: false, ctxMax: 16384 },
    { id: "q14", name: "Qwen2.5-14B-Instruct", q: "Q4_K_M", gb: 9.0, have: false, ctxMax: 32768 },
    { id: "m24", name: "Mistral-Small-24B-Instruct", q: "Q4_K_M", gb: 14.3, have: false, ctxMax: 32768 },
  ],
  sel: "q7", preset: "balanced", kv: "f16",
  drives: [
    { id: "nv3", name: "Host SSD · nvme0n1p3", fs: "ext4", size: 931, free: 412, path: "/mnt/stickllm-host/nvme0n1p3", state: "mounted" },
    { id: "nv4", name: "Host SSD · nvme0n1p4", fs: "ntfs", size: 500, free: 380, path: "/dev/nvme0n1p4", state: "unmounted" },
    { id: "usb", name: "StickLLM USB · DATA", fs: "exfat", size: 32, free: 28, path: "/mnt/stickllm-data", state: "mounted", usb: true },
    { id: "nv2", name: "Host SSD · nvme0n1p2", fs: "BitLocker", size: 256, free: 0, path: "/dev/nvme0n1p2", state: "blocked" },
  ],
  drive: "nv3", path: ["stickllm"],
  devices: [
    { name: "This browser · Firefox on Linux", seen: "now", ip: "192.168.1.20", me: true },
    { name: "Pixel 8 · Chrome", seen: "12 min ago", ip: "192.168.1.31" },
    { name: "MacBook Air · Safari", seen: "yesterday", ip: "192.168.1.44" },
  ],
};
const PRESETS = {
  fast: { ctx: 4096, kv: "q8", temp: 0.7, topp: 0.9, topk: 40, rep: 1.1, maxtok: 512 },
  balanced: { ctx: 8192, kv: "f16", temp: 0.7, topp: 0.9, topk: 40, rep: 1.1, maxtok: 1024 },
  long: { ctx: 32768, kv: "q4", temp: 0.6, topp: 0.9, topk: 40, rep: 1.1, maxtok: 2048 },
};

/* ---------- toast ---------- */
let tt;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(tt); tt = setTimeout(() => (t.hidden = true), 2600); }

/* ---------- theme ---------- */
function setTheme(t) {
  state.theme = t; document.documentElement.dataset.theme = t;
  $$("#themeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.theme === t));
}
$("#themeBtn").onclick = () => setTheme(state.theme === "dark" ? "light" : "dark");
$$("#themeSeg button").forEach((b) => (b.onclick = () => setTheme(b.dataset.theme)));

/* ---------- mode ---------- */
function setMode(m) {
  if (m === "vault" && !state.vaultOpen) { toast("Unlock the vault first"); openSettings("storage"); setTimeout(() => $("#vaultPass").focus(), 50); return; }
  state.mode = m;
  $$("[data-mode]").forEach((b) => { const on = b.dataset.mode === m; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  $("#modeHint").textContent = m === "vault" ? "Chats are saved in your encrypted vault." : "Nothing is written to disk. Chats are lost at reboot.";
  $("#chatWhere").textContent = m === "vault" ? "Vault: saved encrypted on the host SSD." : "Ephemeral: in memory only, gone at reboot.";
  $("#composerNote").textContent = m === "vault" ? "Vault session · saved encrypted · runs locally" : "Ephemeral session · runs locally on this stick";
  renderConvs();
}
$$("[data-mode]").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

/* ---------- vault lock ---------- */
function setVault(open) {
  state.vaultOpen = open;
  $("#vaultCard").classList.toggle("open", open);
  $("#vcState").textContent = open ? "Vault unlocked" : "Vault locked";
  $("#unlockForm").hidden = open; $("#lockBtn2").hidden = !open; $("#lockBtn").hidden = !open;
  $("#popVault").textContent = open ? "Unlocked" : "Locked";
  if (!open && state.mode === "vault") { state.mode = "x"; setMode("ephemeral"); }
  renderConvs(); renderSaved(); renderMovable();
}
$("#unlockForm").onsubmit = (e) => {
  e.preventDefault();
  if ($("#vaultPass").value.length < 1) return toast("Enter the vault passcode");
  $("#vaultPass").value = ""; setVault(true); toast("Vault unlocked");
};
const lockVault = () => { if (state.vaultOpen) { setVault(false); toast("Vault locked"); } };
$("#lockBtn").onclick = lockVault; $("#lockBtn2").onclick = lockVault;

/* ---------- sidebar ---------- */
const mobile = () => matchMedia("(max-width:820px)").matches;
function toggleNav(force) {
  if (mobile()) {
    const open = force ?? !app.classList.contains("navOpen");
    app.classList.toggle("navOpen", open); $("#scrim").hidden = !open;
    $("#menuBtn").setAttribute("aria-expanded", open);
  } else app.classList.toggle("collapsed", force === undefined ? undefined : !force);
}
$("#menuBtn").onclick = () => toggleNav();
$("#collapseBtn").onclick = () => (mobile() ? toggleNav(false) : app.classList.add("collapsed"));
$("#scrim").onclick = () => toggleNav(false);

function renderConvs() {
  const list = $("#convList"); let html = "";
  if (state.ephemeral.length) {
    html += '<div class="convGroup">This session</div>';
    html += state.ephemeral.map((c) => `<button class="conv ${state.current === c ? "on" : ""}" data-e="${c.id}"><span>${esc(c.title)}</span><span class="tag">temp</span></button>`).join("");
  }
  if (state.vaultOpen) {
    let day = "";
    state.chats.forEach((c) => {
      if (c.day !== day) { day = c.day; html += `<div class="convGroup">${day}</div>`; }
      html += `<button class="conv ${state.current === c ? "on" : ""}" data-v="${c.id}"><span>${esc(c.title)}</span></button>`;
    });
  } else {
    html += '<div class="convGroup">Saved chats</div><div class="convEmpty">Locked in the vault. <button class="link" id="unlockLink">Unlock</button></div>';
  }
  list.innerHTML = html;
  $$(".conv", list).forEach((b) => (b.onclick = () => {
    openChat(b.dataset.v ? state.chats.find((c) => c.id == b.dataset.v) : state.ephemeral.find((c) => c.id == b.dataset.e));
    if (mobile()) toggleNav(false);
  }));
  const ul = $("#unlockLink"); if (ul) ul.onclick = () => { openSettings("storage"); setTimeout(() => $("#vaultPass").focus(), 50); };
}

/* ---------- chat ---------- */
function md(t) {
  return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").split(/\n\n/).map((p) => `<p>${p}</p>`).join("");
}
function msgHtml(m) {
  const src = m.src?.length ? `<details class="sources"><summary>${m.src.length} web source${m.src.length > 1 ? "s" : ""}</summary>${m.src.map((u) => `<a href="#">${esc(u)}</a>`).join("")}</details>` : "";
  return `<div class="msg ${m.r}"><div class="av">${m.r === "ai" ? "S" : ""}</div><div class="body">${m.att?.length ? `<div class="msgAtt">${m.att.map((n) => `<span class="pill">${esc(n)}</span>`).join("")}</div>` : ""}${m.pending ? '<span class="typing"><i></i><i></i><i></i></span>' : md(m.t)}${src}</div></div>`;
}
function renderThread() {
  const th = $("#thread"), c = state.current;
  $("#chatTitle").textContent = c ? c.title : "New chat";
  if (!c || !c.msgs.length) {
    th.innerHTML = `<div class="empty"><span class="logo lg"></span><h2>What can I help with?</h2><p>Everything runs on this stick. ${state.mode === "vault" ? "This chat will be saved to your vault." : "This chat disappears when you reboot."}</p>
      <div class="sugg"><button>Summarize a long article I paste in</button><button>Write a bash script to rename photos by date</button><button>Explain how LUKS encryption works</button><button>Draft a polite follow-up email</button></div></div>`;
    $$(".sugg button", th).forEach((b) => (b.onclick = () => { $("#input").value = b.textContent; send(); }));
    return;
  }
  th.innerHTML = `<div class="msgs">${c.msgs.map(msgHtml).join("")}</div>`;
  th.scrollTop = th.scrollHeight;
}
function openChat(c) { state.current = c; renderThread(); renderConvs(); }
function newChat() { state.current = null; renderThread(); renderConvs(); $("#input").focus(); }
$("#newChatBtn").onclick = () => { newChat(); if (mobile()) toggleNav(false); };

function send() {
  const inp = $("#input"), text = inp.value.trim() || (state.attach.length ? "(attachment)" : ""); if (!text) return;
  if (!state.current) {
    const c = { id: Date.now(), title: text.slice(0, 40), msgs: [], day: "Today", saved: state.mode === "vault" };
    (state.mode === "vault" ? state.chats.unshift(c) : state.ephemeral.unshift(c)); state.current = c;
  }
  const c = state.current; const att = state.attach.map((p) => p.split("/").pop()); c.msgs.push({ r: "user", t: text, att }); state.attach = []; renderAttach();
  const pend = { r: "ai", pending: true }; c.msgs.push(pend);
  inp.value = ""; autosize(); renderThread(); renderConvs(); $("#sendBtn").disabled = true;
  setTimeout(() => {
    pend.pending = false;
    pend.t = "This is a mock reply from the local model. In the real app the answer streams in here.\n\nIf web lookup was actually used, the sources are listed underneath. There's no status label on each reply.";
    if (state.web && /news|today|latest|price/i.test(text)) pend.src = ["https://example.org/article"];
    $("#sendBtn").disabled = false; renderThread(); renderSaved();
  }, 700);
}
$("#composer").onsubmit = (e) => { e.preventDefault(); send(); };
const autosize = () => { const i = $("#input"); i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 200) + "px"; };
$("#input").addEventListener("input", autosize);
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("#webToggle").onclick = () => { state.web = !state.web; $("#webToggle").setAttribute("aria-pressed", state.web); $("#webDefault").checked = state.web; };
$("#webDefault").onchange = (e) => { state.web = e.target.checked; $("#webToggle").setAttribute("aria-pressed", state.web); };

/* status chip */
$("#statusChip").onclick = (e) => { e.stopPropagation(); const p = $("#statusPop"); p.hidden = !p.hidden; $("#statusChip").setAttribute("aria-expanded", !p.hidden); };
document.addEventListener("click", (e) => { if (!$("#statusPop").contains(e.target)) $("#statusPop").hidden = true; });

/* ---------- settings modal ---------- */
let lastFocus;
function openSettings(sec = "general") {
  lastFocus = document.activeElement; $("#settings").hidden = false; $("#statusPop").hidden = true;
  if (mobile()) toggleNav(false);
  showSec(sec, !mobile() || sec !== "__nav");
}
function showSec(sec, open = true) {
  $$(".sec").forEach((s) => (s.hidden = s.id !== "sec-" + sec));
  $$(".setNav [data-sec]").forEach((b) => { b.classList.toggle("on", b.dataset.sec === sec); b.setAttribute("aria-current", b.dataset.sec === sec ? "page" : "false"); });
  $("#secTitle").innerHTML = $("#sec-" + sec).dataset.title;
  $(".modal:not(.small)").classList.toggle("secOpen", open);
  $(".setScroll").scrollTop = 0;
}
function closeSettings() { $("#settings").hidden = true; lastFocus?.focus?.(); }
$$("[data-open]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openSettings(b.dataset.open); }));
$$(".setNav [data-sec]").forEach((b) => (b.onclick = () => showSec(b.dataset.sec)));
$$("[data-sec-go]").forEach((b) => (b.onclick = () => showSec(b.dataset.secGo)));
$("#setClose").onclick = closeSettings;
$("#setBack").onclick = () => $(".modal:not(.small)").classList.remove("secOpen");
$("#settings").onclick = (e) => { if (e.target.id === "settings") closeSettings(); };
// arrow keys in settings nav
$(".setNav").addEventListener("keydown", (e) => {
  if (!["ArrowDown", "ArrowUp"].includes(e.key)) return;
  const bs = $$(".setNav [data-sec]"), i = bs.indexOf(document.activeElement); if (i < 0) return;
  e.preventDefault(); const n = bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length]; n.focus(); n.click();
});

/* ---------- confirm dialog ---------- */
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

/* ---------- models ---------- */
function renderModels() {
  $("#modelList").innerHTML = state.models.map((m) => `
    <label class="model ${m.id === state.sel ? "sel" : ""}">
      <input type="radio" name="model" value="${m.id}" ${m.id === state.sel ? "checked" : ""}>
      <div class="mi"><b>${m.name}</b> <span class="muted small">${m.q}</span><small>${m.gb} GB · up to ${m.ctxMax / 1024}k context${m.have ? "" : " · not downloaded"}</small></div>
      ${m.run ? '<span class="pill ok">running</span>' : ""}${m.rec ? '<span class="pill acc">recommended</span>' : ""}${!m.have ? '<span class="pill">download</span>' : ""}
    </label>`).join("");
  $$("#modelList input").forEach((i) => (i.onchange = () => { state.sel = i.value; renderModels(); }));
  const m = state.models.find((x) => x.id === state.sel);
  $("#selHint").textContent = `Selected: ${m.name} ${m.q}`;
  $("#dlModel").hidden = m.have; $("#activate").hidden = !m.have; $("#delModel").hidden = !m.have;
  $("#activate").textContent = m.run ? "Reload with these settings" : "Load model";
  $("#ctx").max = m.ctxMax; updateVram();
}
function updateVram() {
  const m = state.models.find((x) => x.id === state.sel), ctx = +$("#ctx").value;
  const kvPer = { f16: 0.000128, q8: 0.000068, q4: 0.000036 }[state.kv] * (m.gb / 5.2);
  const total = 24, w = m.gb + 0.6, kv = ctx * kvPer * 1.0; const used = w + kv, free = Math.max(0, total - used);
  $("#ctxVal").textContent = ctx.toLocaleString();
  $("#vW").style.width = Math.min(100, (w / total) * 100) + "%";
  $("#vKV").style.width = Math.min(100 - (w / total) * 100, (kv / total) * 100) + "%";
  $("#vFree").style.width = (free / total) * 100 + "%";
  $("#lW").textContent = w.toFixed(1) + " GB"; $("#lKV").textContent = kv.toFixed(1) + " GB"; $("#lFree").textContent = free.toFixed(1) + " GB";
  const over = used > total; $(".vramBar").classList.toggle("over", over); $("#vramWarn").hidden = !over;
}
function applyPreset(p) {
  state.preset = p; const v = PRESETS[p];
  $("#ctx").value = v.ctx; setKv(v.kv); $("#temp").value = v.temp; $("#topp").value = v.topp; $("#topk").value = v.topk; $("#rep").value = v.rep; $("#maxtok").value = v.maxtok;
  $$("#presets button").forEach((b) => { b.classList.toggle("on", b.dataset.preset === p); b.classList.remove("custom"); });
  syncLabels(); updateVram();
}
function markCustom() { $(`#presets [data-preset=${state.preset}]`).classList.add("custom"); }
function setKv(k) { state.kv = k; $$("#kvSeg button").forEach((b) => b.classList.toggle("on", b.dataset.kv === k)); }
function syncLabels() { $("#tempVal").textContent = (+$("#temp").value).toFixed(2); $("#toppVal").textContent = (+$("#topp").value).toFixed(2); }
$$("#presets button").forEach((b) => (b.onclick = () => applyPreset(b.dataset.preset)));
$$("#kvSeg button").forEach((b) => (b.onclick = () => { setKv(b.dataset.kv); markCustom(); updateVram(); }));
["ctx", "temp", "topp", "topk", "rep", "maxtok"].forEach((id) => $("#" + id).addEventListener("input", () => { markCustom(); syncLabels(); updateVram(); }));
$("#resetPreset").onclick = () => applyPreset(state.preset);
$("#probeBtn").onclick = () => toast("GPU check: RTX 4090, 24 GB. Recommended: Qwen2.5-7B Q5_K_M");
$("#refreshCatalog").onclick = () => toast("Model list refreshed");
$("#activate").onclick = () => {
  state.models.forEach((m) => (m.run = m.id === state.sel)); const m = state.models.find((x) => x.run);
  $("#chipModel").textContent = m.name.replace(/-Instruct.*/, "").replace(/-/g, " "); renderModels();
  toast(`Loading ${m.name} with ${(+$("#ctx").value).toLocaleString()} context…`);
};
$("#dlModel").onclick = () => {
  const m = state.models.find((x) => x.id === state.sel); const box = $("#dlBox"); box.hidden = false; $("#dlName").textContent = "Downloading " + m.name;
  let p = 0; const iv = setInterval(() => {
    p += 7; $("#dlFill").style.width = Math.min(p, 100) + "%"; $("#dlPct").textContent = Math.min(p, 100) + "%";
    $("#dlMeta").textContent = `${((m.gb * Math.min(p, 100)) / 100).toFixed(1)} of ${m.gb} GB · 48 MB/s`;
    if (p >= 100) { clearInterval(iv); m.have = true; renderModels(); setTimeout(() => (box.hidden = true), 1200); toast(m.name + " downloaded"); }
  }, 150);
};
$("#delModel").onclick = () => {
  const m = state.models.find((x) => x.id === state.sel);
  confirmBox({ title: "Delete model files?", text: `This permanently deletes ${m.name} ${m.q} (${m.gb} GB) from disk.`, word: "ARE YOU SURE", ok: "Delete files",
    cb: () => { m.have = false; m.run = false; renderModels(); toast("Model files deleted"); } });
};

/* ---------- storage ---------- */
function renderDrives() {
  $("#drives").innerHTML = state.drives.map((d) => {
    const pct = d.size ? Math.round(((d.size - d.free) / d.size) * 100) : 0;
    const act = d.state === "unmounted" ? '<button class="btn sm" data-mount="' + d.id + '">Mount</button>' : d.state === "blocked" ? '<span class="pill">encrypted · blocked</span>' : d.usb ? '<span class="pill">leaves with stick</span>' : '<span class="pill ok">mounted</span>';
    return `<div class="drive ${d.id === state.drive ? "sel" : ""} ${d.state === "blocked" ? "blocked" : ""}" data-d="${d.id}" tabindex="${d.state === "mounted" ? 0 : -1}" role="button">
      <div class="dh"><b>${d.name}</b></div><small class="mono">${d.path} · ${d.fs}</small>
      ${d.state === "blocked" ? "" : `<div class="bar"><i style="width:${pct}%"></i></div><small>${d.free} GiB free of ${d.size} GiB</small>`}
      <div>${act}</div></div>`;
  }).join("");
  $$(".drive").forEach((el) => {
    const pick = () => { const d = state.drives.find((x) => x.id === el.dataset.d); if (d.state !== "mounted") return; state.drive = d.id; renderDrives(); openPicker({ mode: "vault", drive: d.id, cb: onVaultPick }); if (d.usb) toast("Stick USB picked. Data leaves with the stick, so the host SSD is better."); };
    el.onclick = pick; el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
  });
  $$("[data-mount]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); const d = state.drives.find((x) => x.id === b.dataset.mount); d.state = "mounted"; d.path = "/mnt/stickllm-host/" + d.id.replace("nv", "nvme0n1p"); renderDrives(); toast("Mounted at " + d.path); }));
}
$("#refreshDrives").onclick = () => { renderDrives(); toast("Drives refreshed"); };
$("#actClaim").onclick = () => {
  confirmBox({
    title: "Use free space on the stick?",
    text: "Creates a StickLLM data partition on this StickLLM USB stick only (the flashed stick). Your own drives are never partitioned or formatted.",
    word: "USE-STICK-SPACE",
    ok: "Use free space",
    cb: () => toast("Data partition claimed on StickLLM stick · ~28 GiB free"),
  });
};
$("#actFindVault").onclick = () => {
  const box = $("#findHits");
  box.hidden = false;
  box.innerHTML = `<div class="row"><div><b class="mono">stickllm-vault.img</b><small>/mnt/stickllm-host/nvme0n1p3/stickllm · StickLLM vault</small></div><button class="btn sm" id="hitOpenVault">Open</button></div>`;
  $("#hitOpenVault").onclick = () => { $("#vcSub").textContent = "/mnt/stickllm-host/nvme0n1p3/stickllm/stickllm-vault.img · 32 GiB"; toast("Vault path set. Enter passcode to unlock."); $("#vaultPass").focus(); };
  toast("Found 1 vault file");
};
$("#actFindModels").onclick = () => {
  const box = $("#findHits");
  box.hidden = false;
  box.innerHTML = `<div class="row"><div><b>Qwen2.5-7B Q5_K_M</b><small class="mono">/mnt/stickllm-data/models · 5.2 GB</small></div><span class="pill acc">on stick</span></div>
    <div class="row"><div><b>Qwen2.5-3B Q4_K_M</b><small class="mono">/mnt/stickllm-host/nvme0n1p3/models · 1.9 GB</small></div><span class="pill">host SSD</span></div>`;
  toast("Found 2 model locations");
};
$("#createVault").onclick = () => {
  const p1 = $("#np1").value, p2 = $("#np2").value;
  if (p1.length < 8) return toast("Passcode must be at least 8 characters");
  if (p1 !== p2) return toast("Passcodes don't match");
    confirmBox({ title: "Create vault?", text: `Creates a ${$("#vaultSize").value} GiB encrypted file in ${$("#vaultPath").value}.`,
    word: "CREATE-VAULT", ok: "Create vault",
    cb: () => setTimeout(() => confirmBox({ title: "Save your recovery phrase", text: "This is the only time it's shown. Write it down and keep it somewhere safe.", extra: "amber  river  lantern  quiet  copper  meadow\northo  vessel  plum  harbor  nine  oak", word: "SAVED", ok: "Finish setup",
      cb: () => { setVault(true); $("#np1").value = $("#np2").value = ""; toast("Vault created and unlocked"); } }), 50) });
};
$("#growBtn").onclick = () => toast(`Vault grown by ${$("#growGb").value} GiB`);
$("#wipeBtn").onclick = () => { const n = +$("#wipeN").value; if (!n) return toast("Wipe after wrong passcodes: off");
  confirmBox({ title: "Enable auto-wipe?", text: `After ${n} wrong passcodes the vault's key header is destroyed and the data can't be recovered.`, word: "WIPE-OK", ok: "Enable", cb: () => toast(`Auto-wipe after ${n} tries enabled`) }); };
function renderMovable() {
  const box = $("#movable");
  if (!state.vaultOpen) { box.innerHTML = '<div class="row"><small>Unlock the vault to move models off the stick.</small></div>'; return; }
  box.innerHTML = state.models.filter((m) => m.have).map((m) => `<div class="row"><div><b>${m.name} ${m.q}</b><small>on stick USB · ${m.gb} GB</small></div><button class="btn sm" data-mv="${m.id}">Move to vault</button></div>`).join("");
  $$("[data-mv]").forEach((b) => (b.onclick = () => { b.disabled = true; b.textContent = "In vault ✓"; toast("Model moved to vault"); }));
}
$("#refreshMovable").onclick = () => { renderMovable(); toast("Refreshed"); };

/* ---------- chats ---------- */
function renderSaved() {
  const box = $("#savedChats");
  if (!state.vaultOpen) { box.innerHTML = '<div class="row"><small>Unlock the vault to see saved chats. Ephemeral chats are never written to disk.</small></div>'; return; }
  box.innerHTML = state.chats.map((c) => `<div class="row"><div><b>${esc(c.title)}</b><small>${c.day} · ${c.msgs.length} messages</small></div><div class="inline"><button class="btn sm" data-oc="${c.id}">Open</button><button class="btn sm" data-ex="${c.id}">Export</button><button class="btn sm danger ghost" data-dc="${c.id}">Delete</button></div></div>`).join("") || '<div class="row"><small>No saved chats.</small></div>';
  $$("[data-oc]").forEach((b) => (b.onclick = () => { openChat(state.chats.find((c) => c.id == b.dataset.oc)); closeSettings(); }));
  $$("[data-ex]").forEach((b) => (b.onclick = () => exportChats(state.chats.filter((c) => c.id == b.dataset.ex))));
  $$("[data-dc]").forEach((b) => (b.onclick = () => { state.chats = state.chats.filter((c) => c.id != b.dataset.dc); renderSaved(); renderConvs(); toast("Chat deleted"); }));
}
function exportChats(list) {
  const blob = new Blob([JSON.stringify(list, null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "stickllm-chats.json"; a.click(); toast("Exported " + list.length + " chat(s)");
}
$("#exportAll").onclick = () => exportChats(state.vaultOpen ? state.chats : state.ephemeral);
$("#deleteAll").onclick = () => confirmBox({ title: "Delete all saved chats?", text: "Removes every chat stored in the vault.", word: "ARE YOU SURE", ok: "Delete all", cb: () => { state.chats = []; renderSaved(); renderConvs(); newChat(); } });
$("#saveChat").onclick = () => {
  if (!state.vaultOpen) return toast("Unlock the vault to save chats");
  const c = state.current; if (!c) return toast("Nothing to save yet");
  if (state.ephemeral.includes(c)) { state.ephemeral = state.ephemeral.filter((x) => x !== c); state.chats.unshift(c); }
  renderSaved(); renderConvs(); toast("Saved to vault");
};

/* ---------- devices ---------- */
function renderDevices() {
  $("#devices").innerHTML = state.devices.map((d, i) => `<div class="row"><div><b>${esc(d.name)} ${d.me ? '<span class="pill acc">you</span>' : ""}</b><small>${d.ip} · last seen ${d.seen}</small></div><button class="btn sm danger ghost" data-rv="${i}">${d.me ? "Sign out" : "Revoke"}</button></div>`).join("") || '<div class="row"><small>No paired devices.</small></div>';
  $$("[data-rv]").forEach((b) => (b.onclick = () => { state.devices.splice(+b.dataset.rv, 1); renderDevices(); toast("Access revoked"); }));
}
$("#remint").onclick = () => { const c = String(Math.floor(100000 + Math.random() * 899999)); $("#pairCodeShow").textContent = c.slice(0, 3) + " " + c.slice(3); state.devices = state.devices.filter((d) => d.me); renderDevices(); toast("New pair code. Other browsers were signed out."); };
$("#revokeAll").onclick = () => confirmBox({ title: "Revoke all devices?", text: "Every paired browser, including this one, has to pair again.", word: "REVOKE", ok: "Revoke all", cb: () => { state.devices = []; renderDevices(); } });
$("#pairForm").onsubmit = (e) => { e.preventDefault(); const v = $("#pairIn").value.trim(); const err = $("#pairErr");
  if (!/^\d{6}$/.test(v)) { err.hidden = false; err.textContent = "Enter the 6-digit code from the stick screen"; return; }
  err.hidden = true; $("#pairIn").value = ""; toast("Browser paired"); };

/* ---------- network / system ---------- */
$("#copyUrl").onclick = () => { navigator.clipboard?.writeText("http://192.168.1.42/").catch(() => {}); toast("Address copied"); };
$("#offline").onchange = (e) => { const on = e.target.checked; $("#webToggle").disabled = on; if (on) { state.web = false; $("#webToggle").setAttribute("aria-pressed", false); } toast(on ? "Offline mode on: outbound traffic blocked" : "Offline mode off"); };
$("#wifiBtn").onclick = () => toast($("#ssid").value ? "Connecting to " + $("#ssid").value + "…" : "Enter a network name");
$$("#backendSeg button").forEach((b) => (b.onclick = () => { $$("#backendSeg button").forEach((x) => x.classList.toggle("on", x === b)); toast("Backend: " + b.textContent + " (applies on next model load)"); }));
$("#checkUpd").onclick = () => toast("You're on the latest version (0.9.4)");

/* ---------- Shared picker component (folder mode + file mode) ---------- */
const D = (n, m, kids = []) => ({ n, t: "d", m, kids });
const F = (n, m, sz, hue) => ({ n, t: "f", m, sz, hue });
const FS = {
  nv3: D("", "", [
    D("stickllm", "Oct 12, 2026", [F("stickllm-vault.img", "Oct 15, 2026", 34359738368), D("models", "Oct 12, 2026", [F("Qwen2.5-7B-Instruct-Q5_K_M.gguf", "Oct 10, 2026", 5583457484)]), F("README.txt", "Oct 12, 2026", 1840)]),
    D("home", "Sep 2, 2026", [D("nink", "Oct 14, 2026", [
      D("Documents", "Oct 14, 2026", [F("taxes-2025.pdf", "Apr 20, 2026", 482113), F("lease-agreement.pdf", "Feb 2, 2026", 1203311), F("meeting-notes.md", "Oct 14, 2026", 6120), F("budget.csv", "Sep 30, 2026", 18822), F("resume.docx", "Aug 8, 2026", 88213)]),
      D("Pictures", "Oct 13, 2026", [F("heater-broken.jpg", "Oct 13, 2026", 2411520, 18), F("whiteboard.png", "Oct 9, 2026", 1388544, 190), F("receipt.jpg", "Oct 2, 2026", 942080, 40), F("trail-map.png", "Sep 28, 2026", 3145728, 130), F("screenshot-error.png", "Sep 21, 2026", 512000, 220), F("cat.jpg", "Aug 30, 2026", 2883584, 28), F("diagram.webp", "Aug 1, 2026", 204800, 260)]),
      D("Downloads", "Oct 13, 2026", [F("Llama-3.1-8B-Instruct-Q4_K_M.gguf", "Sep 30, 2026", 4920734106), F("ubuntu-24.04.iso", "Aug 11, 2026", 6114656256), F("invoice-0921.pdf", "Sep 21, 2026", 99120)]),
      D("models", "Oct 1, 2026", [F("mistral-small-24b-q4_k_m.gguf", "Oct 1, 2026", 14334457856), F("phi-3.5-mini-q6_k.gguf", "Sep 18, 2026", 3135946752)]),
      D(".cache", "Oct 14, 2026", [D("huggingface", "Oct 9, 2026")]),
    ])]),
    D("games", "Jul 4, 2026", [D("steam", "Oct 1, 2026")]),
    D("backup", "Jun 1, 2026", [F("photos-2025.tar", "Jan 3, 2026", 21474836480)]),
  ]),
  usb: D("", "", [D("models", "Oct 15, 2026", [F("Qwen2.5-7B-Instruct-Q5_K_M.gguf", "Oct 10, 2026", 5583457484), F("Llama-3.1-8B-Instruct-Q4_K_M.gguf", "Oct 11, 2026", 4920734106)]), D("logs", "Oct 15, 2026")]),
  nv4: D("", "", [D("Users", "Mar 3, 2026", [D("Nink", "Oct 2, 2026", [D("Desktop", "Oct 2, 2026", [F("notes.txt", "Oct 2, 2026", 3100)]), D("Videos", "Jul 7, 2026")])]), D("Program Files", "Mar 3, 2026"), F("pagefile.sys", "Oct 14, 2026", 8589934592)]),
};
const isImg = (e) => /\.(png|jpe?g|webp|gif)$/i.test(e.n);
const isDoc = (e) => /\.(pdf|txt|md|csv|docx?|json)$/i.test(e.n);
const kindOf = (e) => e.t === "f" && (/vault.*\.img$/i.test(e.n) ? "vault" : /\.gguf$/i.test(e.n) ? "model" : isImg(e) ? "image" : isDoc(e) ? "doc" : null);
const fmtSize = (b) => b == null ? "" : b >= 1073741824 ? (b / 1073741824).toFixed(1) + " GB" : b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : b >= 1024 ? Math.round(b / 1024) + " KB" : b + " B";
const countModels = (node) => (node.kids || []).filter((k) => kindOf(k) === "model").length;
const thumb = (e) => `<span class="thumb" style="--h:${e.hue ?? 200}"><i></i></span>`;
const IC = {
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>',
  vault: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/></svg>',
  model: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/></svg>',
  ssd: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 14h.01M11 14h6"/></svg>',
  usb: '<svg viewBox="0 0 24 24"><rect x="7" y="9" width="10" height="13" rx="2"/><path d="M9 9V3h6v6M11 5v1M13 5v1"/></svg>',
  lockd: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><rect x="9" y="11" width="6" height="5" rx="1"/><path d="M10 11v-1a2 2 0 014 0v1"/></svg>',
};
// mode: "folder" (pick a folder) | "vault" (folder mode that can also open a vault file) | "file" (multi-select files)
const fp = { mode: "folder", drive: "nv3", path: [], back: [], fwd: [], sel: new Set(), anchor: -1, cursor: -1, filter: "all", view: "list", cb: null };
const fpNode = (drive = fp.drive, path = fp.path) => path.reduce((n, seg) => n.kids.find((k) => k.n === seg), FS[drive]);
const fpRoot = (id = fp.drive) => state.drives.find((d) => d.id === id).path;
const fpFull = (extra) => [fpRoot(), ...fp.path, ...(extra ? [extra] : [])].join("/");
const driveLabel = (d) => d.name.replace("Host SSD · ", "").replace("StickLLM USB · ", "Stick ");
function fpEntries() {
  let ents = [...(fpNode().kids || [])].filter((k) => !k.n.startsWith(".") || fp.path.length > 1);
  if (fp.mode === "file" && fp.filter !== "all") ents = ents.filter((e) => e.t === "d" || (fp.filter === "images" ? isImg(e) : isDoc(e)));
  return ents.sort((a, b) => (a.t === b.t ? a.n.localeCompare(b.n) : a.t === "d" ? -1 : 1));
}
const selectable = (e) => fp.mode === "file" ? e.t === "f" : true;

function openPicker({ mode = "folder", drive = "nv3", path, title, cb } = {}) {
  Object.assign(fp, { mode, drive, path: path || [], back: [], fwd: [], sel: new Set(), anchor: -1, cursor: -1, cb, view: mode === "file" && fp.view === "grid" ? "grid" : "list" });
  $("#fpTitle").textContent = title || (mode === "vault" ? "Open vault or choose folder" : mode === "file" ? "Attach files" : "Choose folder");
  $("#fpFileTools").hidden = mode !== "file";
  $(".modal.fp").classList.toggle("fileMode", mode === "file");
  $("#picker").hidden = false; fpRender(); setTimeout(() => $("#fpList").focus(), 20);
}
function closePicker() { $("#picker").hidden = true; }
function fpGo(drive, path, push = true) {
  if (push) { fp.back.push([fp.drive, [...fp.path]]); fp.fwd = []; }
  fp.drive = drive; fp.path = path; if (fp.mode !== "file") fp.sel.clear(); fp.cursor = -1; fp.anchor = -1; fpRender(); $("#fpList").focus();
}
// selection keys are full paths so file-mode selections survive navigation
const keyOf = (e) => fpFull(e.n);
function fpRender() {
  $("#fpSide").innerHTML = '<div class="fpSideLab">Drives</div>' + state.drives.map((d) => {
    const blocked = d.state === "blocked", un = d.state === "unmounted";
    const sub = blocked ? "Encrypted" : un ? "Not mounted" : `${d.free} GiB free`;
    return `<button class="fpDrive ${d.id === fp.drive ? "on" : ""}" data-fd="${d.id}" ${blocked ? 'aria-disabled="true" title="Encrypted (BitLocker). Unlock in your OS first."' : un ? 'title="Click to mount (never formatted)"' : ""}>
      ${blocked ? IC.lockd : d.usb ? IC.usb : IC.ssd}<span><b>${driveLabel(d)}</b><small>${sub}</small></span></button>`;
  }).join("") + (fp.mode === "file" ? '<div class="fpSideLab" style="margin-top:12px">Places</div><button class="fpDrive" data-pl="Pictures">' + IC.folder + '<span><b>Pictures</b></span></button><button class="fpDrive" data-pl="Documents">' + IC.folder + '<span><b>Documents</b></span></button><button class="fpDrive" data-pl="Downloads">' + IC.folder + "<span><b>Downloads</b></span></button>" : "");
  $$("[data-fd]").forEach((b) => (b.onclick = () => {
    const d = state.drives.find((x) => x.id === b.dataset.fd);
    if (d.state === "blocked") return toast("Encrypted drive. Unlock it in your OS first.");
    if (d.state === "unmounted") { d.state = "mounted"; d.path = "/mnt/stickllm-host/nvme0n1p4"; renderDrives(); toast("Mounted " + d.path); }
    fpGo(d.id, []);
  }));
  $$("[data-pl]").forEach((b) => (b.onclick = () => fpGo("nv3", ["home", "nink", b.dataset.pl])));
  const d = state.drives.find((x) => x.id === fp.drive);
  const segs = [{ label: driveLabel(d), i: 0 }, ...fp.path.map((p, i) => ({ label: p, i: i + 1 }))];
  $("#fpCrumbs").innerHTML = segs.map((s, k) => `<button class="crumbBtn" data-ci="${s.i}">${esc(s.label)}</button>${k < segs.length - 1 ? '<span class="crumbSep">›</span>' : ""}`).join("");
  $$("[data-ci]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); fpGo(fp.drive, fp.path.slice(0, +b.dataset.ci)); }));
  $("#fpBackB").disabled = !fp.back.length; $("#fpFwd").disabled = !fp.fwd.length; $("#fpUp").disabled = !fp.path.length;
  $$("#fpFilter button").forEach((b) => b.classList.toggle("on", b.dataset.flt === fp.filter));
  $$("#fpView button").forEach((b) => { b.classList.toggle("on", b.dataset.view === fp.view); b.setAttribute("aria-pressed", b.dataset.view === fp.view); });
  const grid = fp.mode === "file" && fp.view === "grid";
  $("#fpList").classList.toggle("grid", grid); $(".fpCols").hidden = grid;
  $("#fpList").setAttribute("aria-multiselectable", fp.mode === "file");

  const ents = fpEntries();
  $("#fpList").innerHTML = ents.length ? ents.map((e, i) => {
    const k = kindOf(e), mc = e.t === "d" ? countModels(e) : 0, on = fp.sel.has(keyOf(e));
    const badge = fp.mode === "file" ? "" : k === "vault" ? '<span class="pill acc">StickLLM vault</span>' : k === "model" ? '<span class="pill">model</span>' : mc ? `<span class="pill">${mc} model${mc > 1 ? "s" : ""}</span>` : "";
    const dim = fp.mode !== "file" && e.t === "f" && k !== "vault" && k !== "model" ? "dim" : fp.mode === "file" && !k ? "dim" : "";
    const icon = e.t === "d" ? IC.folder : k === "image" ? thumb(e) : IC[k] || IC.file;
    const cls = `fpRow ${on ? "sel" : ""} ${i === fp.cursor ? "cur" : ""} ${dim}`;
    if (grid) return `<div class="${cls} tile" role="option" aria-selected="${on}" data-i="${i}">${e.t === "d" ? '<span class="thumb dir">' + IC.folder + "</span>" : k === "image" ? thumb(e) : '<span class="thumb doc">' + (IC[k] || IC.file) + "</span>"}${fp.mode === "file" && e.t === "f" ? '<span class="check"></span>' : ""}<span class="nm">${esc(e.n)}</span><small class="muted">${e.t === "d" ? "Folder" : fmtSize(e.sz)}</small></div>`;
    return `<div class="${cls}" role="option" aria-selected="${on}" data-i="${i}">
      <span class="fpName ${k || (e.t === "d" ? "dir" : "")}">${fp.mode === "file" ? `<span class="check ${e.t === "d" ? "none" : ""}"></span>` : ""}${icon}<span class="nm">${esc(e.n)}</span>${badge}</span>
      <span class="muted">${e.m}</span><span class="muted">${e.t === "d" ? "—" : fmtSize(e.sz)}</span></div>`;
  }).join("") : `<div class="fpEmpty">${fp.mode === "file" && fp.filter !== "all" ? "No " + fp.filter + " in this folder" : "This folder is empty"}</div>`;
  $$("#fpList .fpRow").forEach((r) => {
    r.onclick = (ev) => fpClick(+r.dataset.i, ev);
    r.ondblclick = () => fpActivate(+r.dataset.i);
  });
  fpFooter(ents);
}
function fpClick(i, ev = {}) {
  const ents = fpEntries(), e = ents[i]; fp.cursor = i;
  if (fp.mode !== "file") { fp.sel = new Set([keyOf(e)]); }
  else if (!selectable(e)) { /* folders: just focus; double-click opens */ }
  else if (ev.shiftKey && fp.anchor >= 0) {
    const [a, b] = [Math.min(fp.anchor, i), Math.max(fp.anchor, i)];
    ents.slice(a, b + 1).filter(selectable).forEach((x) => fp.sel.add(keyOf(x)));
  } else {
    const k = keyOf(e); fp.sel.has(k) ? fp.sel.delete(k) : fp.sel.add(k); fp.anchor = i; // click toggles (checkbox style)
  }
  fpRender(); $("#fpList").focus();
}
function fpFooter(ents) {
  const ok = $("#fpOk");
  if (fp.mode === "file") {
    const n = fp.sel.size;
    $("#fpSelLabel").textContent = n ? `${n} file${n > 1 ? "s" : ""} selected` : "Click files to select. Shift-click selects a range";
    $("#fpSel").textContent = n ? [...fp.sel].map((p) => p.split("/").pop()).join(", ") : fpFull();
    ok.textContent = n ? `Attach (${n})` : "Attach"; ok.disabled = !n; ok.dataset.kind = "files"; return;
  }
  const se = ents.find((e) => fp.sel.has(keyOf(e)));
  let label = "Selected folder", path = fpFull(), txt = "Select folder";
  if (se && se.t === "d") path = fpFull(se.n);
  else if (se && kindOf(se) === "vault" && fp.mode === "vault") { label = "Vault file"; path = fpFull(se.n); txt = "Open vault"; }
  else if (se && kindOf(se) === "model") label = "Model file (its folder will be used)";
  else if (se) label = "Files can't be selected. Using this folder";
  if (fp.mode === "vault" && !se && ents.some((e) => kindOf(e) === "vault")) label = "Selected folder · contains a StickLLM vault";
  $("#fpSelLabel").textContent = label; $("#fpSel").textContent = path; ok.textContent = txt; ok.disabled = false;
  ok.dataset.kind = txt === "Open vault" ? "vault" : "folder"; ok.dataset.path = path;
}
function fpActivate(i) {
  const e = fpEntries()[i]; if (!e) return;
  if (e.t === "d") fpGo(fp.drive, [...fp.path, e.n]);
  else if (fp.mode === "vault" && kindOf(e) === "vault") { fp.sel = new Set([keyOf(e)]); fpRender(); $("#fpOk").click(); }
  else if (fp.mode === "file") { fp.sel.add(keyOf(e)); fpRender(); $("#fpOk").click(); }
}
$("#fpBackB").onclick = () => { const p = fp.back.pop(); if (!p) return; fp.fwd.push([fp.drive, [...fp.path]]); fpGo(p[0], p[1], false); };
$("#fpFwd").onclick = () => { const p = fp.fwd.pop(); if (!p) return; fp.back.push([fp.drive, [...fp.path]]); fpGo(p[0], p[1], false); };
$("#fpUp").onclick = () => { if (fp.path.length) fpGo(fp.drive, fp.path.slice(0, -1)); };
$("#fpCrumbs").onclick = () => { const i = $("#fpPathIn"); $("#fpCrumbs").hidden = true; i.hidden = false; i.value = fpFull(); i.focus(); i.select(); };
$("#fpPathIn").onkeydown = (e) => {
  if (e.key === "Escape") { e.stopPropagation(); $("#fpPathIn").blur(); return; }
  if (e.key !== "Enter") return; e.preventDefault();
  const v = $("#fpPathIn").value.trim().replace(/\/+$/, "");
  const d = state.drives.find((x) => x.state === "mounted" && (v === x.path || v.startsWith(x.path + "/")));
  if (!d) return toast("That path isn't on a mounted drive");
  const segs = v.slice(d.path.length).split("/").filter(Boolean);
  let n; try { n = fpNode(d.id, segs); } catch { n = null; }
  if (!n || n.t !== "d") return toast("Folder not found");
  $("#fpPathIn").hidden = true; $("#fpCrumbs").hidden = false; fpGo(d.id, segs);
};
$("#fpPathIn").onblur = () => { $("#fpPathIn").hidden = true; $("#fpCrumbs").hidden = false; };
$("#fpNew").onclick = () => {
  const n = prompt("New folder name", "stickllm"); if (!n) return;
  const node = fpNode(); if (node.kids.some((k) => k.n === n)) return toast("A folder with that name already exists");
  node.kids.push(D(n, "Oct 15, 2026")); fp.cursor = fpEntries().findIndex((e) => e.n === n); if (fp.mode !== "file") fp.sel = new Set([fpFull(n)]); fpRender();
};
$$("#fpFilter button").forEach((b) => (b.onclick = () => { fp.filter = b.dataset.flt; fp.cursor = -1; fpRender(); }));
$$("#fpView button").forEach((b) => (b.onclick = () => { fp.view = b.dataset.view; fpRender(); }));
$("#fpList").addEventListener("keydown", (e) => {
  const n = fpEntries().length; if (!n) return;
  const cols = $("#fpList").classList.contains("grid") ? Math.max(1, Math.floor($("#fpList").clientWidth / 150)) : 1;
  const move = (to) => { fp.cursor = Math.max(0, Math.min(n - 1, to)); if (fp.mode !== "file") fp.sel = new Set([keyOf(fpEntries()[fp.cursor])]); else if (e.shiftKey && selectable(fpEntries()[fp.cursor])) fp.sel.add(keyOf(fpEntries()[fp.cursor])); fpRender(); };
  if (e.altKey && e.key === "ArrowLeft") { e.preventDefault(); $("#fpBackB").click(); }
  else if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); $("#fpFwd").click(); }
  else if (e.key === "ArrowDown") { e.preventDefault(); move(fp.cursor + cols); }
  else if (e.key === "ArrowUp") { e.preventDefault(); move(fp.cursor < 0 ? 0 : fp.cursor - cols); }
  else if (e.key === "ArrowRight" && cols > 1) { e.preventDefault(); move(fp.cursor + 1); }
  else if (e.key === "ArrowLeft" && cols > 1) { e.preventDefault(); move(fp.cursor - 1); }
  else if (e.key === "Home") { e.preventDefault(); move(0); }
  else if (e.key === "End") { e.preventDefault(); move(n - 1); }
  else if (e.key === " " && fp.mode === "file" && fp.cursor >= 0) { e.preventDefault(); fpClick(fp.cursor); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && fp.mode === "file") { e.preventDefault(); fpEntries().filter(selectable).forEach((x) => fp.sel.add(keyOf(x))); fpRender(); }
  else if (e.key === "Enter") { e.preventDefault(); const ce = fpEntries()[fp.cursor]; ce && ce.t === "d" ? fpActivate(fp.cursor) : $("#fpOk").click(); }
  else if (e.key === "Backspace") { e.preventDefault(); $("#fpUp").click(); }
  $("#fpList .cur")?.scrollIntoView({ block: "nearest" });
});
$("#fpCancel").onclick = closePicker; $("#fpClose").onclick = closePicker;
$("#picker").onclick = (e) => { if (e.target.id === "picker") closePicker(); };
$("#fpOk").onclick = () => {
  if ($("#fpOk").disabled) return;
  const { kind, path } = $("#fpOk").dataset, cb = fp.cb, files = [...fp.sel];
  closePicker(); cb?.(kind === "files" ? files : path, kind);
};

// Folder-mode uses
const onVaultPick = (path, kind) => {
  if (kind === "vault") { $("#vcSub").textContent = path + " · 32 GiB"; toast("Vault attached. Enter your passcode to unlock."); $("#vaultPass").focus(); }
  else { $("#vaultPath").value = path; $$("#sec-storage details.adv")[0].open = true; toast("Folder selected. Create a new vault file there."); }
};
$("#pickVault").onclick = () => openPicker({ mode: "vault", drive: "nv3", cb: onVaultPick });
$("#pickCreate").onclick = () => openPicker({ mode: "folder", title: "Choose folder for new vault", drive: "nv3", path: ["stickllm"], cb: (p) => ($("#vaultPath").value = p) });
$("#pickModelDir").onclick = () => openPicker({ mode: "folder", title: "Choose models folder", drive: "usb", cb: (p) => { $("#modelDir").textContent = p; toast("Models folder set. GGUF files there appear in the library."); } });

// File-mode use: composer attachments
state.attach = [];
const findFile = (full) => { for (const d of state.drives) { if (d.state !== "mounted" || !full.startsWith(d.path + "/")) continue; const segs = full.slice(d.path.length).split("/").filter(Boolean); try { return segs.reduce((n, s) => n.kids.find((k) => k.n === s), FS[d.id]); } catch { return null; } } return null; };
function renderAttach() {
  const box = $("#attachments");
  box.hidden = !state.attach.length;
  box.innerHTML = state.attach.map((p, i) => {
    const e = findFile(p) || { n: p.split("/").pop() }, img = isImg(e);
    return `<span class="att ${img ? "img" : ""}">${img ? thumb(e) : '<span class="attIc">' + IC.doc + "</span>"}<span class="attTx"><b>${esc(e.n)}</b><small>${fmtSize(e.sz)}</small></span><button type="button" class="attX" data-ax="${i}" aria-label="Remove ${esc(e.n)}"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></span>`;
  }).join("");
  $$("[data-ax]").forEach((b) => (b.onclick = () => { state.attach.splice(+b.dataset.ax, 1); renderAttach(); $("#input").focus(); }));
}
/* Attach + Mic reserved (disabled in HTML) — picker still exists for future / ?att=1 demos */
$("#attachBtn").onclick = null;

/* ---------- keyboard ---------- */
window.addEventListener("keydown", (e) => {
  const k = e.key.toLowerCase();
  if (e.ctrlKey && e.shiftKey && k === "l") { e.preventDefault(); lockVault(); }
  else if (e.ctrlKey && e.shiftKey && k === "o") { e.preventDefault(); newChat(); }
  else if (e.ctrlKey && k === "b") { e.preventDefault(); toggleNav(); }
  else if (e.ctrlKey && k === ",") { e.preventDefault(); openSettings(); }
  else if (e.key === "Escape") {
    if (!$("#confirm").hidden) $("#confirm").hidden = true;
    else if (!$("#picker").hidden) closePicker();
    else if (!$("#settings").hidden) closeSettings();
    else if (!$("#statusPop").hidden) $("#statusPop").hidden = true;
    else if (app.classList.contains("navOpen")) toggleNav(false);
  }
});

/* ---------- boot + URL hooks for screenshots ---------- */
renderConvs(); renderThread(); renderModels(); applyPreset("balanced"); renderDrives(); renderSaved(); renderDevices(); renderMovable();
const q = new URLSearchParams(location.search);
if (q.get("theme")) setTheme(q.get("theme"));
if (q.get("unlock")) setVault(true);
if (q.get("chat")) openChat(state.chats[0]);
if (q.get("s")) openSettings(q.get("s"));
if (q.get("adv")) { $("#advanced").open = true; setTimeout(() => $("#presets").scrollIntoView({ block: "start" }), 0); }
if (q.get("nav")) toggleNav(true);
if (q.get("fp")) { openPicker({ mode: "vault", drive: "nv3", cb: onVaultPick }); fpGo("nv3", ["home", "nink"]); fpGo("nv3", ["stickllm"]); fpClick(2); }
if (q.get("att")) { openPicker({ mode: "file", drive: "nv3", path: ["home", "nink", "Pictures"], cb: (f) => { state.attach.push(...f); renderAttach(); } }); fp.view = "grid"; fp.filter = "images"; fpRender(); [0, 3, 5].forEach((i) => fpClick(i)); }
if (q.get("chips")) { state.attach = ["/mnt/stickllm-host/nvme0n1p3/home/nink/Pictures/heater-broken.jpg", "/mnt/stickllm-host/nvme0n1p3/home/nink/Documents/lease-agreement.pdf"]; renderAttach(); }
})();
