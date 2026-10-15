(() => {
  "use strict";

  // —— Fake data (production shapes) ——
  const CATALOG = [
    {
      id: "qwen25-7b-q5",
      name: "Qwen2.5-7B-Instruct-Q5_K_M",
      approx_size_gb: 5.2,
      source: "usb",
      installed: true,
      runnable: true,
      running: true,
      deletable: true,
      pinned: true,
      ctx_min: 2048,
      ctx_max: 8192,
      ctx_suggested: 8192,
      ctx_loaded: 8192,
      free_mem_after_gb: 18,
    },
    {
      id: "qwen25-3b-q4",
      name: "Qwen2.5-3B-Instruct-Q4_K_M",
      approx_size_gb: 1.9,
      source: "usb",
      installed: true,
      runnable: true,
      running: false,
      deletable: false,
      pinned: true,
      ctx_min: 2048,
      ctx_max: 16384,
      ctx_suggested: 8192,
      note: "baked-in",
    },
    {
      id: "qwen25-14b-q5",
      name: "Qwen2.5-14B-Instruct-Q5_K_M",
      approx_size_gb: 9.8,
      source: "catalog",
      installed: false,
      runnable: false,
      running: false,
      deletable: false,
      pinned: true,
      ctx_min: 2048,
      ctx_max: 8192,
      ctx_suggested: 4096,
    },
    {
      id: "host-gguf-mixtral",
      name: "Mixtral-8x7B (host SSD)",
      approx_size_gb: 26,
      source: "host_ssd",
      installed: true,
      runnable: true,
      running: false,
      deletable: false,
      pinned: false,
      ctx_min: 2048,
      ctx_max: 8192,
      ctx_suggested: 4096,
      free_mem_after_gb: 2,
      fits: false,
    },
  ];

  const DEVICES = [
    {
      kind: "host_ssd",
      label: "Fanxiang NVMe · models",
      mount_path: "/mnt/stickllm-host/nvme0n1p3",
      avail: "412G",
      selectable: true,
    },
    {
      kind: "usb_stick",
      label: "STICKLLM-DATA",
      mount_path: "/mnt/stickllm-data",
      avail: "28G",
      selectable: true,
      warn: "USB — data leaves with stick",
    },
    {
      kind: "blocked",
      label: "BitLocker volume",
      mount_path: "/dev/nvme0n1p2",
      selectable: false,
      warn: "encrypted — unlock in host OS",
    },
  ];

  const MOUNTABLE = [
    {
      kind: "host_ssd",
      device: "/dev/nvme0n1p4",
      label: "Clear ext4 SSD",
      size_gb: 500,
      fstype: "ext4",
      suggested_mount: "/mnt/stickllm-host/nvme0n1p4",
    },
  ];

  const FOLDERS = {
    "/mnt/stickllm-host/nvme0n1p3": [
      { name: "home", path: "/mnt/stickllm-host/nvme0n1p3/home" },
      { name: "opt", path: "/mnt/stickllm-host/nvme0n1p3/opt" },
    ],
    "/mnt/stickllm-host/nvme0n1p3/home": [
      { name: "nink", path: "/mnt/stickllm-host/nvme0n1p3/home/nink" },
    ],
    "/mnt/stickllm-host/nvme0n1p3/home/nink": [
      { name: "models", path: "/mnt/stickllm-host/nvme0n1p3/home/nink/models" },
      { name: "Documents", path: "/mnt/stickllm-host/nvme0n1p3/home/nink/Documents" },
    ],
    "/mnt/stickllm-host/nvme0n1p3/home/nink/models": [
      { name: "ollama", path: "/mnt/stickllm-host/nvme0n1p3/home/nink/models/ollama" },
      { name: "gguf", path: "/mnt/stickllm-host/nvme0n1p3/home/nink/models/gguf" },
    ],
    "/mnt/stickllm-data": [
      { name: "models", path: "/mnt/stickllm-data/models" },
    ],
  };

  const MODEL_HITS = [
    {
      path: "/mnt/stickllm-host/nvme0n1p3/home/nink/models",
      relative: "home/nink/models",
      gguf_count: 3,
      has_vault_blob: true,
      reason: "GGUF + stickllm-vault.img",
    },
    {
      path: "/mnt/stickllm-host/nvme0n1p3/home/nink/models/ollama",
      relative: "home/nink/models/ollama",
      gguf_count: 0,
      has_vault_blob: false,
      reason: "Ollama models/",
    },
  ];

  const SAVED_CHATS = [
    { id: "c1", title: "Explain LUKS blob layout", messages: 6 },
    { id: "c2", title: "VRAM probe for 3090", messages: 4 },
    { id: "c3", title: "WiFi bootstrap notes", messages: 2 },
  ];

  const MOVABLE = [
    { name: "Qwen2.5-7B-Instruct-Q5_K_M", size: 5.2e9, in_vault: false, path: "/mnt/stickllm-data/models/qwen…" },
    { name: "lite-3b (baked)", size: 1.9e9, in_vault: true, path: "/opt/…" },
  ];

  // —— State ——
  let mode = "ephemeral";
  let vaultUnlocked = false;
  let selectedModelId = "qwen25-7b-q5";
  let browsePath = "/mnt/stickllm-host/nvme0n1p3/home/nink/models";
  let selectedDevice = DEVICES[0];
  let hasBlob = true;
  let paired = true;
  let pairCode = "482917";
  let activeChatId = null;
  const messages = [];

  const $ = (id) => document.getElementById(id);
  const app = $("app");
  const drawer = $("drawer");
  const scrim = $("scrim");
  const thread = $("thread");
  const input = $("input");

  // —— Helpers ——
  function toast(text, kind = "system") {
    addBubble(kind, text);
  }

  function addBubble(role, text) {
    // Never append web-on / status spam to replies — constraint #1
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = role;
    el.appendChild(who);
    el.appendChild(document.createTextNode(text));
    thread.appendChild(el);
    thread.scrollTop = thread.scrollHeight;
    return el;
  }

  function setFeedback(msg, kind = "info") {
    const el = $("vaultFeedback");
    if (!el) return;
    el.textContent = msg || "";
    el.classList.remove("is-ok", "is-err");
    if (kind === "ok") el.classList.add("is-ok");
    if (kind === "err") el.classList.add("is-err");
  }

  function locLabel(m) {
    if (m.source === "host_ssd") return "SSD";
    if (!m.installed) return mode === "vault" ? "SSD" : "USB";
    return m.source === "usb" ? "USB" : "USB";
  }

  function statusLabel(m) {
    if (m.running) return "Running";
    if (m.installed) return "Downloaded";
    return "Not downloaded";
  }

  // —— Drawer / panels ——
  function openDrawer() {
    app.classList.add("drawer-open");
    $("menuBtn")?.classList.add("is-open");
    if (scrim) scrim.hidden = false;
  }
  function closeDrawer() {
    app.classList.remove("drawer-open");
    $("menuBtn")?.classList.remove("is-open");
    if (scrim) scrim.hidden = true;
  }
  function toggleDrawer() {
    if (app.classList.contains("drawer-open")) closeDrawer();
    else openDrawer();
  }

  function closeAllPanels() {
    document.querySelectorAll(".sheet").forEach((s) => {
      s.hidden = true;
    });
  }

  function openPanel(name) {
    closeDrawer();
    closeAllPanels();
    const panel = $(`panel-${name}`);
    if (!panel) return;
    if (name === "chats" && mode !== "vault") {
      toast("Switch Mode to Vault to use saved chats.");
      return;
    }
    panel.hidden = false;
    if (name === "models") renderCatalog();
    if (name === "vault") {
      renderDevices();
      renderFolders();
    }
    if (name === "chats") renderChats();
  }

  // —— Mode ——
  function applyMode(next) {
    const prev = mode;
    if (next === "vault" && !vaultUnlocked) {
      toast("Vault is locked — open Vault → Unlock (or create/attach first).");
      openPanel("vault");
      switchVtab("unlock");
      // Keep UI preview on vault but don't claim unlocked
      mode = "vault";
    } else {
      mode = next;
    }
    document.querySelectorAll(".modeBtn").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.mode === mode);
    });
    const badge = $("modeBadge");
    if (badge) {
      badge.textContent = mode === "vault" ? "Vault" : "Ephemeral";
      badge.classList.toggle("is-vault", mode === "vault");
    }
    const chatsNav = $("navChats");
    if (chatsNav) {
      chatsNav.disabled = mode !== "vault";
      chatsNav.title = mode === "vault" ? "Saved chats" : "Switch Mode to Vault";
    }
    const lockBtn = $("navLock");
    const lockChrome = $("lockChrome");
    const canLock = vaultUnlocked;
    if (lockBtn) {
      lockBtn.disabled = !canLock;
      lockBtn.title = canLock ? "Lock vault (Ctrl+Shift+L)" : "Unlock vault first";
    }
    if (lockChrome) {
      lockChrome.disabled = !canLock;
    }
    const hint = $("sessionHint");
    if (hint) {
      hint.textContent =
        mode === "vault"
          ? vaultUnlocked
            ? "Vault mode — chats/settings in encrypted blob"
            : "Vault mode selected — unlock required"
          : "Ephemeral — no SSD vault writes";
    }
    if (next === "ephemeral" && prev === "vault") {
      toast("Ephemeral mode — no SSD vault writes. Use Lock to close LUKS.");
    } else if (next === "vault" && vaultUnlocked) {
      toast("Vault mode — models use your SSD models folder; chats stay in the vault.");
    }
  }

  function lockVault() {
    if (!vaultUnlocked) {
      toast("Vault already locked.");
      return;
    }
    vaultUnlocked = false;
    $("vaultStatus").textContent =
      "Vault: locked · wipe-after-N off · file-blob only — never formats your drive";
    setFeedback("Vault locked — model unloaded.", "ok");
    toast("Vault locked — model unloaded.");
    if (mode === "vault") applyMode("ephemeral");
    else applyMode(mode);
  }

  function unlockVault() {
    const pass = $("vaultPass")?.value || "";
    if (pass.length < 4) {
      setFeedback("Enter vault passcode.", "err");
      return;
    }
    vaultUnlocked = true;
    $("vaultPass").value = "";
    $("vaultStatus").textContent =
      "Vault: unlocked · mounted at /var/lib/stickllm/vault · wipe-after-N off";
    setFeedback("Vault unlocked.", "ok");
    toast("Vault unlocked.");
    applyMode("vault");
  }

  // —— Models ——
  function renderCatalog() {
    const list = $("catalog");
    if (!list) return;
    list.innerHTML = "";
    const m = CATALOG.find((x) => x.id === selectedModelId) || CATALOG[0];
    selectedModelId = m.id;

    for (const model of CATALOG) {
      const row = document.createElement("label");
      row.className = "catalogRow" + (model.id === selectedModelId ? " is-selected" : "");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "catalogModel";
      radio.value = model.id;
      radio.checked = model.id === selectedModelId;
      radio.addEventListener("change", () => {
        selectedModelId = model.id;
        renderCatalog();
      });
      const meta = document.createElement("div");
      meta.className = "catalogMeta";
      meta.innerHTML = `<span class="catalogTitle">${model.name}</span>
        <span class="catalogDetail">${model.approx_size_gb} GB · ${locLabel(model)} · ${statusLabel(model)}${model.note ? " · " + model.note : ""}</span>`;
      row.appendChild(radio);
      row.appendChild(meta);
      list.appendChild(row);
    }
    updateSelectionPanel();
  }

  function updateSelectionPanel() {
    const m = CATALOG.find((x) => x.id === selectedModelId);
    const ctxPanel = $("ctxPanel");
    const dlBtn = $("actModelDl");
    const delBtn = $("actModelDel");
    const hint = $("manageHint");
    const activate = $("actActivate");
    const slider = $("ctxSlider");
    const ctxValue = $("ctxValue");
    const ctxMeta = $("ctxMeta");

    if (!m) return;

    if (hint) {
      const bits = [];
      if (m.fits === false) bits.push("won't fit VRAM comfortably");
      if (m.source === "host_ssd") bits.push("host SSD (delete in host OS)");
      if (m.note) bits.push(m.note);
      hint.textContent = bits.join(" · ");
      hint.hidden = !bits.length;
    }
    if (dlBtn) {
      dlBtn.hidden = !(m.pinned && !m.installed);
    }
    if (delBtn) {
      delBtn.hidden = !m.deletable;
    }

    if (m.runnable && ctxPanel && slider) {
      ctxPanel.hidden = false;
      const lo = m.ctx_min || 2048;
      const hi = m.ctx_max || 8192;
      slider.min = String(lo);
      slider.max = String(hi);
      slider.step = hi <= 8192 ? "1024" : "2048";
      if (slider.dataset.modelId !== m.id) {
        slider.value = String(m.ctx_loaded || m.ctx_suggested || lo);
        slider.dataset.modelId = m.id;
      }
      if (ctxValue) ctxValue.textContent = slider.value;
      if (ctxMeta) {
        ctxMeta.textContent = [
          `Slider range ${lo}–${hi} tokens`,
          m.ctx_loaded ? `loaded ${m.ctx_loaded}` : null,
          m.free_mem_after_gb != null ? `~${m.free_mem_after_gb} GB free after load` : null,
        ]
          .filter(Boolean)
          .join(" · ");
      }
      if (activate) {
        const same = m.running && Number(slider.value) === Number(m.ctx_loaded);
        activate.disabled = same;
        activate.textContent = same
          ? "Running"
          : m.running
            ? "Reload with context"
            : "Activate selected";
      }
    } else if (ctxPanel) {
      ctxPanel.hidden = true;
    }
  }

  function simulateDownload(name) {
    const prog = $("dlProgress");
    const fill = $("dlFill");
    const label = $("dlLabel");
    const meta = $("dlMeta");
    if (!prog) return;
    prog.hidden = false;
    let pct = 0;
    label.textContent = `Downloading ${name}…`;
    const t = setInterval(() => {
      pct += 12;
      if (pct >= 100) {
        clearInterval(t);
        fill.style.width = "100%";
        label.textContent = `Downloaded: ${name}`;
        meta.textContent = "Complete — hash verified";
        toast(`Model download complete: ${name}`);
        return;
      }
      fill.style.width = `${pct}%`;
      meta.textContent = `${pct}% · mock progress`;
    }, 280);
  }

  // —— Vault ——
  function renderDevices() {
    const list = $("deviceList");
    if (!list) return;
    list.innerHTML = "";
    for (const d of DEVICES) {
      const row = document.createElement("div");
      row.className =
        "pickRow" +
        (selectedDevice?.mount_path === d.mount_path ? " is-selected" : "");
      const kind = document.createElement("span");
      kind.className = `kind ${d.kind}`;
      kind.textContent =
        d.kind === "host_ssd" ? "SSD" : d.kind === "usb_stick" ? "Stick USB" : "Blocked";
      const text = document.createElement("span");
      text.textContent = `${d.label}${d.avail ? " · free " + d.avail : ""}`;
      row.appendChild(kind);
      row.appendChild(text);
      if (d.selectable) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "actionBtn";
        btn.textContent = "Open";
        btn.addEventListener("click", () => {
          selectedDevice = d;
          browsePath =
            d.kind === "host_ssd"
              ? "/mnt/stickllm-host/nvme0n1p3/home/nink/models"
              : d.mount_path;
          const warn = $("usbWarn");
          if (warn) {
            if (d.kind === "usb_stick") {
              warn.hidden = false;
              warn.textContent = d.warn || "USB selected — prefer host SSD.";
            } else {
              warn.hidden = true;
            }
          }
          renderDevices();
          renderFolders();
          setFeedback(`Opened ${d.label}`, "ok");
        });
        row.appendChild(btn);
      } else {
        const why = document.createElement("span");
        why.className = "muted";
        why.textContent = d.warn || "don't touch";
        row.appendChild(why);
      }
      list.appendChild(row);
    }
    for (const m of MOUNTABLE) {
      const row = document.createElement("div");
      row.className = "pickRow";
      const kind = document.createElement("span");
      kind.className = `kind ${m.kind}`;
      kind.textContent = "SSD · unmounted";
      const text = document.createElement("span");
      text.textContent = `${m.label} · ${m.size_gb} GiB`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "actionBtn";
      btn.textContent = "Mount";
      btn.addEventListener("click", () => {
        if (!confirm(`Mount ${m.device} (${m.fstype}, ${m.size_gb} GiB) under ${m.suggested_mount}?\n\nNever formats.`)) {
          setFeedback("Mount cancelled.", "info");
          return;
        }
        setFeedback(`Mounted ${m.device} at ${m.suggested_mount}. Browse to your models folder.`, "ok");
        toast(`Mounted host volume ${m.device}`);
        browsePath = m.suggested_mount;
        renderFolders();
      });
      row.appendChild(kind);
      row.appendChild(text);
      row.appendChild(btn);
      list.appendChild(row);
    }
  }

  function renderFolders() {
    const pathEl = $("browsePath");
    const folderList = $("folderList");
    const blobHint = $("blobHint");
    const openExisting = $("actOpenExisting");
    if (pathEl) pathEl.textContent = browsePath;
    hasBlob = browsePath.includes("/models") && !browsePath.includes("ollama");
    if (blobHint) {
      blobHint.hidden = !hasBlob;
      if (hasBlob) {
        blobHint.textContent = `Found existing vault blob: ${browsePath}/stickllm-vault.img — Open existing, then Unlock.`;
      }
    }
    if (openExisting) openExisting.disabled = !hasBlob;
    if ($("vaultPath")) $("vaultPath").value = browsePath;

    if (!folderList) return;
    folderList.innerHTML = "";
    if (hasBlob) {
      const blobRow = document.createElement("div");
      blobRow.className = "pickRow";
      blobRow.textContent = "stickllm-vault.img (existing encrypted vault) ";
      const bind = document.createElement("button");
      bind.type = "button";
      bind.className = "actionBtn";
      bind.textContent = "Open existing";
      bind.addEventListener("click", () => attachExisting());
      blobRow.appendChild(bind);
      folderList.appendChild(blobRow);
    }
    const entries = FOLDERS[browsePath] || [];
    if (!entries.length && !hasBlob) {
      folderList.textContent = "(no subfolders — Use this folder or New folder)";
    }
    for (const ent of entries) {
      const row = document.createElement("div");
      row.className = "pickRow";
      row.appendChild(document.createTextNode(ent.name + " "));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "actionBtn";
      btn.textContent = "Open";
      btn.addEventListener("click", () => {
        browsePath = ent.path;
        renderFolders();
      });
      row.appendChild(btn);
      folderList.appendChild(row);
    }
  }

  function attachExisting() {
    setFeedback(
      `Existing vault attached: ${browsePath}/stickllm-vault.img. Enter passcode and Unlock — CREATE-VAULT not needed.`,
      "ok"
    );
    toast(`Existing vault attached at ${browsePath}/stickllm-vault.img`);
    switchVtab("unlock");
    $("vaultPass")?.focus();
  }

  function switchVtab(name) {
    document.querySelectorAll("[data-vtab]").forEach((t) => {
      t.classList.toggle("is-on", t.dataset.vtab === name);
    });
    ["storage", "unlock", "create", "advanced"].forEach((id) => {
      const el = $(`vtab-${id}`);
      if (el) el.hidden = id !== name;
    });
  }

  function switchStab(name) {
    document.querySelectorAll("[data-stab]").forEach((t) => {
      t.classList.toggle("is-on", t.dataset.stab === name);
    });
    ["network", "system"].forEach((id) => {
      const el = $(`stab-${id}`);
      if (el) el.hidden = id !== name;
    });
  }

  // —— Chats ——
  function renderChats() {
    const list = $("chatsList");
    if (!list) return;
    list.innerHTML = "";
    for (const c of SAVED_CHATS) {
      const row = document.createElement("div");
      row.className = "catalogRow";
      const meta = document.createElement("div");
      meta.className = "catalogMeta";
      meta.innerHTML = `<span class="catalogTitle">${c.title}</span>
        <span class="catalogDetail">${c.messages} msgs · ${c.id}</span>`;
      const actions = document.createElement("div");
      actions.className = "catalogActions";
      const open = document.createElement("button");
      open.type = "button";
      open.className = "actionBtn";
      open.textContent = "Open";
      open.addEventListener("click", () => {
        activeChatId = c.id;
        thread.innerHTML = "";
        addBubble("system", `Opened saved chat “${c.title}”.`);
        addBubble("user", "(restored user message)");
        addBubble("assistant", "(restored assistant reply — mock)");
        closeAllPanels();
      });
      const del = document.createElement("button");
      del.type = "button";
      del.className = "actionBtn";
      del.textContent = "Delete";
      del.addEventListener("click", () => {
        if (!confirm(`Delete chat “${c.title}”?`)) return;
        toast(`Deleted chat “${c.title}” (mock).`);
        renderChats();
      });
      actions.appendChild(open);
      actions.appendChild(del);
      row.appendChild(meta);
      row.appendChild(actions);
      list.appendChild(row);
    }
  }

  function newChat() {
    activeChatId = null;
    thread.innerHTML = "";
    addBubble(
      "system",
      "No model loads at boot. To chat: Models → radio select → context slider → Activate. Pair | URL above for LAN."
    );
    toast("New chat (not saved until you Save).");
    closeAllPanels();
  }

  // —— Chat send (no web-on spam) ——
  function sendChat(text) {
    addBubble("user", text);
    const webOn = $("webToggle")?.checked;
    // Reply content only — never "web on" status line in the bubble
    const reply = webOn
      ? "Mock reply. (Web lookup would run server-side when needed; sources appear only if used — no per-message “web on” badge.)"
      : "Mock reply with web lookup off — local model only.";
    setTimeout(() => addBubble("assistant", reply), 280);
  }

  // —— Wire UI ——
  $("menuBtn")?.addEventListener("click", toggleDrawer);
  scrim?.addEventListener("click", closeDrawer);

  document.querySelectorAll("[data-panel]").forEach((btn) => {
    btn.addEventListener("click", () => openPanel(btn.dataset.panel));
  });
  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", closeAllPanels);
  });

  document.querySelectorAll(".modeBtn").forEach((btn) => {
    btn.addEventListener("click", () => applyMode(btn.dataset.mode));
  });

  document.querySelectorAll("[data-vtab]").forEach((btn) => {
    btn.addEventListener("click", () => switchVtab(btn.dataset.vtab));
  });
  document.querySelectorAll("[data-stab]").forEach((btn) => {
    btn.addEventListener("click", () => switchStab(btn.dataset.stab));
  });

  $("navNewChat")?.addEventListener("click", () => {
    closeDrawer();
    newChat();
  });
  $("actChatNew")?.addEventListener("click", newChat);
  $("actChatSave")?.addEventListener("click", () => {
    if (mode !== "vault") {
      toast("Switch Mode to Vault to save chats.");
      return;
    }
    toast("Saved chat in vault (mock).");
  });

  $("navLock")?.addEventListener("click", lockVault);
  $("lockChrome")?.addEventListener("click", lockVault);
  $("actLockVault")?.addEventListener("click", lockVault);
  $("actUnlock")?.addEventListener("click", unlockVault);

  window.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey && ev.shiftKey && (ev.key === "L" || ev.key === "l")) {
      ev.preventDefault();
      lockVault();
    }
  });

  // Models actions
  $("actProbe")?.addEventListener("click", () => {
    $("modelsStatus").textContent =
      "Backend: CUDA · VRAM ~24 GB\nOptimum: Qwen2.5-7B-Instruct-Q5_K_M (~5.2 GB)\nProbe refreshed (mock)\nModels: /mnt/stickllm-data/models";
    toast("VRAM probe complete — optimum highlighted.");
  });
  $("actDownloadRec")?.addEventListener("click", () => {
    simulateDownload("Qwen2.5-7B-Instruct-Q5_K_M");
  });
  $("actRefreshModels")?.addEventListener("click", () => {
    renderCatalog();
    toast("Catalog refreshed.");
  });
  $("ctxSlider")?.addEventListener("input", (ev) => {
    if ($("ctxValue")) $("ctxValue").textContent = ev.target.value;
    updateSelectionPanel();
  });
  $("actActivate")?.addEventListener("click", () => {
    const m = CATALOG.find((x) => x.id === selectedModelId);
    const ctx = $("ctxSlider")?.value;
    CATALOG.forEach((x) => {
      x.running = x.id === selectedModelId;
      if (x.running) x.ctx_loaded = Number(ctx);
    });
    $("stModel").textContent = `${m?.name || "model"} · CUDA`;
    $("modelsStatus").textContent = `Now running: ${m?.name} · ctx ${ctx}`;
    renderCatalog();
    toast(`Activated ${m?.name} (ctx ${ctx}).`);
  });
  $("actModelDl")?.addEventListener("click", () => {
    const m = CATALOG.find((x) => x.id === selectedModelId);
    if (m) simulateDownload(m.name);
  });
  $("actModelDel")?.addEventListener("click", () => {
    const m = CATALOG.find((x) => x.id === selectedModelId);
    if (!m?.deletable) return;
    $("deleteBody").innerHTML = `Permanently delete downloaded files for <strong>${m.name}</strong>? Type <strong>ARE YOU SURE</strong> to confirm.`;
    $("deleteConfirmInput").value = "";
    $("deleteErr").hidden = true;
    $("deleteDialog").showModal();
  });
  $("deleteCancel")?.addEventListener("click", () => $("deleteDialog").close());
  $("deleteOk")?.addEventListener("click", () => {
    const typed = ($("deleteConfirmInput")?.value || "").trim();
    if (typed !== "ARE YOU SURE") {
      $("deleteErr").hidden = false;
      $("deleteErr").textContent = "Type ARE YOU SURE exactly (all caps) to delete.";
      return;
    }
    const m = CATALOG.find((x) => x.id === selectedModelId);
    toast(`Deleted ${m?.id} (mock).`);
    $("deleteDialog").close();
  });

  // Vault actions
  $("actClaim")?.addEventListener("click", () => {
    setFeedback("USB free space claimed → STICKLLM-DATA (mock).", "ok");
    toast("Claimed USB free space.");
  });
  $("actListStorage")?.addEventListener("click", () => {
    setFeedback("Storage list refreshed (read-only probe).", "ok");
  });
  $("actVaultRefresh")?.addEventListener("click", () => {
    renderDevices();
    renderFolders();
    setFeedback("Vault panel refreshed.", "ok");
  });
  $("actDevRefresh")?.addEventListener("click", () => {
    renderDevices();
    setFeedback("Devices refreshed.", "ok");
  });
  $("actBrowseUp")?.addEventListener("click", () => {
    const parts = browsePath.replace(/\/$/, "").split("/");
    if (parts.length > 3) {
      parts.pop();
      browsePath = parts.join("/") || "/";
      renderFolders();
    }
  });
  $("actUseFolder")?.addEventListener("click", () => {
    if ($("vaultPath")) $("vaultPath").value = browsePath;
    setFeedback(`Selected folder ${browsePath}`, hasBlob ? "ok" : "ok");
  });
  $("actOpenExisting")?.addEventListener("click", attachExisting);
  $("actNewFolder")?.addEventListener("click", () => {
    const name = prompt("New folder name:", "StickLLM");
    if (!name) return;
    setFeedback(`Created folder ${browsePath}/${name.trim()} (mock)`, "ok");
  });
  $("actFindModels")?.addEventListener("click", () => {
    const hits = $("modelHits");
    if (!hits) return;
    hits.hidden = false;
    hits.innerHTML = "";
    const head = document.createElement("div");
    head.className = "muted";
    head.style.fontSize = "0.75rem";
    head.textContent = `Found ${MODEL_HITS.length} location(s)`;
    hits.appendChild(head);
    for (const hit of MODEL_HITS) {
      const row = document.createElement("div");
      row.className = "pickRow";
      row.textContent = `${hit.relative} · ${hit.gguf_count} GGUF${hit.has_vault_blob ? " · vault blob" : ""} — ${hit.reason} `;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "actionBtn";
      btn.textContent = hit.has_vault_blob ? "Open + use vault" : "Open";
      btn.addEventListener("click", () => {
        browsePath = hit.path;
        renderFolders();
        if (hit.has_vault_blob) attachExisting();
      });
      row.appendChild(btn);
      hits.appendChild(row);
    }
    setFeedback("Best match: home/nink/models (GGUF + vault blob).", "ok");
  });
  $("actFindVault")?.addEventListener("click", () => {
    browsePath = "/mnt/stickllm-host/nvme0n1p3/home/nink/models";
    renderFolders();
    setFeedback("Found vault (USB DATA pointer): attaching…", "ok");
    attachExisting();
  });
  $("actCreateVault")?.addEventListener("click", () => {
    const confirm = ($("vaultCreateConfirm")?.value || "").trim();
    const p1 = $("vaultPassNew")?.value || "";
    const p2 = $("vaultPassNew2")?.value || "";
    if (confirm !== "CREATE-VAULT") {
      setFeedback("Type CREATE-VAULT exactly to confirm.", "err");
      return;
    }
    if (p1.length < 8 || p1 !== p2) {
      setFeedback("Passcode must match and be at least 8 characters.", "err");
      return;
    }
    const recovery = $("recoveryPhrase");
    recovery.hidden = false;
    recovery.textContent =
      "RECOVERY PHRASE (shown once — write it down):\nlinden maple cedar birch willow aspen pine spruce oak elm fir yew";
    $("savedLabel").hidden = false;
    $("actFinishSetup").hidden = false;
    setFeedback("Success — vault created. Write the recovery phrase, type SAVED, then Finish.", "ok");
    toast("Vault created — write down the recovery phrase.");
  });
  $("actFinishSetup")?.addEventListener("click", () => {
    if (($("vaultSaved")?.value || "").trim() !== "SAVED") {
      setFeedback("Type SAVED after writing the recovery phrase.", "err");
      return;
    }
    $("recoveryPhrase").textContent = "(recovery phrase cleared from this screen)";
    $("savedLabel").hidden = true;
    $("actFinishSetup").hidden = true;
    vaultUnlocked = true;
    setFeedback("Recovery phrase acknowledged. Keep your written copy safe.", "ok");
    applyMode("vault");
  });
  $("actGrow")?.addEventListener("click", () => {
    const gb = $("vaultGrowGb")?.value || "8";
    const typed = prompt(`Type GROW-VAULT to expand the blob by ${gb} GiB:`, "");
    if (typed !== "GROW-VAULT") {
      toast("Grow aborted.");
      return;
    }
    toast(`Vault grew by ${gb} GiB (mock).`);
  });
  $("actWipe")?.addEventListener("click", () => {
    const n = $("vaultWipeN")?.value || "0";
    if (n !== "0") {
      const c = prompt(`Type WIPE-OK to enable wipe after ${n} failed unlocks:`, "");
      if (c !== "WIPE-OK") {
        toast("Wipe setting aborted.");
        return;
      }
    }
    toast(`Wipe-after-N set to ${n} (mock).`);
  });
  $("actMovable")?.addEventListener("click", () => {
    const el = $("movableList");
    if (!el) return;
    el.innerHTML = "";
    for (const m of MOVABLE) {
      const line = document.createElement("div");
      line.textContent = `${m.name}  ${(m.size / 1e9).toFixed(1)} GB${m.in_vault ? " (already in vault)" : ""} `;
      if (!m.in_vault) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "actionBtn";
        btn.textContent = "Move → vault";
        btn.addEventListener("click", () => {
          if (!confirm(`Move ${m.name} into vault?`)) return;
          toast(`Moved ${m.name} into vault (SHA-256 OK, mock).`);
        });
        line.appendChild(btn);
      }
      el.appendChild(line);
    }
  });

  // Pair
  $("actPairSubmit")?.addEventListener("click", () => {
    const code = ($("pairCode")?.value || "").trim();
    if (!/^\d{4,8}$/.test(code)) {
      $("pairErr").hidden = false;
      $("pairErr").textContent = "Enter the 6-digit code from the stick screen.";
      return;
    }
    $("pairErr").hidden = true;
    paired = true;
    toast("Paired. Chat, Models, and Settings unlocked until reboot.");
    closeAllPanels();
  });
  $("actRemint")?.addEventListener("click", () => {
    pairCode = String(Math.floor(100000 + Math.random() * 900000));
    $("pairDisplayCode").textContent = pairCode;
    $("stPair").textContent = pairCode;
    toast(
      `New PAIR CODE: ${pairCode} — open the URL on phone/desktop and enter this code. Previous paired browsers were unpaired.`
    );
  });

  // WiFi
  $("actWifi")?.addEventListener("click", () => {
    const ssid = ($("wifiSsid")?.value || "").trim();
    if (!ssid) {
      $("netStatus").textContent = "Enter a WiFi SSID.";
      return;
    }
    $("netStatus").textContent = `Online via WiFi ${ssid} (mock)`;
    $("stUplink").textContent = "online";
    toast(`WiFi profile saved for ${ssid}.`);
  });

  // Composer
  $("composer")?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = (input?.value || "").trim();
    if (!text) return;
    input.value = "";
    sendChat(text);
  });
  input?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      $("composer")?.requestSubmit();
    }
  });

  // Escape closes sheet
  window.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      closeAllPanels();
      closeDrawer();
    }
  });

  // Boot
  applyMode("ephemeral");
  renderCatalog();
  renderDevices();
  renderFolders();
  addBubble(
    "system",
    "No model loads at boot. To chat: Models → radio select → context slider → Activate. Pair | URL above for LAN. Vault is a first-class panel (Mount SSD / create / unlock / find) — not at boot."
  );
  addBubble("assistant", "Mockup is interactive — open the menu for Models, Vault, Pair, and Settings. Attach and mic are reserved.");
  input?.focus();
})();
