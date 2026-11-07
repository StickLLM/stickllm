/* StickLLM Browser home — Web mode status (external file: CSP blocks inline script). */
(function () {
  "use strict";
  const LABELS = {
    internet: "Internet",
    tor: "Tor mode",
    none: "No internet",
  };
  const FALLBACK = {
    internet: "Normal uplink for this Browser window.",
    tor: "Public sites go through Tor. StickLLM Settings stay on Wi‑Fi.",
    none: "Public web is blocked. StickLLM on this stick still works.",
  };
  const pill = document.getElementById("modePill");
  const label = document.getElementById("modeLabel");
  const note = document.getElementById("modeNote");
  if (!pill || !label || !note) return;

  function paint(j) {
    const mode = (j && j.mode) || "internet";
    const key = LABELS[mode] ? mode : "internet";
    pill.dataset.mode = key;
    let title = LABELS[key];
    if (key === "tor" && j && j.tor_ready === false) title = "Tor — starting…";
    else if (key === "tor" && j && j.tor_ready) title = "Tor mode";
    label.textContent = title;
    note.textContent = (j && j.note) || FALLBACK[key];
    document.title = "StickLLM · " + title;
  }

  async function refresh() {
    try {
      const r = await fetch("/api/web-mode", { cache: "no-store" });
      const j = await r.json().catch(() => ({}));
      if (r.ok) paint(j);
      else paint({ mode: "internet", note: "Could not read Web mode (" + r.status + ")." });
    } catch (_) {
      paint({ mode: "internet", note: "StickLLM is unreachable — is the stick UI service up?" });
    }
  }

  refresh();
  setInterval(refresh, 4000);
})();
