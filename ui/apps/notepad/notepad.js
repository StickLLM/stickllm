/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  const $ = (s) => document.querySelector(s);
  let name = "note.txt";
  function say(text) { $("#msg").textContent = text || ""; $("#where").textContent = name; }
  function txtName(value) {
    const base = String(value || "").replace(/\\/g, "/").split("/").pop().trim();
    if (!base || base.includes("..") || /[/:*?"<>|]/.test(base)) return "";
    return base.toLowerCase().endsWith(".txt") ? base : base + ".txt";
  }
  async function api(url, opt) {
    const r = await fetch(url, Object.assign({ cache: "no-store" }, opt || {}));
    if (r.status === 401) throw new Error("Pair this browser from StickLLM first.");
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.message || j.error || "Request failed");
    return j;
  }
  $("#neu").addEventListener("click", () => { $("#doc").value = ""; name = "note.txt"; say("New note"); });
  $("#save").addEventListener("click", async () => {
    const picked = txtName(prompt("Save as", name));
    if (!picked) { say("Use a plain .txt name."); return; }
    name = picked;
    try {
      await api("/api/files/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: $("#root").value, path: name, text: $("#doc").value }),
      });
      say("Saved " + name);
    } catch (e) { say(e.message); }
  });
  $("#open").addEventListener("click", async () => {
    const root = $("#root").value;
    try {
      const doc = await api("/api/files/list?root=" + encodeURIComponent(root) + "&path=");
      const files = (doc.entries || []).filter((e) => !e.dir && !e.symlink && String(e.name || "").toLowerCase().endsWith(".txt"));
      if (!files.length) { say("No .txt files in that folder."); return; }
      const picked = prompt("Open which file?\n" + files.map((e) => e.name).join("\n"), files[0].name);
      const file = txtName(picked);
      if (!file || !files.some((e) => e.name === file)) { say("That file is not in the list."); return; }
      const r = await fetch("/api/files/read?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(file), { cache: "no-store" });
      if (r.status === 401) throw new Error("Pair this browser from StickLLM first.");
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.message || j.error || "Could not open that file.");
      }
      $("#doc").value = await r.text();
      name = file;
      say("Opened " + file);
    } catch (e) { say(e.message); }
  });
  api("/api/files/roots").then((doc) => {
    const vault = (doc.roots || []).find((r) => r.id === "vault");
    const opt = $("#root").querySelector('option[value="vault"]');
    if (opt && (!vault || !vault.available)) opt.disabled = true;
  }).catch((e) => say(e.message));
})();
