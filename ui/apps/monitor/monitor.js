/* External script: the gateway CSP is script-src 'self' and blocks inline scripts.
   0.5.9 monitor cleanup: SVG arc gauges, 60 s sparklines, every drive, real card
   names, and "holds the model" only while the service runs. No libraries, no fetches
   beyond /api/system (the stick is offline-first). */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StickMonitor = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const POLL_MS = 2000;
  const HISTORY = 30; // 30 samples x 2 s = last ~60 s
  const SVGNS = "http://www.w3.org/2000/svg";

  function n(v) { return typeof v === "number" && Number.isFinite(v); }

  function gb(v) {
    if (!n(v)) return "—";
    return (v / (1024 * 1024 * 1024)).toFixed(1) + " GB";
  }

  function gbt(v) {
    if (!n(v)) return "—";
    const g = v / (1024 * 1024 * 1024);
    return g >= 1000 ? (g / 1024).toFixed(1) + " TB" : g >= 100 ? Math.round(g) + " GB" : g.toFixed(1) + " GB";
  }

  // Card titles drop the vendor marketing prefix; the full name stays in the tooltip.
  function shortName(name) {
    return String(name || "GPU").replace(/^NVIDIA\s+(GeForce\s+)?/i, "").replace(/^AMD\s+/i, "") || "GPU";
  }

  function size(v) {
    if (!n(v)) return "—";
    const g = v / 1e9;
    return g >= 1000 ? (g / 1000).toFixed(g >= 10000 ? 0 : 1) + " TB" : g >= 10 ? Math.round(g) + " GB" : g.toFixed(1) + " GB";
  }

  function pct(used, total) {
    return n(used) && n(total) && total > 0 ? Math.max(0, Math.min(100, (100 * used) / total)) : null;
  }

  /* Colour bands: temperature green < 70 °C, amber < 83 °C, red above.
     Load: accent below 85 %, amber below 95 %, red above. */
  function tempTone(c) { return !n(c) ? "dim" : c >= 83 ? "red" : c >= 70 ? "amber" : "green"; }
  function loadTone(p) { return !n(p) ? "dim" : p >= 95 ? "red" : p >= 85 ? "amber" : "accent"; }

  function uptime(s) {
    if (!n(s)) return "";
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return (d ? d + "d " : "") + (d || h ? h + "h " : "") + m + "m";
  }

  // ---- history (sparklines) -------------------------------------------------
  const history = {};
  function pushHistory(key, value) {
    const row = history[key] || (history[key] = []);
    row.push(n(value) ? value : null);
    while (row.length > HISTORY) row.shift();
    return row;
  }
  function getHistory(key) { return history[key] || []; }

  // ---- view model ------------------------------------------------------------
  function cpuCard(cpu, host) {
    const row = cpu || {};
    const h = host || {};
    if (!row.available) return { title: "CPU", kind: "cpu", lines: [{ text: row.message || "CPU stats are unavailable" }] };
    const lines = [];
    const gauges = [];
    if (n(row.percent)) {
      gauges.push({ label: "CPU", pct: row.percent, text: Math.round(row.percent) + "%", tone: loadTone(row.percent) });
      lines.push({ cls: "hide", text: row.percent + "%" });
    } else lines.push({ cls: "dim", text: "Percent arrives on the next sample." });
    if (h.model) lines.push({ cls: "dim clip", text: h.model.replace(/\s+\d+-Core Processor$/i, "") + (h.threads ? " · " + h.threads + " threads" : "") });
    if (Array.isArray(row.load) && row.load.length) lines.push({ cls: "clip", text: "Load " + row.load.map((x) => Number(x).toFixed(2)).join("  ") });
    if (h.uptime_s != null) lines.push({ cls: "dim", text: "Up " + uptime(h.uptime_s) });
    return { title: "CPU", kind: "cpu", gauges, lines, spark: { key: "cpu", value: row.percent, max: 100, unit: "%" } };
  }

  function memCard(mem) {
    const row = mem || {};
    if (!row.available) return { title: "Memory", kind: "mem", lines: [{ text: row.message || "Memory stats are unavailable" }] };
    const p = pct(row.used, row.total);
    return {
      title: "Memory",
      kind: "mem",
      gauges: p == null ? [] : [{ label: "RAM", pct: p, text: Math.round(p) + "%", tone: loadTone(p) }],
      lines: [
        { cls: "val clip", text: (n(row.used) ? (row.used / 1024 ** 3).toFixed(1) : "—") + " / " + gb(row.total) },
        { cls: "dim", text: gb(row.free) + " free" },
      ],
    };
  }

  function gpuCard(g) {
    const lines = [];
    const gauges = [];
    const vram = pct(g.memory_used_mib, g.memory_total_mib);
    if (vram != null) gauges.push({ label: "VRAM", pct: vram, text: Math.round(vram) + "%", tone: loadTone(vram) });
    if (n(g.util_percent)) gauges.push({ label: "Busy", pct: g.util_percent, text: g.util_percent + "%", tone: loadTone(g.util_percent) });
    if (n(g.temperature_c)) gauges.push({ label: "Temp", pct: Math.min(100, g.temperature_c), text: g.temperature_c + "°", tone: tempTone(g.temperature_c) });
    if (n(g.memory_used_mib) && n(g.memory_total_mib)) {
      lines.push({ cls: "val", text: (g.memory_used_mib / 1024).toFixed(1) + " / " + (g.memory_total_mib / 1024).toFixed(1) + " GB" });
    } else {
      lines.push({ cls: "dim", text: g.onboard ? "Onboard display" : "No VRAM reading" });
    }
    // Temperature and busy % are in the gauges; the text keeps the rest.
    const a = [];
    if (!gauges.some((x) => x.label === "Temp") && n(g.temperature_c)) a.push(g.temperature_c + " °C");
    if (n(g.fan_percent)) a.push("fan " + g.fan_percent + "%");
    if (n(g.power_w)) a.push(Math.round(g.power_w) + (n(g.power_limit_w) ? "/" + Math.round(g.power_limit_w) : "") + " W");
    if (a.length) lines.push({ cls: "clip", text: a.join(" · ") });
    const c = [];
    if (n(g.sm_mhz)) c.push(g.sm_mhz + (n(g.mem_mhz) ? "/" + g.mem_mhz : "") + " MHz");
    if (n(g.pcie_gen) || n(g.pcie_width)) c.push((n(g.pcie_gen) ? "Gen" + g.pcie_gen : "PCIe") + (n(g.pcie_width) ? " x" + g.pcie_width : ""));
    if (g.bus) c.push(String(g.bus).replace(/^0000:/, ""));
    if (c.length) lines.push({ cls: "dim clip", text: c.join(" · ") });
    const label = n(g.index) ? "GPU" + g.index + " · " : "";
    const card = { title: label + shortName(g.name), kind: "gpu", gauges, lines };
    if (g.holds_model) card.badge = "Holds the model" + (n(g.model_mib) && g.model_mib ? " · " + (g.model_mib / 1024).toFixed(1) + " GB" : "");
    card.tip = [g.name, g.pci_name && g.pci_name !== g.name ? g.pci_name : "", g.pci_id || ""].filter(Boolean).join("\n");
    if (g.onboard || (!gauges.length && !n(g.memory_total_mib))) card.mini = true;
    if (n(g.util_percent)) card.spark = { key: "gpu:" + (g.bus || g.index), value: g.util_percent, max: 100, unit: "%" };
    return card;
  }

  function gpuCards(gpu) {
    const row = gpu || {};
    if (!row.available || !Array.isArray(row.gpus) || !row.gpus.length) {
      return [{ title: "GPU", kind: "gpu", lines: [{ text: row.message || "GPU stats are unavailable" }] }];
    }
    return row.gpus.map(gpuCard);
  }

  function gpuLines(gpu) {
    const row = gpu || {};
    if (!row.available) return [{ text: row.message || "GPU stats are unavailable" }];
    const lines = [];
    (row.gpus || []).forEach((g) => {
      lines.push({ text: g.name || "GPU" });
      lines.push({ text: g.memory_used_mib + " / " + g.memory_total_mib + " MiB" });
      if (g.temperature_c != null) lines.push({ text: g.temperature_c + " °C" });
    });
    if (!lines.length) return [{ text: row.message || "GPU stats are unavailable" }];
    return lines;
  }

  const ROLE_TEXT = { boot: "Boot stick", models: "Models", vault: "Vault" };

  function driveRows(disk) {
    const row = disk || {};
    if (Array.isArray(row.drives) && row.drives.length) {
      return row.drives.map((d) => {
        const used = pct(d.fs_used, d.fs_total);
        const io = [];
        if (n(d.read_mb_s)) io.push("R " + d.read_mb_s.toFixed(1));
        if (n(d.write_mb_s)) io.push("W " + d.write_mb_s.toFixed(1));
        return {
          name: d.name,
          model: d.model && d.model !== d.name ? d.model : "",
          kind: d.kind || "",
          size: size(d.size),
          roles: (d.roles || []).map((r) => ROLE_TEXT[r] || r),
          used_pct: used,
          usage: n(d.fs_total) ? gbt(d.fs_free) + " free of " + gbt(d.fs_total) : "not mounted",
          io: io.length ? io.join("  ") + " MB/s" : "",
        };
      });
    }
    return (row.volumes || []).map((vol) => ({
      name: vol.label || "Disk",
      model: "",
      kind: "",
      size: n(vol.total) ? gb(vol.total) : "",
      roles: [],
      used_pct: pct(vol.used != null ? vol.used : vol.total - vol.free, vol.total),
      usage: vol.available ? gb(vol.free) + " free of " + gb(vol.total) : "unavailable",
      io: "",
    }));
  }

  function diskCard(disk) {
    const row = disk || {};
    if (!row.available) return { title: "Disks", kind: "disk", lines: [{ text: row.message || "Disk stats are unavailable" }], drives: [] };
    const drives = driveRows(row);
    const lines = drives.map((d) => d.name + (d.model ? " " + d.model : "") + "  " + d.size + "  " + d.usage + (d.roles.length ? "  [" + d.roles.join(", ") + "]" : ""));
    return { title: "Disks", kind: "disk", drives, lines: lines.length ? lines.map((text) => ({ text })) : [{ text: "Disk stats are unavailable" }] };
  }

  function modelCard(model, live) {
    const row = model || {};
    if (!row.available) return { title: "Model", kind: "model", state: "none", lines: [{ text: row.message || "The model is not running." }] };
    const lines = [];
    const running = !!row.llama_up;
    const loading = !running && (row.service === "active" || row.service === "activating");
    const state = running ? "running" : loading ? "loading" : "stopped";
    if (row.name) lines.push({ cls: "val clip", text: String(row.name).replace(/\.gguf$/i, "") });
    lines.push({ cls: "state " + state, text: running ? "Running" : loading ? "Loading…" : "Stopped · the model is not running." });
    const l = live || {};
    let spark = null;
    if (running && l.available) {
      const t = [];
      if (n(l.gen_tok_s)) t.push(l.gen_tok_s + " tok/s gen");
      if (n(l.prompt_tok_s)) t.push(l.prompt_tok_s + " prompt");
      if (t.length) lines.push({ cls: "val", text: t.join(" · ") });
      if (n(l.ctx_used) && n(l.n_ctx)) lines.push({ cls: "dim", text: "Context " + l.ctx_used.toLocaleString() + " / " + l.n_ctx.toLocaleString() });
      else if (n(l.ctx_used_ratio)) lines.push({ cls: "dim", text: "Context " + Math.round(l.ctx_used_ratio * 100) + "% used" });
      else if (n(l.n_ctx)) lines.push({ cls: "dim", text: "Context size " + l.n_ctx.toLocaleString() });
      spark = { key: "toks", value: n(l.gen_tok_s) ? l.gen_tok_s : 0, max: null, unit: " tok/s" };
    }
    if (row.service) lines.push({ cls: "dim", text: "Service " + row.service });
    return { title: "Model", kind: "model", state, lines, spark };
  }

  function parseMonitor(doc) {
    if (!doc || typeof doc !== "object") return { error: "Status response was empty." };
    if (doc.ok === false && doc.cpu == null && doc.memory == null && doc.disk == null && doc.gpu == null && doc.model == null) {
      return { error: doc.message || doc.error || "Status request failed." };
    }
    const warn = Array.isArray(doc.warnings) ? doc.warnings.filter((w) => typeof w === "string" && w) : [];
    const cards = warn.length ? [{ title: "Warning", kind: "warn", lines: warn.map((text) => ({ text })) }] : [];
    // Onboard / no-VRAM display adapters (ASPEED BMC) are one line in the CPU card,
    // so four real GPUs still fit on one row.
    const cpu = cpuCard(doc.cpu, doc.host);
    const gpus = gpuCards(doc.gpu);
    const minis = gpus.filter((c) => c.mini);
    if (minis.length) cpu.lines.push({ cls: "dim clip", text: "Display: " + minis.map((c) => c.title).join(", ") });
    return {
      status: typeof doc.status_line === "string" ? doc.status_line : "",
      cards: cards.concat([modelCard(doc.model, doc.llama), cpu, memCard(doc.memory)], gpus.filter((c) => !c.mini), [diskCard(doc.disk)]),
    };
  }

  function failureMessage(status, doc, err) {
    if (err) {
      if (err.name === "AbortError") return "The status request timed out.";
      return err.message || "Could not read the stick.";
    }
    const body = doc && typeof doc === "object" ? doc : {};
    if (status === 401) return body.message || "Pair this browser from StickLLM first.";
    const detail = body.message || body.error || "";
    if (status) return detail ? detail + " (" + status + ")" : "Status request failed (" + status + ").";
    return detail || "Could not read the stick.";
  }

  // ---- drawing ---------------------------------------------------------------
  function svg(tag, attrs) {
    const el = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach((k) => el.setAttribute(k, String(attrs[k])));
    return el;
  }

  // 270° arc from 135° to 405°.
  function arcPath(cx, cy, r, frac) {
    const f = Math.max(0, Math.min(1, frac));
    const a0 = (135 * Math.PI) / 180;
    const a1 = a0 + f * 1.5 * Math.PI;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    const large = f * 270 > 180 ? 1 : 0;
    return "M" + x0.toFixed(2) + " " + y0.toFixed(2) + " A" + r + " " + r + " 0 " + large + " 1 " + x1.toFixed(2) + " " + y1.toFixed(2);
  }

  function gauge(g) {
    const box = document.createElement("div");
    box.className = "gauge";
    const s = svg("svg", { viewBox: "0 0 56 56", class: "arc", "aria-hidden": "true" });
    s.appendChild(svg("path", { d: arcPath(28, 28, 23, 1), class: "track" }));
    if (n(g.pct) && g.pct > 0) s.appendChild(svg("path", { d: arcPath(28, 28, 23, g.pct / 100), class: "fill t-" + g.tone }));
    const t = svg("text", { x: 28, y: 32, "text-anchor": "middle", class: "gv t-" + g.tone });
    t.textContent = g.text;
    s.appendChild(t);
    box.appendChild(s);
    const lab = document.createElement("span");
    lab.className = "gl";
    lab.textContent = g.label;
    box.appendChild(lab);
    box.title = g.label + " " + g.text;
    return box;
  }

  function sparkline(spec) {
    const data = getHistory(spec.key);
    const W = 120, H = 22;
    const wrap = document.createElement("div");
    wrap.className = "spark";
    const s = svg("svg", { viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", "aria-hidden": "true" });
    const vals = data.filter(n);
    const max = spec.max || Math.max(1, ...vals) * 1.15;
    const pts = [];
    data.forEach((v, i) => {
      if (!n(v)) return;
      const x = (W * (i + HISTORY - data.length)) / (HISTORY - 1);
      const y = H - 1 - (Math.min(v, max) / max) * (H - 2);
      pts.push(x.toFixed(1) + "," + y.toFixed(1));
    });
    if (pts.length > 1) {
      s.appendChild(svg("polygon", { points: pts[0].split(",")[0] + "," + H + " " + pts.join(" ") + " " + pts[pts.length - 1].split(",")[0] + "," + H, class: "sparea" }));
      s.appendChild(svg("polyline", { points: pts.join(" "), class: "spline" }));
    }
    wrap.appendChild(s);
    const cap = document.createElement("span");
    cap.className = "spcap";
    cap.textContent = "60 s" + (vals.length ? " · peak " + Math.round(Math.max(...vals)) + spec.unit : "");
    wrap.appendChild(cap);
    return wrap;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function driveTable(drives) {
    const list = el("div", "drives");
    drives.forEach((d) => {
      const r = el("div", "drive");
      const name = el("div", "dname");
      name.appendChild(el("strong", "", d.name));
      if (d.kind) name.appendChild(el("span", "kind", d.kind));
      if (d.model) name.appendChild(el("span", "dim clip", d.model));
      d.roles.forEach((role) => name.appendChild(el("span", "badge", role)));
      r.appendChild(name);
      r.appendChild(el("span", "dsize", d.size));
      const bar = el("div", "bar");
      const fill = el("i", "t-" + loadTone(d.used_pct));
      fill.style.width = (n(d.used_pct) ? d.used_pct.toFixed(0) : 0) + "%";
      bar.appendChild(fill);
      bar.title = d.usage;
      r.appendChild(bar);
      r.appendChild(el("span", "dim dfree", d.usage));
      r.appendChild(el("span", "dio", d.io));
      list.appendChild(r);
    });
    return list;
  }

  function card(item) {
    const art = el("article", "card k-" + (item.kind || "x") + (item.mini ? " mini" : "") + (item.state ? " s-" + item.state : ""));
    const head = el("header", "ch");
    const h = el("h2", "clip", item.title);
    if (item.tip) h.title = item.tip;
    head.appendChild(h);
    art.appendChild(head);
    if (item.badge) art.appendChild(el("span", "badge live", item.badge));
    const body = el("div", "cb");
    if (item.gauges && item.gauges.length) {
      const row = el("div", "gauges");
      item.gauges.forEach((g) => row.appendChild(gauge(g)));
      body.appendChild(row);
    }
    const text = el("div", "ct");
    if (item.kind === "disk" && item.drives && item.drives.length) text.appendChild(driveTable(item.drives));
    else (item.lines || []).forEach((line) => {
      if (line.cls === "hide") return;
      text.appendChild(el("p", line.cls || "", line.text));
    });
    body.appendChild(text);
    art.appendChild(body);
    if (item.spark) art.appendChild(sparkline(item.spark));
    return art;
  }

  function showError(text) {
    const board = document.getElementById("board");
    if (!board) return;
    board.replaceChildren();
    board.appendChild(card({ title: "Status", lines: [{ text: text || "Could not read the stick." }] }));
  }

  function render(view) {
    const board = document.getElementById("board");
    if (!board) return;
    if (!view || view.error) {
      showError(view && view.error);
      return;
    }
    (view.cards || []).forEach((item) => { if (item.spark) pushHistory(item.spark.key, item.spark.value); });
    board.replaceChildren();
    const sl = document.getElementById("statusLine");
    if (sl) sl.textContent = view.status || "";
    (view.cards || []).forEach((item) => board.appendChild(card(item)));
  }

  async function tick() {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const r = await fetch("/api/system", { cache: "no-store", signal: ctrl.signal });
      const text = await r.text();
      let doc = null;
      if (text) {
        try { doc = JSON.parse(text); }
        catch (e) {
          showError("Status response was not JSON (" + r.status + ").");
          return;
        }
      }
      if (!r.ok) {
        showError(failureMessage(r.status, doc, null));
        return;
      }
      render(parseMonitor(doc));
    } catch (e) {
      showError(failureMessage(0, null, e));
    } finally {
      clearTimeout(timer);
    }
  }

  function boot() {
    if (typeof document === "undefined" || !document.getElementById("board")) return;
    if (root_preview()) return;
    tick();
    setInterval(tick, POLL_MS);
  }

  // A static preview page sets window.STICKLLM_MONITOR_PREVIEW and calls render itself.
  function root_preview() {
    return typeof window !== "undefined" && !!window.STICKLLM_MONITOR_PREVIEW;
  }

  boot();
  return { parseMonitor, failureMessage, gb, gpuLines, tempTone, loadTone, pushHistory, render, arcPath, size };
});
