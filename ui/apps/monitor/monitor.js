/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StickMonitor = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function gb(n) {
    if (typeof n !== "number" || !Number.isFinite(n)) return "—";
    return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB";
  }

  function cpuLines(cpu, host) {
    const row = cpu || {};
    if (!row.available) return [{ text: row.message || "CPU stats are unavailable" }];
    const lines = [];
    const h = host || {};
    if (h.model) lines.push({ cls: "dim", text: h.model + (h.threads ? "  ·  " + h.threads + " threads" : "") });
    if (typeof row.percent === "number") lines.push({ big: true, text: row.percent + "%" });
    else lines.push({ text: "Percent arrives on the next sample." });
    if (Array.isArray(row.load) && row.load.length) {
      lines.push({ text: "Load " + row.load.map((x) => Number(x).toFixed(2)).join("  ") });
    }
    if (h.uptime_s != null) lines.push({ cls: "dim", text: "Up " + uptime(h.uptime_s) });
    return lines;
  }

  function memLines(mem) {
    const row = mem || {};
    if (!row.available) return [{ text: row.message || "Memory stats are unavailable" }];
    return [
      { big: true, text: gb(row.used) },
      { text: "of " + gb(row.total) + "  ·  " + gb(row.free) + " free" },
    ];
  }

  function n(v) { return typeof v === "number" && Number.isFinite(v); }

  function gpuCard(g) {
    // 0.5.9: one card per GPU (NVIDIA, AMD, onboard) with its real PCI name.
    const lines = [];
    if (g.pci_name && g.pci_name !== g.name) lines.push({ cls: "dim", text: g.pci_name });
    if (g.holds_model) lines.push({ cls: "tag", text: "Holds the model" });
    if (n(g.memory_used_mib) && n(g.memory_total_mib)) {
      lines.push({ big: true, text: (g.memory_used_mib / 1024).toFixed(1) + " / " + (g.memory_total_mib / 1024).toFixed(1) + " GB" });
    } else if (g.onboard || !n(g.memory_total_mib)) {
      lines.push({ cls: "dim", text: g.onboard ? "Onboard display" : "No VRAM reading" });
    }
    const a = [];
    if (n(g.temperature_c)) a.push(g.temperature_c + " °C");
    if (n(g.util_percent)) a.push(g.util_percent + "% busy");
    if (n(g.fan_percent)) a.push("fan " + g.fan_percent + "%");
    if (a.length) lines.push({ text: a.join("  ·  ") });
    if (n(g.power_w)) lines.push({ text: Math.round(g.power_w) + " W" + (n(g.power_limit_w) ? " of " + Math.round(g.power_limit_w) + " W limit" : "") });
    const c = [];
    if (n(g.sm_mhz)) c.push("core " + g.sm_mhz + " MHz");
    if (n(g.mem_mhz)) c.push("mem " + g.mem_mhz + " MHz");
    if (c.length) lines.push({ cls: "dim", text: c.join("  ·  ") });
    if (n(g.pcie_gen) || n(g.pcie_width)) lines.push({ cls: "dim", text: "PCIe " + (n(g.pcie_gen) ? "Gen" + g.pcie_gen : "") + (n(g.pcie_width) ? " x" + g.pcie_width : "") + (g.bus ? "  ·  " + g.bus.replace(/^0000:/, "") : "") });
    const label = n(g.index) ? "GPU" + g.index + " · " : "";
    return { title: label + (g.name || "GPU"), lines };
  }

  function gpuCards(gpu) {
    const row = gpu || {};
    if (!row.available || !Array.isArray(row.gpus) || !row.gpus.length) {
      return [{ title: "GPU", lines: [{ text: row.message || "GPU stats are unavailable" }] }];
    }
    return row.gpus.map(gpuCard);
  }

  function gpuLines(gpu) {
    const row = gpu || {};
    if (!row.available) return [{ text: row.message || "GPU stats are unavailable" }];
    const lines = [];
    (row.gpus || []).forEach((g) => {
      lines.push({ text: g.name || "GPU" });
      lines.push({ big: true, text: g.memory_used_mib + " / " + g.memory_total_mib + " MiB" });
      if (g.temperature_c != null) lines.push({ text: g.temperature_c + " °C" });
    });
    if (!lines.length) return [{ text: row.message || "GPU stats are unavailable" }];
    return lines;
  }

  function uptime(s) {
    if (!n(s)) return "";
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return (d ? d + "d " : "") + (d || h ? h + "h " : "") + m + "m";
  }

  function diskLines(disk) {
    const row = disk || {};
    if (!row.available) return [{ text: row.message || "Disk stats are unavailable" }];
    const lines = [];
    (row.volumes || []).forEach((vol) => {
      const label = vol.label || "Disk";
      if (!vol.available) lines.push({ text: label + " unavailable" });
      else lines.push({ text: label + "  " + gb(vol.free) + " free of " + gb(vol.total) });
    });
    if (!lines.length) return [{ text: "Disk stats are unavailable" }];
    return lines;
  }

  function modelLines(model, live) {
    const row = model || {};
    if (!row.available) return [{ text: row.message || "The model is not running." }];
    const lines = [];
    if (row.name) lines.push({ text: row.name });
    lines.push({ text: row.llama_up ? "Running" : "The model is not running." });
    const l = live || {};
    if (row.llama_up && l.available) {
      const t = [];
      if (n(l.prompt_tok_s)) t.push("prompt " + l.prompt_tok_s + " tok/s");
      if (n(l.gen_tok_s)) t.push("gen " + l.gen_tok_s + " tok/s");
      if (t.length) lines.push({ big: true, text: t.join("  ·  ") });
      if (n(l.ctx_used) && n(l.n_ctx)) lines.push({ text: "Context " + l.ctx_used.toLocaleString() + " / " + l.n_ctx.toLocaleString() + " tokens" });
      else if (n(l.ctx_used_ratio)) lines.push({ text: "Context " + Math.round(l.ctx_used_ratio * 100) + "% used" });
      else if (n(l.n_ctx)) lines.push({ text: "Context size " + l.n_ctx.toLocaleString() + " tokens" });
    }
    if (row.service) lines.push({ cls: "dim", text: "Service " + row.service });
    return lines;
  }

  function parseMonitor(doc) {
    if (!doc || typeof doc !== "object") return { error: "Status response was empty." };
    if (doc.ok === false && doc.cpu == null && doc.memory == null && doc.disk == null && doc.gpu == null && doc.model == null) {
      return { error: doc.message || doc.error || "Status request failed." };
    }
    const warn = Array.isArray(doc.warnings) ? doc.warnings.filter((w) => typeof w === "string" && w) : [];
    const cards = warn.length ? [{ title: "Warning", lines: warn.map((text) => ({ text })) }] : [];
    return {
      status: typeof doc.status_line === "string" ? doc.status_line : "",
      cards: cards.concat([
        { title: "Model", lines: modelLines(doc.model, doc.llama) },
        { title: "CPU", lines: cpuLines(doc.cpu, doc.host) },
        { title: "Memory", lines: memLines(doc.memory) },
      ], gpuCards(doc.gpu), [
        { title: "Disk", lines: diskLines(doc.disk) },
      ]),
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

  function card(title, lines) {
    const el = document.createElement("article");
    const h = document.createElement("h2");
    h.textContent = title;
    el.appendChild(h);
    (lines || []).forEach((line) => {
      const p = document.createElement("p");
      if (line.big) p.className = "big";
      else if (line.cls) p.className = line.cls;
      p.textContent = line.text;
      el.appendChild(p);
    });
    return el;
  }

  function showError(text) {
    const board = document.getElementById("board");
    if (!board) return;
    board.replaceChildren();
    board.appendChild(card("Status", [{ text: text || "Could not read the stick." }]));
  }

  function render(view) {
    const board = document.getElementById("board");
    if (!board) return;
    if (!view || view.error) {
      showError(view && view.error);
      return;
    }
    board.replaceChildren();
    const sl = document.getElementById("statusLine");
    if (sl) sl.textContent = view.status || "";
    (view.cards || []).forEach((item) => board.appendChild(card(item.title, item.lines)));
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
    tick();
    setInterval(tick, 3000);
  }

  boot();
  return { parseMonitor, failureMessage, gb, gpuLines };
});
