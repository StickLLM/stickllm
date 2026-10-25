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

  function cpuLines(cpu) {
    const row = cpu || {};
    if (!row.available) return [{ text: row.message || "CPU stats are unavailable" }];
    const lines = [];
    if (typeof row.percent === "number") lines.push({ big: true, text: row.percent + "%" });
    else lines.push({ text: "Percent arrives on the next sample." });
    if (Array.isArray(row.load) && row.load.length) {
      lines.push({ text: "Load " + row.load.map((n) => Number(n).toFixed(2)).join("  ") });
    }
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

  function modelLines(model) {
    const row = model || {};
    if (!row.available) return [{ text: row.message || "The model is not running." }];
    const lines = [];
    if (row.name) lines.push({ text: row.name });
    lines.push({ text: row.llama_up ? "Running" : "The model is not running." });
    if (row.service) lines.push({ text: "Service " + row.service });
    return lines;
  }

  function parseMonitor(doc) {
    if (!doc || typeof doc !== "object") return { error: "Status response was empty." };
    if (doc.ok === false && doc.cpu == null && doc.memory == null && doc.disk == null && doc.gpu == null && doc.model == null) {
      return { error: doc.message || doc.error || "Status request failed." };
    }
    return {
      cards: [
        { title: "CPU", lines: cpuLines(doc.cpu) },
        { title: "Memory", lines: memLines(doc.memory) },
        { title: "GPU", lines: gpuLines(doc.gpu) },
        { title: "Disk", lines: diskLines(doc.disk) },
        { title: "Model", lines: modelLines(doc.model) },
      ],
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
  return { parseMonitor, failureMessage, gb };
});
