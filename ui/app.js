(() => {
  const log = document.getElementById("log");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const statusLine = document.getElementById("statusLine");
  const modeBadge = document.getElementById("modeBadge");
  const apiHint = document.getElementById("apiHint");
  const webToggle = document.getElementById("webToggle");
  const modelsBtn = document.getElementById("modelsBtn");
  const settingsBtn = document.getElementById("settingsBtn");
  const pairBtn = document.getElementById("pairBtn");
  const modelsDialog = document.getElementById("modelsDialog");
  const settingsDialog = document.getElementById("settingsDialog");
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
    // On-stick Chat UI: hide Pair button (loopback needs no pair), keep connect banner.
    if (pairBtn) pairBtn.hidden = isLocalMode;
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
      const placeholder = !name || /^loading/i.test(name) || name === "…";
      if (j.llama_ok) {
        if (placeholder) {
          const path = (c.model_path || "").trim();
          name = path ? path.split(/[/\\]/).pop() : "ready";
        }
        connectModel.textContent = name;
      } else {
        connectModel.textContent = placeholder ? "loading…" : `${name} (loading)`;
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
      const modelBit = j.llama_ok
        ? modelName
          ? `model ready · ${modelName}${backendBit}`
          : `model ready${backendBit}`
        : modelName
          ? `model loading · ${modelName}${backendBit}`
          : `model loading${backendBit}`;
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
      try {
        const m = await fetch("/stickllm.json", { cache: "no-store" });
        if (m.ok) {
          const meta = await m.json();
          if (meta.mode) modeBadge.textContent = meta.mode;
          if (meta.version) modeBadge.title = `v${meta.version}`;
          const mode = String(meta.mode || "").toLowerCase();
          if (mode === "local" || mode === "chat") {
            applyLocalChrome(true);
          }
        }
      } catch (_) {}
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
      p.dest ? `Download dest: ${p.dest}` : "",
    ].filter(Boolean);
    modelsBody.textContent = lines.join("\n");
    renderDownload(j.download || {});
  }

  function renderSettingsStatus(j) {
    const s = j.storage || {};
    const backend = String(j.backend || "cpu").toUpperCase();
    const lines = [
      `Backend: ${backend}`,
      s.mounted
        ? `USB DATA: mounted (${s.free_gb ?? "?"} GiB free)`
        : `USB DATA: ${s.note || "not claimed"}`,
      j.online ? "Uplink: online" : "Uplink: none (Ethernet or console WiFi first)",
    ];
    if (settingsBody) settingsBody.textContent = lines.join("\n");
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

  function renderCatalog(models) {
    catalogList.innerHTML = "";
    if (!models?.length) {
      catalogList.textContent = "No catalog entries.";
      return;
    }
    for (const m of models) {
      const row = document.createElement("div");
      row.className = "catalogRow";
      const meta = document.createElement("div");
      const flags = [
        m.running ? "RUNNING" : m.active ? "LOADING" : null,
        m.installed ? "downloaded" : "not downloaded",
        m.fits ? null : m.fit_note || `needs ${m.min_vram_gb}GB`,
        m.backend === "cpu" ? "CPU" : null,
        m.vision ? "vision" : null,
        m.pinned ? null : "not pinned",
      ]
        .filter(Boolean)
        .join(" · ");
      meta.innerHTML = `<strong>${m.name}</strong><br/><span class="muted">${m.id} · ~${m.approx_size_gb} GB · ${flags}</span>`;

      const actions = document.createElement("div");
      actions.className = "catalogActions";

      if (m.runnable) {
        const runBtn = document.createElement("button");
        runBtn.type = "button";
        runBtn.className = "actionBtn";
        runBtn.textContent = m.running ? "Running" : m.active ? "Loading…" : "Use this";
        runBtn.disabled = !!m.running;
        runBtn.addEventListener("click", async () => {
          runBtn.disabled = true;
          runBtn.textContent = "Loading…";
          try {
            modelsBody.textContent = `Loading model ${m.name || m.id}…`;
            const res = await control("model_activate", { id: m.id });
            if (!res.ok && res.error) throw new Error(res.error);
            modelsBody.textContent = res.running
              ? `Now running: ${res.name || res.active_model || m.id}`
              : `Loading: ${res.name || m.id} — waiting for /health`;
            await openModels();
          } catch (e) {
            modelsBody.textContent = `Error: ${e.message}`;
            runBtn.disabled = false;
            runBtn.textContent = "Use this";
          }
        });
        actions.appendChild(runBtn);
      }

      if (m.pinned && !m.installed) {
        const dlBtn = document.createElement("button");
        dlBtn.type = "button";
        dlBtn.className = "actionBtn";
        dlBtn.textContent = "Download";
        dlBtn.addEventListener("click", async () => {
          dlBtn.disabled = true;
          dlBtn.textContent = "Downloading…";
          try {
            modelsBody.textContent = `Starting download: ${m.id}…`;
            const res = await control("model_download", { id: m.id });
            renderDownload(res.download || { state: "starting", id: m.id, name: m.name });
            startDlPoll();
            await openModels();
          } catch (e) {
            modelsBody.textContent = `Error: ${e.message}`;
            dlBtn.disabled = false;
            dlBtn.textContent = "Download";
          }
        });
        actions.appendChild(dlBtn);
      } else if (!m.pinned && !m.installed) {
        const na = document.createElement("button");
        na.type = "button";
        na.className = "actionBtn";
        na.textContent = "Unavailable";
        na.disabled = true;
        actions.appendChild(na);
      } else if (m.installed && !m.fits) {
        const na = document.createElement("button");
        na.type = "button";
        na.className = "actionBtn";
        na.textContent = m.backend === "cpu" ? "Won't fit RAM" : "Won't fit VRAM";
        na.disabled = true;
        actions.appendChild(na);
      }

      if (m.deletable) {
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "actionBtn";
        delBtn.textContent = "Delete";
        delBtn.addEventListener("click", async () => {
          if (!confirm(`Delete downloaded files for ${m.name || m.id}?`)) return;
          delBtn.disabled = true;
          try {
            const res = await control("model_delete", { id: m.id });
            if (!res.ok && res.error) throw new Error(res.error);
            modelsBody.textContent = `Deleted ${m.id}`;
            await openModels();
          } catch (e) {
            modelsBody.textContent = `Error: ${e.message}`;
            delBtn.disabled = false;
          }
        });
        actions.appendChild(delBtn);
      }

      row.appendChild(meta);
      row.appendChild(actions);
      catalogList.appendChild(row);
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
    } catch (e) {
      if (settingsBody) settingsBody.textContent = `Could not load: ${e.message}`;
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

  modelsBtn?.addEventListener("click", () => openModels());
  settingsBtn?.addEventListener("click", () => openSettings());
  pairBtn?.addEventListener("click", () => ensurePaired(true));
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

  addBubble(
    "system",
    "StickLLM v0.3.1 — Pair | URL | Model above. Settings → System has How to connect. Models = catalog; Settings = WiFi / USB / backend. No LAN? Term: stickllm-wifi-setup."
  );
  refreshStatus();
  setInterval(refreshStatus, 8000);
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
