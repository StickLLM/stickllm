(() => {
  const log = document.getElementById("log");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const statusLine = document.getElementById("statusLine");
  const sessionModeEl = document.getElementById("sessionMode");
  const apiHint = document.getElementById("apiHint");
  const webToggle = document.getElementById("webToggle");
  const modelsBtn = document.getElementById("modelsBtn");
  const chatsBtn = document.getElementById("chatsBtn");
  const settingsBtn = document.getElementById("settingsBtn");
  const pairBtn = document.getElementById("pairBtn");
  const modelsDialog = document.getElementById("modelsDialog");
  const chatsDialog = document.getElementById("chatsDialog");
  const settingsDialog = document.getElementById("settingsDialog");
  const chatsList = document.getElementById("chatsList");
  const modelsBody = document.getElementById("modelsBody");
  const settingsBody = document.getElementById("settingsBody");
  const catalogList = document.getElementById("catalogList");
  const pairDialog = document.getElementById("pairDialog");
  const pairForm = document.getElementById("pairForm");
  const pairCode = document.getElementById("pairCode");
  const pairErr = document.getElementById("pairErr");
  const netStatus = document.getElementById("netStatus");
  const wifiSsid = document.getElementById("wifiSsid");
  const wifiPass = document.getElementById("wifiPass");
  const wifiConnect = document.getElementById("wifiConnect");
  const connectPair = document.getElementById("connectPair");
  const connectModel = document.getElementById("connectModel");
  const connectUrl = document.getElementById("connectUrl");

  const API_BASE = window.STICKLLM_API || "";
  const TOKEN_KEY = "stickllm_pair_token";
  let token = localStorage.getItem(TOKEN_KEY) || "";
  let isLocalMode = false;
  let dlProgress = document.getElementById("dlProgress");
  let dlProgressLabel = document.getElementById("dlProgressLabel");
  let dlProgressFill = document.getElementById("dlProgressFill");
  let dlProgressBar = document.getElementById("dlProgressBar");
  let dlProgressMeta = document.getElementById("dlProgressMeta");
  let lastDownload = {};
  let dlPollTimer = null;
  // null = not seeded yet (avoid re-announcing an old remint on kiosk refresh)
  let lastRemintId = null;
  let sessionMode = "ephemeral";
  let sessionModeBusy = false;
  let activeChatId = null;
  let vaultPickerDevice = null;
  let vaultBrowsePath = "";
  let selectedModelId = null;
  let lastCatalog = [];

  function authHeaders(extra = {}) {
    const h = {
      "X-StickLLM-Client": "ui",
      ...extra,
    };
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
  }

  function applyLocalChrome(local) {
    isLocalMode = !!local;
    // Pair always remints a LAN code; stick shows it in chat, LAN opens enter-code.
    if (pairBtn) {
      pairBtn.hidden = false;
      pairBtn.title = isLocalMode
        ? "Unpair LAN browsers and show a new pair code"
        : "Mint a new pair code on the stick and enter it here";
    }
    if (input && isLocalMode) {
      input.placeholder = "Ask anything";
    }
    refreshSessionHints();
  }

  function refreshSessionHints() {
    if (!apiHint) return;
    if (isLocalMode) {
      apiHint.textContent = "this screen — no pair; LAN clients pair";
    } else {
      apiHint.textContent = token ? "session active" : "pair if prompted";
    }
  }
  refreshSessionHints();

  function renderConnect(j) {
    const c = j.connect || {};
    if (connectPair) {
      connectPair.textContent =
        c.pair_code ||
        (isLocalMode ? "…" : "(see stick screen)") ||
        "…";
    }
    if (connectUrl) {
      const url = c.url || (c.ip ? `http://${c.ip}/` : "") || c.local_url || "";
      connectUrl.textContent = url || "…";
      if (url && /^https?:\/\//i.test(url)) {
        connectUrl.href = url;
        connectUrl.removeAttribute("aria-disabled");
      } else {
        connectUrl.href = "#";
        connectUrl.setAttribute("aria-disabled", "true");
      }
    }
    if (connectModel) {
      let name = (c.model || "").trim();
      const none =
        !name ||
        name === "…" ||
        /^none\b/i.test(name) ||
        /^loading/i.test(name);
      if (j.llama_ok) {
        if (none) {
          const path = (c.model_path || "").trim();
          name = path ? path.split(/[/\\]/).pop() : "ready";
        }
        connectModel.textContent = name;
      } else if (none) {
        connectModel.textContent = "none — Activate in Models";
      } else {
        connectModel.textContent = `${name} (loading)`;
      }
    }
  }

  const messages = [
    {
      role: "system",
      content:
        "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful.",
    },
  ];

  function addBubble(role, text) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role;
    el.appendChild(who);
    el.appendChild(document.createTextNode(text));
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  async function pairStatus() {
    const r = await fetch("/api/pair/status", { cache: "no-store" });
    return r.json();
  }

  function clearPairSession() {
    token = "";
    localStorage.removeItem(TOKEN_KEY);
    refreshSessionHints();
  }

  async function sessionStillValid() {
    if (!token) return false;
    const t = await fetch("/api/storage", {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (t.status === 401) {
      clearPairSession();
      return false;
    }
    return t.ok;
  }

  async function ensurePaired(force = false) {
    const st = await pairStatus();
    if (st.local) applyLocalChrome(true);
    if (!st.require_pair || st.local) return true;
    if (!force && token) {
      if (await sessionStillValid()) return true;
    }
    pairErr.hidden = true;
    pairCode.value = "";
    pairDialog.showModal();
    pairCode.focus();
    return false;
  }

  async function remintPairCode() {
    const r = await fetch("/api/pair/remint", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: "{}",
      cache: "no-store",
    });
    let j = {};
    try {
      j = await r.json();
    } catch (_) {}
    if (!r.ok) {
      throw new Error(j.message || j.error || `remint ${r.status}`);
    }
    return j;
  }

  function announceRemintFromConnect(connect) {
    if (!isLocalMode) return;
    const c = connect || {};
    const rid = String(c.remint_id || "").trim();
    const code = String(c.pair_code || "").trim();
    // Seed on first local health so a later LAN remint is not treated as "old".
    if (lastRemintId === null) {
      lastRemintId = rid;
      return;
    }
    if (!rid || rid === lastRemintId) return;
    lastRemintId = rid;
    if (!/^\d{4,8}$/.test(code)) return;
    addBubble(
      "system",
      `New PAIR CODE: ${code} — open the URL above on phone/desktop and enter this code. Previous paired browsers were unpaired.`
    );
    statusLine.textContent = `pair code ${code}`;
  }

  async function issuePairFromStick() {
    statusLine.textContent = "minting pair code…";
    const j = await remintPairCode();
    const rid = String(j.remint_id || "").trim();
    if (rid) lastRemintId = rid;
    const code = String(j.pair_code || "").trim();
    if (code) {
      addBubble(
        "system",
        `New PAIR CODE: ${code} — open the URL above on phone/desktop and enter this code. Previous paired browsers were unpaired.`
      );
      statusLine.textContent = `pair code ${code}`;
    } else {
      addBubble("system", "New pair code minted — see Pair banner above.");
      statusLine.textContent = "pair code ready";
    }
    await refreshStatus();
    return code;
  }

  async function issuePairFromLan() {
    statusLine.textContent = "requesting new pair code…";
    clearPairSession();
    await remintPairCode();
    statusLine.textContent = "enter PAIR CODE from stick chat";
    addBubble(
      "system",
      "New pair code minted on the stick. Enter the PAIR CODE shown in the stick/kiosk chat."
    );
    await ensurePaired(true);
  }

  async function refreshStatus() {
    try {
      const r = await fetch(`/api/health`, { cache: "no-store" });
      if (!r.ok && r.status !== 503) throw new Error(`health ${r.status}`);
      const j = await r.json();
      let sessionOk = false;
      if (token && j.pair?.require_pair) {
        sessionOk = await sessionStillValid();
      } else if (!j.pair?.require_pair) {
        sessionOk = true;
      }
      const online = j.online || j.web;
      const modelName = j.connect?.model;
      const backend = String(j.backend || j.connect?.backend || "").toUpperCase();
      const backendBit = backend ? ` · ${backend}` : "";
      const noModel =
        !modelName ||
        /^none\b/i.test(String(modelName)) ||
        /^loading/i.test(String(modelName));
      const modelBit = j.llama_ok
        ? modelName && !noModel
          ? `model ready · ${modelName}${backendBit}`
          : `model ready${backendBit}`
        : modelName && !noModel
          ? `model loading · ${modelName}${backendBit}`
          : `no model — Activate in Models`;
      if (sessionOk) {
        statusLine.textContent = online
          ? `${modelBit} · online`
          : `${modelBit} · no uplink`;
      } else if (j.pair?.require_pair) {
        statusLine.textContent = "needs pair code (see stick screen)";
      } else {
        statusLine.textContent = modelBit;
      }
      if (j.pair?.local) applyLocalChrome(true);
      renderConnect(j);
      if (j.session_mode) applySessionModeUi(j.session_mode);
      try {
        const m = await fetch("/stickllm.json", { cache: "no-store" });
        if (m.ok) {
          const meta = await m.json();
          // stickllm.json "mode" is boot/kiosk profile (local/chat), not storage mode.
          if (meta.version && sessionModeEl) {
            sessionModeEl.title = `v${meta.version} · storage mode (Ephemeral = no SSD vault writes)`;
          }
          const bootMode = String(meta.mode || "").toLowerCase();
          if (bootMode === "local" || bootMode === "chat") {
            applyLocalChrome(true);
          }
        }
      } catch (_) {}
      announceRemintFromConnect(j.connect);
    } catch (e) {
      statusLine.textContent = "waiting for gateway…";
    }
  }

  async function control(action, params = {}) {
    const r = await fetch("/api/control", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ action, params }),
    });
    if (r.status === 401) {
      clearPairSession();
      statusLine.textContent = "needs pair code (see stick screen)";
      await ensurePaired(true);
      throw new Error("Pair required");
    }
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || j.message || `HTTP ${r.status}`);
    return j;
  }

  function isStickUsbVaultPath(path) {
    const p = String(path || "").trim().replace(/\/+$/, "");
    if (!p) return false;
    const bad = [
      "/mnt/stickllm-data",
      "/run/live",
      "/usr/lib/live/mount/medium",
      "/lib/live/mount/medium",
    ];
    return bad.some((b) => p === b || p.startsWith(`${b}/`));
  }

  function setVaultSetupFeedback(msg, kind = "info") {
    const hint = document.getElementById("vaultSetupHint");
    if (!hint) return;
    hint.textContent = msg || "";
    hint.classList.remove("is-info", "is-ok", "is-err");
    if (msg) {
      hint.classList.add(
        kind === "ok" ? "is-ok" : kind === "err" ? "is-err" : "is-info"
      );
      try {
        hint.scrollIntoView({ block: "nearest", behavior: "smooth" });
      } catch (_) {}
    }
    const vaultStatus = document.getElementById("vaultStatus");
    if (vaultStatus && msg && (kind === "ok" || kind === "err")) {
      vaultStatus.textContent =
        kind === "ok" ? `Vault: ${msg}` : `Vault create/unlock: ${msg}`;
    }
  }

  function fmtBytes(n) {
    if (!n || n < 0) return "—";
    const gb = n / 1024 ** 3;
    if (gb >= 1) return `${gb.toFixed(2)} GB`;
    const mb = n / 1024 ** 2;
    return `${mb.toFixed(0)} MB`;
  }

  function renderDownload(d) {
    lastDownload = d || {};
    if (!dlProgress) return false;
    const state = d?.state || "idle";
    if (state === "idle" || !state) {
      dlProgress.hidden = true;
      return false;
    }
    if (state === "done") {
      dlProgress.hidden = false;
      dlProgressLabel.textContent = `Downloaded: ${d.name || d.id || "model"}`;
      dlProgressFill.style.width = "100%";
      dlProgressBar.setAttribute("aria-valuenow", "100");
      dlProgressMeta.textContent = "Complete — hash verified";
      return true;
    }
    if (!["downloading", "verifying", "starting", "failed"].includes(state)) {
      dlProgress.hidden = true;
      return false;
    }
    dlProgress.hidden = false;
    const pct = d.percent == null ? null : Number(d.percent);
    const label =
      state === "verifying"
        ? `Verifying ${d.name || d.id || "model"}…`
        : state === "failed"
          ? `Download failed: ${d.name || d.id || "model"}`
          : `Downloading ${d.name || d.id || "model"}…`;
    dlProgressLabel.textContent = label;
    if (pct == null) {
      dlProgressFill.style.width = "15%";
      dlProgressBar.setAttribute("aria-valuenow", "0");
      dlProgressMeta.textContent = d.note || "in progress…";
    } else {
      dlProgressFill.style.width = `${Math.max(2, Math.min(100, pct))}%`;
      dlProgressBar.setAttribute("aria-valuenow", String(Math.round(pct)));
      const bits = [`${pct}%`, `${fmtBytes(d.bytes_done)} / ${fmtBytes(d.bytes_total)}`];
      if (d.eta_secs != null) bits.push(`ETA ~${Math.ceil(d.eta_secs / 60)}m`);
      if (d.note) bits.push(d.note);
      dlProgressMeta.textContent = bits.join(" · ");
    }
    return true;
  }

  function stopDlPoll() {
    if (dlPollTimer) {
      clearInterval(dlPollTimer);
      dlPollTimer = null;
    }
  }

  function startDlPoll() {
    stopDlPoll();
    dlPollTimer = setInterval(async () => {
      if (!modelsDialog?.open) {
        stopDlPoll();
        return;
      }
      try {
        const st = await control("status");
        renderModelsStatus(st);
        renderDownload(st.download || {});
        if (st.download?.state === "done") {
          renderCatalog(st.catalog || []);
        }
      } catch (_) {}
    }, 2000);
  }

  function renderModelsStatus(j) {
    const p = j.probe || {};
    const loaded = j.loaded || {};
    const loadLine = loaded.running
      ? `Running: ${loaded.name || loaded.id || loaded.path} (health ok)`
      : loaded.path
        ? `Loading: ${loaded.name || loaded.id || loaded.path} — ${loaded.health || "waiting /health"}`
        : "Loaded: (none)";
    const backend = String(j.backend || "cpu").toLowerCase();
    const backendLabel =
      backend === "cuda"
        ? `Backend: CUDA · VRAM ~${j.vram_gb ?? p.vram_gb ?? "?"} GB`
        : backend === "vulkan"
          ? `Backend: Vulkan · VRAM ~${j.vram_gb ?? p.vram_gb ?? "?"} GB`
          : `Backend: CPU · RAM ~${j.ram_gb ?? "?"} GB`;
    const lines = [
      backendLabel,
      p.recommend_name
        ? `Optimum: ${p.recommend_name} (~${p.recommend_size_gb} GB)`
        : "Optimum: unknown",
      loadLine,
      j.download_dir
        ? `Download dest: ${j.download_dir}`
        : p.dest
          ? `Download dest: ${p.dest}`
          : "",
      Array.isArray(j.models_dirs) && j.models_dirs.length
        ? `Scanning: ${j.models_dirs.filter((d) => !String(d).startsWith("/opt/")).slice(0, 3).join(" · ")}`
        : "",
    ].filter(Boolean);
    modelsBody.textContent = lines.join("\n");
    renderDownload(j.download || {});
  }

  function renderSettingsStatus(j) {
    const s = j.storage || {};
    const v = j.vault || {};
    const backend = String(j.backend || "cpu").toUpperCase();
    const lines = [
      `Backend: ${backend}`,
      s.mounted
        ? `USB DATA: mounted (${s.free_gb ?? "?"} GiB free)`
        : `USB DATA: ${s.note || "not claimed"}`,
      j.online ? "Uplink: online" : "Uplink: none (Ethernet or console WiFi first)",
    ];
    if (settingsBody) settingsBody.textContent = lines.join("\n");
    const vaultStatus = document.getElementById("vaultStatus");
    if (vaultStatus) {
      const bits = [`Vault: ${v.status || "absent"}`];
      if (v.root) bits.push(`root ${v.root}`);
      if (v.mounted) bits.push("mounted at /var/lib/stickllm/vault");
      const wipe = Number(v.wipe_after_failed_unlocks || 0);
      bits.push(wipe > 0 ? `wipe-after-${wipe}` : "wipe-after-N off");
      bits.push("file-blob only — never formats your drive");
      vaultStatus.textContent = bits.join(" · ");
      const wipeInput = document.getElementById("vaultWipeN");
      if (wipeInput && document.activeElement !== wipeInput) {
        wipeInput.value = String(wipe);
      }
    }
    if (netStatus) {
      const ssid = j.wifi?.ssid || "";
      netStatus.textContent = j.online
        ? `Online: yes${ssid ? ` · WiFi ${ssid}` : ""}`
        : `Online: no uplink${ssid ? ` · WiFi profile ${ssid}` : " · connect Ethernet or console WiFi"}`;
    }
    const how = document.getElementById("howToConnect");
    if (how) {
      const url =
        document.getElementById("connectUrl")?.textContent?.trim() ||
        "http://<stick-lan-ip>/";
      how.textContent =
        `Open ${url} on the same LAN and enter the PAIR CODE from the stick screen (or Pair | URL | Model above). Loopback on the stick needs no pair. No LAN? Term console: stickllm-wifi-setup.`;
    }
  }

  function applySessionModeUi(mode) {
    const m = String(mode || "ephemeral").toLowerCase() === "vault" ? "vault" : "ephemeral";
    sessionMode = m;
    if (sessionModeEl && sessionModeEl.value !== m && !sessionModeBusy) {
      sessionModeEl.value = m;
    }
    if (chatsBtn) chatsBtn.hidden = m !== "vault";
  }

  function resetChatMessages(keepSystem = true) {
    const sys = keepSystem
      ? messages.find((x) => x.role === "system") || {
          role: "system",
          content:
            "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful.",
        }
      : null;
    messages.length = 0;
    if (sys) messages.push(sys);
    if (log) log.innerHTML = "";
  }

  async function setSessionMode(mode) {
    const next = String(mode || "").toLowerCase() === "vault" ? "vault" : "ephemeral";
    const prev = sessionMode;
    sessionModeBusy = true;
    try {
      if (next === "vault") {
        // Unlock (or setup) before committing Vault mode — never silently stay locked.
        let vault = {};
        try {
          vault = await control("vault_status");
        } catch (_) {}
        const st = String(vault.status || "").toLowerCase();
        if (st === "absent" || !st) {
          applySessionModeUi(prev);
          if (sessionModeEl) sessionModeEl.value = prev;
          addBubble(
            "system",
            "No vault yet — create a blob on a mounted host SSD folder in Settings (not the StickLLM USB)."
          );
          if (settingsDialog && !settingsDialog.open) await openSettings();
          document.getElementById("vaultSetupPath")?.focus();
          return;
        }
        if (!(st === "unlocked" || vault.mounted)) {
          const pass = window.prompt("Enter vault passcode to unlock:");
          if (pass == null || pass === "") {
            applySessionModeUi(prev);
            if (sessionModeEl) sessionModeEl.value = prev;
            addBubble("system", "Vault mode cancelled — passcode required to unlock.");
            return;
          }
          const unlock = await control("vault_unlock", { passcode: pass });
          if (!unlock.ok) {
            applySessionModeUi(prev);
            if (sessionModeEl) sessionModeEl.value = prev;
            throw new Error(unlock.error || unlock.stderr || "unlock failed");
          }
        }
      }

      const r = await fetch("/api/session-mode", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ mode: next }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) {
        throw new Error(j.error || j.message || `HTTP ${r.status}`);
      }
      applySessionModeUi(next);
      if (next === "ephemeral") {
        const lockNote = j.vault_locked === false
          ? ` (vault lock: ${j.vault_lock_error || "failed"})`
          : " — vault locked.";
        addBubble(
          "system",
          `Ephemeral mode — no SSD vault writes${lockNote}`
        );
        return;
      }
      addBubble(
        "system",
        "Vault mode — models use your SSD models folder; chats/settings stay in the encrypted vault."
      );
    } catch (e) {
      applySessionModeUi(prev);
      if (sessionModeEl) sessionModeEl.value = prev;
      addBubble("system", `Could not switch mode: ${e.message}`);
    } finally {
      sessionModeBusy = false;
      applySessionModeUi(sessionMode);
    }
  }

  async function lockVault() {
    try {
      const res = await control("vault_lock");
      addBubble("system", res.ok !== false ? "Vault locked — model unloaded." : `Lock failed: ${res.error || res.stderr || "unknown"}`);
      messages.length = 0;
      if (sessionMode === "vault") {
        await setSessionMode("ephemeral");
      }
      if (settingsDialog?.open) await openSettings();
    } catch (e) {
      addBubble("system", `Lock failed: ${e.message}`);
    }
  }

  function selectedCatalogModel() {
    if (!selectedModelId) return null;
    return lastCatalog.find((m) => m.id === selectedModelId) || null;
  }

  function formatCtx(n) {
    const v = Number(n) || 0;
    return v >= 1024 ? `${Math.round(v / 1024)}k` : String(v);
  }

  function updateSelectionPanel() {
    const ctxPanel = document.getElementById("ctxPanel");
    const ctxSlider = document.getElementById("ctxSlider");
    const ctxValue = document.getElementById("ctxValue");
    const ctxMeta = document.getElementById("ctxMeta");
    const actActivate = document.getElementById("actActivate");
    const manage = document.getElementById("modelManage");
    const manageHint = document.getElementById("modelManageHint");
    const dlBtn = document.getElementById("actModelDownload");
    const delBtn = document.getElementById("actModelDelete");
    const m = selectedCatalogModel();

    if (!m) {
      if (ctxPanel) ctxPanel.hidden = true;
      if (manage) manage.hidden = true;
      return;
    }

    const canRun = !!m.runnable;
    const canDl = !!(m.pinned && !m.installed);
    const canDel = !!m.deletable;

    if (manage) manage.hidden = false;
    if (manageHint) {
      const bits = [
        !m.fits && m.installed
          ? m.backend === "cpu"
            ? "won't fit RAM"
            : "won't fit VRAM"
          : null,
        m.source === "host_ssd" ? "host SSD (delete in host OS)" : null,
        m.backend === "cpu" && m.installed ? "CPU" : null,
        m.vision ? "vision" : null,
      ].filter(Boolean);
      manageHint.textContent = bits.length ? bits.join(" · ") : "";
      manageHint.hidden = !bits.length;
    }
    if (dlBtn) {
      dlBtn.hidden = !canDl;
      dlBtn.disabled = false;
      dlBtn.textContent = "Download this model";
    }
    if (delBtn) {
      delBtn.hidden = !canDel;
      delBtn.disabled = false;
    }

    if (canRun && ctxPanel && ctxSlider && ctxValue && ctxMeta && actActivate) {
      ctxPanel.hidden = false;
      const lo = Math.max(2048, Number(m.ctx_min) || 2048);
      let hi = Math.max(lo, Number(m.ctx_max) || 8192);
      const step = hi <= 8192 ? 1024 : 2048;
      hi = Math.max(lo, Math.floor(hi / step) * step);
      let suggested = Number(m.ctx_suggested) || Math.min(8192, hi);
      suggested = Math.max(lo, Math.min(hi, suggested));
      suggested = Math.round(suggested / step) * step;
      ctxSlider.min = String(lo);
      ctxSlider.max = String(hi);
      ctxSlider.step = String(step);
      // Keep prior slider value if still in range for same model; else suggest.
      let cur = Number(ctxSlider.value) || suggested;
      if (cur < lo || cur > hi || ctxSlider.dataset.modelId !== m.id) {
        cur = suggested;
      }
      ctxSlider.value = String(cur);
      ctxSlider.dataset.modelId = m.id;
      ctxValue.textContent = String(cur);
      const free = m.free_mem_after_gb != null ? `~${m.free_mem_after_gb} GB free after load` : "";
      const modelMax = m.max_context ? `model max ${formatCtx(m.max_context)}` : "";
      ctxMeta.textContent = [
        `Slider range ${formatCtx(lo)}–${formatCtx(hi)} tokens`,
        free,
        modelMax,
        m.architecture ? m.architecture : null,
      ]
        .filter(Boolean)
        .join(" · ");
      actActivate.disabled = !!m.running;
      actActivate.textContent = m.running
        ? "Running"
        : m.active
          ? "Reload with context"
          : "Activate selected";
    } else if (ctxPanel) {
      ctxPanel.hidden = true;
    }
  }

  function modelLocationLabel(m) {
    if (m.source === "host_ssd") return "SSD";
    const p = String(m.path || m.local_path || "").toLowerCase();
    if (p.includes("stickllm-data") || p.startsWith("/opt/stickllm/models")) {
      return "USB";
    }
    if (p.includes("/var/lib/stickllm/vault")) return "SSD";
    if (/\bhdd\b|hard.?disk|rotational/.test(p)) return "HDD";
    if (m.installed && (p.startsWith("/mnt/") || p.startsWith("/media/"))) {
      return "SSD";
    }
    if (!m.installed) {
      return sessionMode === "vault" ? "SSD" : "USB";
    }
    return "USB";
  }

  function modelStatusLabel(m) {
    if (m.running) return "Running";
    if (m.installed) return "Downloaded";
    return "Not downloaded";
  }

  function renderCatalog(models) {
    lastCatalog = Array.isArray(models) ? models : [];
    catalogList.innerHTML = "";
    if (!lastCatalog.length) {
      catalogList.textContent = "No catalog entries.";
      selectedModelId = null;
      updateSelectionPanel();
      return;
    }

    if (
      selectedModelId &&
      !lastCatalog.some((m) => m.id === selectedModelId)
    ) {
      selectedModelId = null;
    }
    if (!selectedModelId) {
      const prefer =
        lastCatalog.find((m) => m.running) ||
        lastCatalog.find((m) => m.active) ||
        lastCatalog.find((m) => m.runnable) ||
        lastCatalog.find((m) => m.installed) ||
        lastCatalog[0];
      selectedModelId = prefer?.id || null;
    }

    for (const m of lastCatalog) {
      const row = document.createElement("div");
      row.className = "catalogRow";
      if (m.id === selectedModelId) row.classList.add("is-selected");

      const label = document.createElement("label");
      label.className = "catalogSelect";

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "catalogModel";
      radio.className = "catalogRadio";
      radio.value = m.id;
      radio.checked = m.id === selectedModelId;
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        selectedModelId = m.id;
        renderCatalog(lastCatalog);
      });

      const meta = document.createElement("div");
      meta.className = "catalogMeta";

      const title = document.createElement("strong");
      title.className = "catalogTitle";
      title.textContent = m.name || m.id;

      const detail = document.createElement("span");
      detail.className = "muted catalogDetail";
      const size =
        m.approx_size_gb != null && m.approx_size_gb !== ""
          ? `${m.approx_size_gb} GB`
          : null;
      const bits = [
        size,
        modelLocationLabel(m),
        modelStatusLabel(m),
      ].filter(Boolean);
      detail.textContent = bits.join(" · ");

      meta.appendChild(title);
      meta.appendChild(detail);
      label.appendChild(radio);
      label.appendChild(meta);
      row.appendChild(label);
      catalogList.appendChild(row);
    }
    updateSelectionPanel();
  }

  async function activateSelectedModel() {
    const m = selectedCatalogModel();
    const actActivate = document.getElementById("actActivate");
    const ctxSlider = document.getElementById("ctxSlider");
    if (!m) {
      modelsBody.textContent = "Select a model first.";
      return;
    }
    if (!m.runnable) {
      modelsBody.textContent = m.installed
        ? "Selected model does not fit this host."
        : "Selected model is not downloaded yet.";
      return;
    }
    const ctx = Number(ctxSlider?.value) || Number(m.ctx_suggested) || 8192;
    if (actActivate) {
      actActivate.disabled = true;
      actActivate.textContent = "Loading…";
    }
    try {
      modelsBody.textContent = `Loading ${m.name || m.id} (ctx ${ctx})…`;
      const res = await control("model_activate", { id: m.id, ctx_size: ctx });
      if (!res.ok && res.error) throw new Error(res.error);
      modelsBody.textContent = res.running
        ? `Now running: ${res.name || m.id} · ctx ${res.ctx_size || ctx}`
        : `Loading: ${res.name || m.id} · ctx ${res.ctx_size || ctx} — waiting for /health`;
      await openModels();
    } catch (e) {
      modelsBody.textContent = `Error: ${e.message}`;
      updateSelectionPanel();
    }
  }

  async function downloadSelectedModel() {
    const m = selectedCatalogModel();
    const dlBtn = document.getElementById("actModelDownload");
    if (!m) return;
    if (dlBtn) {
      dlBtn.disabled = true;
      dlBtn.textContent = "Downloading…";
    }
    try {
      modelsBody.textContent = `Starting download: ${m.id}…`;
      const res = await control("model_download", { id: m.id });
      renderDownload(res.download || { state: "starting", id: m.id, name: m.name });
      startDlPoll();
      await openModels();
    } catch (e) {
      modelsBody.textContent = `Error: ${e.message}`;
      if (dlBtn) {
        dlBtn.disabled = false;
        dlBtn.textContent = "Download this model";
      }
    }
  }

  function openDeleteConfirm() {
    const m = selectedCatalogModel();
    const dlg = document.getElementById("deleteConfirmDialog");
    const body = document.getElementById("deleteConfirmBody");
    const input = document.getElementById("deleteConfirmInput");
    const err = document.getElementById("deleteConfirmErr");
    if (!m?.deletable) {
      modelsBody.textContent = m
        ? "This model cannot be deleted from StickLLM (baked-in or host SSD)."
        : "Select a deletable model first.";
      return;
    }
    if (!dlg) return;
    if (body) {
      body.innerHTML =
        `Permanently delete downloaded files for <strong>${m.name || m.id}</strong>? ` +
        `Type <strong>ARE YOU SURE</strong> to confirm.`;
    }
    if (input) input.value = "";
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
    dlg.showModal();
    input?.focus();
  }

  async function confirmDeleteSelected() {
    const m = selectedCatalogModel();
    const dlg = document.getElementById("deleteConfirmDialog");
    const input = document.getElementById("deleteConfirmInput");
    const err = document.getElementById("deleteConfirmErr");
    const typed = String(input?.value || "").trim();
    if (typed !== "ARE YOU SURE") {
      if (err) {
        err.hidden = false;
        err.textContent = 'Type ARE YOU SURE exactly (all caps) to delete.';
      }
      return;
    }
    if (!m?.deletable) {
      dlg?.close();
      return;
    }
    try {
      modelsBody.textContent = `Deleting ${m.id}…`;
      const res = await control("model_delete", { id: m.id });
      if (!res.ok && res.error) throw new Error(res.error);
      modelsBody.textContent = `Deleted ${m.id}`;
      selectedModelId = null;
      dlg?.close();
      await openModels();
    } catch (e) {
      if (err) {
        err.hidden = false;
        err.textContent = e.message;
      } else {
        modelsBody.textContent = `Error: ${e.message}`;
      }
    }
  }

  async function openModels() {
    if (!(await ensurePaired())) return;
    modelsBody.textContent = "Loading…";
    catalogList.textContent = "";
    refreshSessionHints();
    modelsDialog.showModal();
    try {
      const st = await control("status");
      renderModelsStatus(st);
      renderCatalog(st.catalog || []);
      const d = st.download || {};
      if (["downloading", "starting", "verifying", "failed"].includes(d.state)) {
        startDlPoll();
      }
    } catch (e) {
      modelsBody.textContent = `Could not load: ${e.message}`;
    }
  }

  async function openSettings() {
    if (!(await ensurePaired())) return;
    if (settingsBody) settingsBody.textContent = "Loading…";
    refreshSessionHints();
    settingsDialog.showModal();
    try {
      const st = await control("status");
      renderSettingsStatus(st);
      await refreshVaultPicker({ quiet: true });
    } catch (e) {
      if (settingsBody) settingsBody.textContent = `Could not load: ${e.message}`;
    }
  }

  function setVaultUsbWarn(msg) {
    const el = document.getElementById("vaultUsbWarn");
    if (!el) return;
    if (msg) {
      el.hidden = false;
      el.textContent = msg;
    } else {
      el.hidden = true;
      el.textContent = "";
    }
  }

  function kindLabel(kind) {
    if (kind === "host_ssd") return "SSD";
    if (kind === "usb_stick") return "Stick USB";
    if (kind === "other_usb") return "USB";
    if (kind === "blocked") return "Blocked";
    return "Other";
  }

  async function refreshVaultPicker({ quiet = false } = {}) {
    const list = document.getElementById("vaultDeviceList");
    const diskList = document.getElementById("diskList");
    if (list) list.textContent = "Loading devices…";
    try {
      const res = await control("vault_devices");
      if (!res.ok) throw new Error(res.error || "device list failed");
      if (list) list.innerHTML = "";
      const devices = Array.isArray(res.devices) ? res.devices : [];
      const mountable = Array.isArray(res.mountable) ? res.mountable : [];
      const selectable = devices.filter((d) => d.selectable);
      if (!selectable.length && !mountable.length) {
        if (list) {
          list.textContent =
            "No browsable mounts. If a host SSD has a clear ext4/ntfs volume it should offer Mount; encrypted volumes stay locked.";
        }
        if (!quiet) {
          setVaultSetupFeedback(
            "No device available — Mount a clear host volume below, or unlock encrypted disks in the host OS.",
            "err"
          );
        }
      }
      for (const d of devices) {
        if (!list) break;
        const row = document.createElement("div");
        row.className =
          "vaultPickRow" +
          (d.selectable ? "" : " is-blocked") +
          (vaultPickerDevice?.mount_path === d.mount_path ? " is-selected" : "");
        const tag = document.createElement("span");
        tag.className = `vaultKind ${d.kind || "other"}`;
        tag.textContent = kindLabel(d.kind);
        const text = document.createElement("span");
        const free = d.avail ? ` · free ${d.avail}` : "";
        text.textContent = `${d.label || d.mount_path}${free}`;
        row.appendChild(tag);
        row.appendChild(text);
        if (d.selectable) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "actionBtn";
          btn.textContent = "Open";
          btn.addEventListener("click", () => selectVaultDevice(d));
          row.appendChild(btn);
        } else {
          const why = document.createElement("span");
          why.className = "muted";
          why.textContent = d.warn || "don't touch";
          row.appendChild(why);
        }
        list.appendChild(row);
      }
      for (const m of mountable) {
        if (!list) break;
        const row = document.createElement("div");
        row.className = "vaultPickRow";
        const tag = document.createElement("span");
        tag.className = `vaultKind ${m.kind || "host_ssd"}`;
        tag.textContent = kindLabel(m.kind) + " · unmounted";
        const text = document.createElement("span");
        text.textContent = `${m.label || m.device} · ${m.size_gb ?? "?"} GiB`;
        row.appendChild(tag);
        row.appendChild(text);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "actionBtn";
        btn.textContent = "Mount";
        btn.title = m.warn || "Mount read-write under /mnt/stickllm-host/";
        btn.addEventListener("click", () => mountHostVolume(m));
        row.appendChild(btn);
        list.appendChild(row);
      }
      if (diskList) {
        diskList.textContent = "";
        const blocked = Array.isArray(res.blocked_disks) ? res.blocked_disks : [];
        const lines = [];
        if (mountable.length) {
          lines.push(
            `Clear unencrypted volumes ready to Mount (${mountable.length}) — never formats.`
          );
        }
        if (blocked.length) {
          lines.push("Not offered (encrypted / unclear):");
          for (const b of blocked) {
            lines.push(
              `${b.path}  ${b.size_gb ?? "?"} GiB  ${b.model || ""} — ${b.reason || ""}`
            );
          }
        }
        diskList.textContent =
          lines.join("\n") ||
          res.safety ||
          "Pick Device → Folder above. Encrypted disks are never offered.";
      }
      return res;
    } catch (e) {
      if (list) list.textContent = `Error: ${e.message}`;
      if (!quiet) setVaultSetupFeedback(`Device list failed: ${e.message}`, "err");
      throw e;
    }
  }

  async function resolveVaultStartDir(mountPath, { kind } = {}) {
    const root = (mountPath || "").trim();
    if (!root) return root;
    // Host volumes: land in /home, Users/, Documents — not bare mount root.
    if (kind === "host_ssd" || kind === "other" || kind === "other_usb") {
      try {
        const res = await control("vault_browse_start", { path: root });
        if (res.ok && res.start_dir) return res.start_dir;
      } catch (_) {
        /* fall through to mount root */
      }
    }
    return root;
  }

  async function selectVaultDevice(device) {
    vaultPickerDevice = device;
    setVaultUsbWarn(
      device.kind === "usb_stick" || device.kind === "other_usb"
        ? device.warn ||
            "USB selected — data on the stick leaves when removed. Prefer host SSD for the vault."
        : ""
    );
    const start = await resolveVaultStartDir(device.mount_path, { kind: device.kind });
    await browseVaultDir(start);
    await refreshVaultPicker({ quiet: true });
  }

  async function mountHostVolume(vol) {
    const device = vol?.device || vol?.id || "";
    if (!device) {
      setVaultSetupFeedback("No device to mount.", "err");
      return;
    }
    const ok = window.confirm(
      `Mount ${device} (${vol.fstype || "fs"}, ${vol.size_gb ?? "?"} GiB) read-write under ${vol.suggested_mount || "/mnt/stickllm-host/…"}?\n\nNever formats. Encrypted volumes are refused.`
    );
    if (!ok) {
      setVaultSetupFeedback("Mount cancelled.", "info");
      return;
    }
    setVaultSetupFeedback(`Mounting ${device}…`, "info");
    try {
      const res = await control("vault_mount", {
        device,
        confirm: "MOUNT-HOST",
      });
      if (!res.ok) throw new Error(res.error || res.stderr || "mount failed");
      const mp = res.mount_path || vol.suggested_mount || "";
      setVaultSetupFeedback(
        res.already_mounted
          ? `Already mounted at ${mp} — opening folder browser.`
          : `Mounted ${device} at ${mp}. Pick a folder, then CREATE-VAULT.`,
        "ok"
      );
      await refreshVaultPicker({ quiet: true });
      if (mp) {
        vaultPickerDevice = {
          kind: vol.kind || "host_ssd",
          mount_path: mp,
          label: vol.label,
        };
        setVaultUsbWarn("");
        const start = await resolveVaultStartDir(mp, { kind: vol.kind || "host_ssd" });
        await browseVaultDir(start);
      }
    } catch (e) {
      setVaultSetupFeedback(`Mount failed: ${e.message}`, "err");
    }
  }

  function clearVaultModelHits() {
    const hitsEl = document.getElementById("vaultModelHits");
    if (hitsEl) {
      hitsEl.hidden = true;
      hitsEl.innerHTML = "";
    }
  }

  function renderVaultModelHits(res) {
    const hitsEl = document.getElementById("vaultModelHits");
    if (!hitsEl) return;
    const hits = Array.isArray(res.hits) ? res.hits : [];
    hitsEl.innerHTML = "";
    if (!hits.length) {
      hitsEl.hidden = false;
      hitsEl.textContent =
        "No model folders found under common locations (GGUF dirs, models/, Ollama, LM Studio, HuggingFace). Browse manually from the start folder.";
      return;
    }
    hitsEl.hidden = false;
    const head = document.createElement("div");
    head.className = "vaultModelHitMeta";
    head.textContent = `Found ${hits.length} location(s) — open one or Use this folder after jumping.`;
    hitsEl.appendChild(head);
    for (const hit of hits.slice(0, 24)) {
      const row = document.createElement("div");
      row.className = "vaultPickRow";
      const label = document.createElement("span");
      const gguf = hit.gguf_count ? ` · ${hit.gguf_count} GGUF` : "";
      label.textContent = `${hit.relative || hit.path}${gguf} — ${hit.reason || hit.kind || ""}`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "actionBtn";
      btn.textContent = "Open";
      btn.addEventListener("click", async () => {
        await browseVaultDir(hit.path);
        useVaultBrowseFolder();
      });
      row.appendChild(label);
      row.appendChild(btn);
      hitsEl.appendChild(row);
    }
  }

  async function findVaultModels() {
    const base =
      (vaultPickerDevice?.mount_path || "").trim() || (vaultBrowsePath || "").trim();
    if (!base) {
      setVaultSetupFeedback("Open a mounted device first, then Find existing models.", "err");
      return;
    }
    const findBtn = document.getElementById("actVaultFindModels");
    if (findBtn) findBtn.disabled = true;
    setVaultSetupFeedback("Searching for existing model folders…", "info");
    try {
      const res = await control("vault_find_models", { path: base });
      if (!res.ok) throw new Error(res.error || "find models failed");
      renderVaultModelHits(res);
      const jump = res.best?.path || res.jump_dir || res.start_dir;
      if (jump) {
        await browseVaultDir(jump);
        if (res.best) {
          useVaultBrowseFolder();
          setVaultSetupFeedback(
            `Best match: ${res.best.relative || res.best.path} (${res.best.reason || "models"}).`,
            "ok"
          );
        } else {
          setVaultSetupFeedback(
            `No strong model hits — started at ${res.start_dir || jump} (${res.start_reason || "default"}).`,
            "info"
          );
        }
      } else {
        setVaultSetupFeedback("Search finished — no browsable start folder.", "err");
      }
    } catch (e) {
      clearVaultModelHits();
      setVaultSetupFeedback(`Find models failed: ${e.message}`, "err");
    } finally {
      if (findBtn) findBtn.disabled = !vaultPickerDevice;
    }
  }

  async function browseVaultDir(path) {
    const folderList = document.getElementById("vaultFolderList");
    const pathEl = document.getElementById("vaultBrowsePath");
    const upBtn = document.getElementById("actVaultBrowseUp");
    const useBtn = document.getElementById("actVaultBrowseUse");
    const newBtn = document.getElementById("actVaultBrowseNew");
    const findBtn = document.getElementById("actVaultFindModels");
    if (folderList) folderList.textContent = "Loading folders…";
    try {
      const res = await control("vault_list_dirs", { path });
      if (!res.ok) throw new Error(res.error || "list dirs failed");
      vaultBrowsePath = res.path || path;
      if (pathEl) pathEl.textContent = vaultBrowsePath;
      if (upBtn) upBtn.disabled = !res.parent;
      if (useBtn) useBtn.disabled = false;
      if (newBtn) newBtn.disabled = !res.can_mkdir;
      if (findBtn) findBtn.disabled = !(vaultPickerDevice?.mount_path || vaultBrowsePath);
      if (res.is_stick_usb || res.warn) {
        setVaultUsbWarn(
          res.warn ||
            "Browsing StickLLM USB — vault data leaves when the stick is removed."
        );
      } else if (vaultPickerDevice?.kind === "host_ssd") {
        setVaultUsbWarn("");
      }
      if (folderList) {
        folderList.innerHTML = "";
        const entries = Array.isArray(res.entries) ? res.entries : [];
        if (!entries.length) {
          folderList.textContent = "(no subfolders — you can Use this folder or New folder)";
        }
        for (const ent of entries) {
          const row = document.createElement("div");
          row.className = "vaultPickRow";
          row.textContent = ent.name;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "actionBtn";
          btn.textContent = "Open";
          btn.addEventListener("click", () => browseVaultDir(ent.path));
          row.appendChild(document.createTextNode(" "));
          row.appendChild(btn);
          folderList.appendChild(row);
        }
      }
      return res;
    } catch (e) {
      if (folderList) folderList.textContent = `Error: ${e.message}`;
      setVaultSetupFeedback(`Folder browse failed: ${e.message}`, "err");
      throw e;
    }
  }

  function useVaultBrowseFolder() {
    const path = (vaultBrowsePath || "").trim();
    const input = document.getElementById("vaultSetupPath");
    if (!path) {
      setVaultSetupFeedback("Choose a folder — open a device, then Use this folder.", "err");
      return;
    }
    if (input) input.value = path;
    const usb = isStickUsbVaultPath(path) || vaultPickerDevice?.kind === "usb_stick";
    setVaultSetupFeedback(
      usb
        ? `Selected USB folder ${path} — data leaves when stick is removed. Prefer host SSD.`
        : `Selected folder ${path}`,
      usb ? "err" : "ok"
    );
  }

  async function createVaultBrowseFolder() {
    if (!vaultBrowsePath) {
      setVaultSetupFeedback("Open a device/folder first.", "err");
      return;
    }
    const name = window.prompt("New folder name (letters, digits, . _ -):", "StickLLM");
    if (!name) return;
    try {
      const res = await control("vault_mkdir", { path: vaultBrowsePath, name: name.trim() });
      if (!res.ok) throw new Error(res.error || "mkdir failed");
      setVaultSetupFeedback(`Created folder ${res.path}`, "ok");
      await browseVaultDir(res.path || vaultBrowsePath);
      useVaultBrowseFolder();
    } catch (e) {
      setVaultSetupFeedback(`New folder failed: ${e.message}`, "err");
    }
  }

  async function chat(userText) {
    if (!(await ensurePaired())) return;
    messages.push({ role: "user", content: userText });
    addBubble("user", userText);
    const assistantEl = addBubble("assistant", "…");
    send.disabled = true;
    const web = webToggle?.checked ? "on" : "off";

    try {
      const r = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          model: "stickllm",
          messages,
          stream: false,
          temperature: 0.7,
          web,
        }),
      });
      if (r.status === 401) {
        clearPairSession();
        statusLine.textContent = "needs pair code (see stick screen)";
        assistantEl.lastChild.textContent =
          "Pair required — enter the code from the stick screen.";
        await ensurePaired(true);
        return;
      }
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const err = await r.json();
          msg = err.message || err.error || msg;
        } catch (_) {
          msg = (await r.text()) || msg;
        }
        throw new Error(msg);
      }
      const data = await r.json();
      let reply =
        data?.choices?.[0]?.message?.content?.trim() || "(empty response)";
      const webInfo = data?.stickllm_web;
      if (webInfo?.used && webInfo.results?.length) {
        const cites = webInfo.results
          .slice(0, 3)
          .map((x) => x.url)
          .filter(Boolean);
        if (cites.length) {
          reply += "\n\nSources:\n" + cites.map((u) => `• ${u}`).join("\n");
        }
      }
      messages.push({ role: "assistant", content: reply });
      assistantEl.lastChild.textContent = reply;
      if (sessionMode === "vault") {
        // Persist only in Vault mode; never write chats in Ephemeral.
        saveCurrentChat({ quiet: true }).catch(() => {});
      }
    } catch (err) {
      assistantEl.classList.add("system");
      assistantEl.lastChild.textContent = `Error: ${err.message}`;
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;
    input.value = "";
    chat(text);
  });

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      form.requestSubmit();
    }
  });

  pairForm?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    pairErr.hidden = true;
    const code = pairCode.value.trim();
    try {
      const r = await fetch("/api/pair", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-StickLLM-Client": "ui",
        },
        body: JSON.stringify({ code }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.message || j.error || "Pair failed");
      token = j.token;
      localStorage.setItem(TOKEN_KEY, token);
      refreshSessionHints();
      pairDialog.close();
      statusLine.textContent = "paired";
      addBubble("system", "Paired. Chat, Models, and Settings unlocked until reboot.");
    } catch (e) {
      pairErr.textContent = e.message;
      pairErr.hidden = false;
    }
  });

  async function openChats() {
    if (!(await ensurePaired())) return;
    if (sessionMode !== "vault") {
      addBubble("system", "Switch Mode to Vault to use saved chats.");
      return;
    }
    chatsDialog?.showModal();
    if (chatsList) chatsList.textContent = "Loading…";
    try {
      const r = await fetch("/api/chats", { headers: authHeaders() });
      const j = await r.json();
      if (!r.ok || j.ok === false) {
        if (chatsList) chatsList.textContent = j.error || "Could not list chats";
        return;
      }
      renderChatsList(j.chats || []);
    } catch (e) {
      if (chatsList) chatsList.textContent = e.message;
    }
  }

  function renderChatsList(chats) {
    if (!chatsList) return;
    chatsList.innerHTML = "";
    if (!chats.length) {
      chatsList.textContent = "No saved chats yet.";
      return;
    }
    for (const c of chats) {
      const row = document.createElement("div");
      row.className = "catalogRow";
      const meta = document.createElement("div");
      meta.textContent = `${c.title || c.id} · ${c.messages || 0} msgs`;
      const actions = document.createElement("div");
      actions.className = "catalogActions";
      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.className = "actionBtn";
      openBtn.textContent = "Open";
      openBtn.addEventListener("click", async () => {
        try {
          const r = await fetch(`/api/chats/${encodeURIComponent(c.id)}`, {
            headers: authHeaders(),
          });
          const j = await r.json();
          if (!r.ok || j.ok === false) throw new Error(j.error || "load failed");
          resetChatMessages(false);
          activeChatId = j.id || c.id;
          for (const m of j.messages || []) {
            if (m.role === "system") {
              messages.push(m);
              continue;
            }
            messages.push(m);
            addBubble(m.role, m.content);
          }
          if (!messages.some((x) => x.role === "system")) {
            messages.unshift({
              role: "system",
              content:
                "You are StickLLM, a local assistant on a Privacy AI USB. Be concise and helpful.",
            });
          }
          chatsDialog?.close();
        } catch (e) {
          addBubble("system", `Open chat failed: ${e.message}`);
        }
      });
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "actionBtn";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Delete chat “${c.title || c.id}”?`)) return;
        try {
          const r = await fetch("/api/chats", {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ delete: true, id: c.id }),
          });
          const j = await r.json();
          if (!r.ok || j.ok === false) throw new Error(j.error || "delete failed");
          if (activeChatId === c.id) activeChatId = null;
          await openChats();
        } catch (e) {
          addBubble("system", `Delete failed: ${e.message}`);
        }
      });
      actions.appendChild(openBtn);
      actions.appendChild(delBtn);
      row.appendChild(meta);
      row.appendChild(actions);
      chatsList.appendChild(row);
    }
  }

  async function saveCurrentChat(opts = {}) {
    const quiet = !!opts.quiet;
    if (sessionMode !== "vault") {
      if (!quiet) addBubble("system", "Switch Mode to Vault to save chats.");
      return;
    }
    const title =
      (messages.find((m) => m.role === "user")?.content || "Chat").slice(0, 60) || "Chat";
    try {
      const r = await fetch("/api/chats", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          id: activeChatId || undefined,
          title,
          messages,
        }),
      });
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || "save failed");
      activeChatId = j.id;
      if (!quiet) addBubble("system", `Saved chat “${j.title || title}” in vault.`);
    } catch (e) {
      if (!quiet) addBubble("system", `Save failed: ${e.message}`);
      throw e;
    }
  }

  modelsBtn?.addEventListener("click", () => openModels());
  chatsBtn?.addEventListener("click", () => openChats());
  settingsBtn?.addEventListener("click", () => openSettings());
  sessionModeEl?.addEventListener("change", () => {
    setSessionMode(sessionModeEl.value);
  });
  document.getElementById("lockVaultBtn")?.addEventListener("click", () => lockVault());
  document.getElementById("actChatNew")?.addEventListener("click", () => {
    activeChatId = null;
    resetChatMessages(true);
    addBubble("system", "New chat (not saved until you Save).");
    chatsDialog?.close();
  });
  document.getElementById("actChatSave")?.addEventListener("click", () => saveCurrentChat());
  document.getElementById("chatsClose")?.addEventListener("click", () => chatsDialog?.close());
  document.getElementById("actVaultSetup")?.addEventListener("click", async () => {
    const path = (document.getElementById("vaultSetupPath")?.value || "").trim();
    const size = String(document.getElementById("vaultSetupSize")?.value || "8");
    const pass = document.getElementById("vaultSetupPass")?.value || "";
    const pass2 = document.getElementById("vaultSetupPass2")?.value || "";
    const confirm = (document.getElementById("vaultSetupConfirm")?.value || "").trim();
    const recoveryEl = document.getElementById("vaultRecovery");
    if (!path) {
      setVaultSetupFeedback(
        "Choose a folder — pick Device → open folders → Use this folder (path is blank).",
        "err"
      );
      return;
    }
    if (path.startsWith("/dev/") || path.startsWith("\\\\.\\")) {
      setVaultSetupFeedback("Refusing block device — pick a mounted host SSD folder.", "err");
      return;
    }
    if (isStickUsbVaultPath(path)) {
      setVaultSetupFeedback(
        "Refusing StickLLM USB / STICKLLM-DATA — vault must be on a mounted host SSD folder.",
        "err"
      );
      return;
    }
    if (confirm !== "CREATE-VAULT") {
      setVaultSetupFeedback(
        "Type CREATE-VAULT exactly to confirm (never formats your drive).",
        "err"
      );
      return;
    }
    if (pass.length < 8 || pass !== pass2) {
      setVaultSetupFeedback("Passcode must match and be at least 8 characters.", "err");
      return;
    }
    setVaultSetupFeedback("Creating vault blob on host path (non-destructive)…", "info");
    try {
      const res = await control("vault_setup", {
        path,
        size_gb: size,
        confirm: "CREATE-VAULT",
        recovery_confirm: "SHOW-ONCE",
        passcode: pass,
        passcode2: pass2,
        space_confirm: "SPACE-OK",
      });
      if (!res.ok) {
        throw new Error(res.error || res.stderr || res.note || "setup failed");
      }
      if (String(res.status || "").toLowerCase() === "absent") {
        throw new Error(
          res.error ||
            res.stderr ||
            "API reported success but vault is still absent — refuse silent success"
        );
      }
      if (document.getElementById("vaultSetupPass")) document.getElementById("vaultSetupPass").value = "";
      if (document.getElementById("vaultSetupPass2")) document.getElementById("vaultSetupPass2").value = "";
      if (document.getElementById("vaultSetupConfirm")) document.getElementById("vaultSetupConfirm").value = "";
      const phrase = res.recovery_phrase || "";
      if (recoveryEl) {
        recoveryEl.style.display = "block";
        recoveryEl.textContent = phrase
          ? `RECOVERY PHRASE (shown once — write it down):\n${phrase}`
          : "Vault created. (Recovery phrase missing from response — check stick logs.)";
      }
      const savedLabel = document.getElementById("vaultSavedLabel");
      const finishBtn = document.getElementById("actVaultSetupFinish");
      if (savedLabel) savedLabel.hidden = false;
      if (finishBtn) finishBtn.hidden = false;
      const blob = res.blob || `${path.replace(/\/$/, "")}/stickllm-vault.img`;
      setVaultSetupFeedback(
        `Success — vault created at ${blob} (folder ${path}). Write the recovery phrase, type SAVED, then Finish.`,
        "ok"
      );
      addBubble(
        "system",
        `Vault created — full path ${blob}. Write down the recovery phrase in Settings.`
      );
      await setSessionMode("vault");
      if (settingsDialog?.open) {
        const st = await control("status");
        renderSettingsStatus(st);
      }
    } catch (e) {
      setVaultSetupFeedback(`Setup failed: ${e.message}`, "err");
      addBubble("system", `Vault setup failed: ${e.message}`);
    }
  });
  document.getElementById("actVaultSetupFinish")?.addEventListener("click", () => {
    const saved = (document.getElementById("vaultSetupSaved")?.value || "").trim();
    const recoveryEl = document.getElementById("vaultRecovery");
    if (saved !== "SAVED") {
      setVaultSetupFeedback("Type SAVED after writing the recovery phrase.", "err");
      return;
    }
    if (recoveryEl) {
      recoveryEl.textContent = "(recovery phrase cleared from this screen)";
    }
    const savedLabel = document.getElementById("vaultSavedLabel");
    const finishBtn = document.getElementById("actVaultSetupFinish");
    if (savedLabel) savedLabel.hidden = true;
    if (finishBtn) finishBtn.hidden = true;
    if (document.getElementById("vaultSetupSaved")) document.getElementById("vaultSetupSaved").value = "";
    setVaultSetupFeedback("Recovery phrase acknowledged. Keep your written copy safe.", "ok");
    addBubble("system", "Recovery phrase acknowledged.");
  });
  document.getElementById("actVaultGrow")?.addEventListener("click", async () => {
    const gb = String(document.getElementById("vaultGrowGb")?.value || "8");
    const typed = window.prompt(`Type GROW-VAULT to expand the blob by ${gb} GiB (free space checked):`, "");
    if (typed !== "GROW-VAULT") {
      addBubble("system", "Grow aborted.");
      return;
    }
    try {
      const res = await control("vault_grow", { add_gb: gb, confirm: "GROW-VAULT" });
      if (!res.ok) throw new Error(res.error || res.stderr || "grow failed");
      addBubble("system", `Vault grew by ${gb} GiB.`);
      if (settingsDialog?.open) await openSettings();
    } catch (e) {
      addBubble("system", `Grow failed: ${e.message}`);
    }
  });
  document.getElementById("actVaultWipe")?.addEventListener("click", async () => {
    const n = String(document.getElementById("vaultWipeN")?.value || "0");
    let confirm = "";
    if (n !== "0") {
      confirm = window.prompt(
        `Type WIPE-OK to enable wipe after ${n} failed unlocks (destroys blob LUKS header only):`,
        ""
      );
      if (confirm !== "WIPE-OK") {
        addBubble("system", "Wipe setting aborted.");
        return;
      }
    }
    try {
      const res = await control("vault_set_wipe", { n, confirm: confirm || "OFF" });
      if (!res.ok) throw new Error(res.error || res.stderr || "failed");
      addBubble("system", `Wipe-after-N set to ${n} (0 = off).`);
      if (settingsDialog?.open) await openSettings();
    } catch (e) {
      addBubble("system", `Wipe setting failed: ${e.message}`);
    }
  });
  document.getElementById("actVaultMovable")?.addEventListener("click", async () => {
    const el = document.getElementById("movableList");
    if (el) el.textContent = "Listing…";
    try {
      const res = await control("vault_list_movable");
      const models = res.models || [];
      if (!el) return;
      el.innerHTML = "";
      if (!models.length) {
        el.textContent = "No USB models to move (or DATA not mounted).";
        return;
      }
      for (const m of models) {
        const line = document.createElement("div");
        line.textContent = `${m.name}  ${Math.round((m.size || 0) / 1e9 * 10) / 10} GB${
          m.in_vault ? " (already in vault)" : ""
        }`;
        if (!m.in_vault) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "actionBtn";
          btn.textContent = "Move → vault";
          btn.addEventListener("click", async () => {
            if (!confirm(`Move ${m.name} into vault? Source removed after SHA-256 verify.`)) return;
            btn.disabled = true;
            try {
              const r = await control("vault_move_model", {
                path: m.path,
                confirm: "MOVE-MODEL",
              });
              if (!r.ok) throw new Error(r.error || r.stderr || "move failed");
              addBubble("system", `Moved ${m.name} into vault (SHA-256 OK).`);
              document.getElementById("actVaultMovable")?.click();
            } catch (e) {
              addBubble("system", `Move failed: ${e.message}`);
              btn.disabled = false;
            }
          });
          line.appendChild(document.createTextNode(" "));
          line.appendChild(btn);
        }
        el.appendChild(line);
      }
    } catch (e) {
      if (el) el.textContent = e.message;
    }
  });
  document.getElementById("actVaultDisks")?.addEventListener("click", async () => {
    try {
      await refreshVaultPicker({ quiet: false });
    } catch (_) {}
  });
  document.getElementById("actVaultPickerRefresh")?.addEventListener("click", async () => {
    try {
      await refreshVaultPicker({ quiet: false });
    } catch (_) {}
  });
  document.getElementById("actVaultBrowseUse")?.addEventListener("click", () => useVaultBrowseFolder());
  document.getElementById("actVaultBrowseNew")?.addEventListener("click", () => createVaultBrowseFolder());
  document.getElementById("actVaultFindModels")?.addEventListener("click", () => findVaultModels());
  // Up is rebound per browseVaultDir response (once). Keep a stable handler too.
  document.getElementById("actVaultBrowseUp")?.addEventListener("click", async () => {
    if (!vaultBrowsePath || !vaultPickerDevice) return;
    try {
      const cur = await control("vault_list_dirs", { path: vaultBrowsePath });
      if (cur.parent) await browseVaultDir(cur.parent);
    } catch (e) {
      setVaultSetupFeedback(`Up failed: ${e.message}`, "err");
    }
  });
  document.getElementById("actVaultUnlock")?.addEventListener("click", async () => {
    const pass = document.getElementById("vaultPass")?.value || "";
    const vaultStatus = document.getElementById("vaultStatus");
    if (vaultStatus) vaultStatus.textContent = "Unlocking…";
    try {
      const res = await control("vault_unlock", { passcode: pass });
      if (document.getElementById("vaultPass")) document.getElementById("vaultPass").value = "";
      if (res.ok) {
        setVaultSetupFeedback("Vault unlocked.", "ok");
        if (vaultStatus) vaultStatus.textContent = "Vault: unlocked";
        if (sessionMode !== "vault") {
          await setSessionMode("vault");
        }
      } else {
        const msg = res.error || res.stderr || "bad passcode / no vault configured";
        setVaultSetupFeedback(`Unlock failed: ${msg}`, "err");
        if (vaultStatus) vaultStatus.textContent = `Unlock failed: ${msg}`;
      }
      const st = await control("status");
      renderSettingsStatus(st);
    } catch (e) {
      setVaultSetupFeedback(`Unlock error: ${e.message}`, "err");
      if (vaultStatus) vaultStatus.textContent = `Error: ${e.message}`;
    }
  });
  document.getElementById("actVaultLock")?.addEventListener("click", () => lockVault());
  window.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey && ev.shiftKey && (ev.key === "L" || ev.key === "l")) {
      ev.preventDefault();
      lockVault();
    }
  });
  pairBtn?.addEventListener("click", async () => {
    try {
      if (isLocalMode) {
        await issuePairFromStick();
      } else {
        await issuePairFromLan();
      }
    } catch (e) {
      addBubble("system", `Pair remint failed: ${e.message}`);
      statusLine.textContent = "pair remint failed";
    }
  });
  document.getElementById("modelsClose")?.addEventListener("click", () => {
    stopDlPoll();
    modelsDialog.close();
  });
  document.getElementById("settingsClose")?.addEventListener("click", () => {
    settingsDialog.close();
  });
  modelsDialog?.addEventListener("close", () => stopDlPoll());

  wifiConnect?.addEventListener("click", async () => {
    const ssid = (wifiSsid?.value || "").trim();
    const password = wifiPass?.value || "";
    if (!ssid) {
      if (netStatus) netStatus.textContent = "Enter a WiFi SSID.";
      return;
    }
    if (netStatus) netStatus.textContent = `Connecting to ${ssid}…`;
    try {
      const res = await control("wifi_connect", { ssid, password });
      if (!res.ok && res.error) throw new Error(res.error);
      if (netStatus) {
        netStatus.textContent = res.online
          ? `Online via WiFi ${ssid}`
          : `WiFi profile saved for ${ssid} — waiting for uplink`;
      }
      await openSettings();
    } catch (e) {
      if (netStatus) netStatus.textContent = `WiFi error: ${e.message}`;
    }
  });

  document.getElementById("actClaim")?.addEventListener("click", async () => {
    if (settingsBody) settingsBody.textContent = "Claiming USB free space…";
    try {
      const res = await control("usb_claim");
      if (settingsBody) {
        settingsBody.textContent = (res.stdout || JSON.stringify(res, null, 2)).slice(-1500);
      }
      await openSettings();
    } catch (e) {
      if (settingsBody) settingsBody.textContent = `Error: ${e.message}`;
    }
  });
  document.getElementById("actProbe")?.addEventListener("click", async () => {
    modelsBody.textContent = "Probing…";
    try {
      await control("model_probe");
      await openModels();
    } catch (e) {
      modelsBody.textContent = `Error: ${e.message}`;
    }
  });
  document.getElementById("actDownload")?.addEventListener("click", async () => {
    modelsBody.textContent = "Starting recommended download…";
    try {
      const st = await control("status");
      const id = st.probe?.recommend_id;
      const res = await control("model_download", id ? { id } : {});
      renderDownload(res.download || { state: "starting", id: id || "" });
      startDlPoll();
      await openModels();
    } catch (e) {
      modelsBody.textContent = `Error: ${e.message}`;
    }
  });
  document.getElementById("actRefresh")?.addEventListener("click", () => openModels());
  document.getElementById("actActivate")?.addEventListener("click", () => activateSelectedModel());
  document.getElementById("actModelDownload")?.addEventListener("click", () => downloadSelectedModel());
  document.getElementById("actModelDelete")?.addEventListener("click", () => openDeleteConfirm());
  document.getElementById("ctxSlider")?.addEventListener("input", (ev) => {
    const ctxValue = document.getElementById("ctxValue");
    if (ctxValue) ctxValue.textContent = String(ev.target.value);
  });
  document.getElementById("deleteConfirmCancel")?.addEventListener("click", () => {
    document.getElementById("deleteConfirmDialog")?.close();
  });
  document.getElementById("deleteConfirmOk")?.addEventListener("click", () => confirmDeleteSelected());
  document.getElementById("deleteConfirmInput")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      confirmDeleteSelected();
    }
  });

  addBubble(
    "system",
    "No model loads at boot. To chat: Models → radio select → context slider → Activate. Pair | URL above for LAN; Settings → System has How to connect. No LAN? Term: stickllm-wifi-setup."
  );
  refreshStatus();
  // Stick kiosk polls faster so LAN Pair remints show in chat promptly.
  setInterval(() => {
    refreshStatus();
  }, 2500);
  ensurePaired(false).then(async () => {
    try {
      const st = await pairStatus();
      if (st.local) applyLocalChrome(true);
    } catch (_) {}
  });
  const focusChat = () => {
    try {
      if (pairDialog?.open) return;
      if (modelsDialog?.open) return;
      if (settingsDialog?.open) return;
      input?.focus({ preventScroll: true });
    } catch (_) {
      input?.focus();
    }
  };
  focusChat();
  setTimeout(focusChat, 300);
  setTimeout(focusChat, 1200);
  window.addEventListener("focus", focusChat);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) focusChat();
  });
})();
