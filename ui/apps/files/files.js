/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  const $ = (s) => document.querySelector(s);
  let root = "";
  let rel = "";
  function say(text) { $("#msg").textContent = text || ""; }
  async function api(url, opt) {
    const r = await fetch(url, Object.assign({ cache: "no-store" }, opt || {}));
    if (r.status === 401) throw new Error("Pair this browser from StickLLM first.");
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.message || j.error || "Request failed");
    return j;
  }
  async function loadRoots() {
    const doc = await api("/api/files/roots");
    const box = $("#roots");
    box.innerHTML = "";
    (doc.roots || []).forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = item.available ? item.label : item.label + " (not available)";
      btn.disabled = !item.available;
      if (item.id === root) btn.className = "on";
      btn.addEventListener("click", () => { root = item.id; rel = ""; refresh(); });
      box.appendChild(btn);
    });
    if (!root) {
      const first = (doc.roots || []).find((item) => item.available);
      if (first) root = first.id;
    }
  }
  async function refresh() {
    try {
      await loadRoots();
      if (!root) { $("#list").innerHTML = ""; say("No folders are available."); return; }
      const doc = await api("/api/files/list?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel));
      $("#crumb").textContent = root + (doc.path ? " / " + doc.path : "");
      const list = $("#list");
      list.innerHTML = "";
      if (!doc.exists) say("That folder is not on the drive yet. Upload or create a folder to make it.");
      else say("");
      (doc.entries || []).forEach((entry) => {
        const li = document.createElement("li");
        const open = document.createElement("button");
        open.type = "button";
        open.textContent = (entry.dir ? "Folder  " : "File  ") + entry.name;
        open.addEventListener("click", () => openEntry(entry));
        const del = document.createElement("button");
        del.type = "button";
        del.textContent = "Delete";
        del.addEventListener("click", () => remove(entry.name));
        li.append(open, del);
        list.appendChild(li);
      });
    } catch (e) {
      say(e.message || "Could not read that folder.");
    }
  }
  function join(name) { return rel ? rel + "/" + name : name; }
  function openEntry(entry) {
    if (entry.outside || entry.symlink) { say("That link points outside the allowed folders."); return; }
    if (entry.dir) { rel = join(entry.name); refresh(); return; }
    const url = "/api/files/read?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(join(entry.name));
    window.open(url, "_blank", "noopener");
  }
  async function remove(name) {
    if (!confirm("Delete " + name + "?")) return;
    try {
      await api("/api/files/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: root, path: join(name) }),
      });
      refresh();
    } catch (e) { say(e.message || "Could not delete that."); }
  }
  $("#up").addEventListener("click", () => {
    if (!rel) return;
    rel = rel.split("/").slice(0, -1).join("/");
    refresh();
  });
  $("#mkdir").addEventListener("click", async () => {
    const name = prompt("Folder name");
    if (!name) return;
    try {
      await api("/api/files/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: root, path: join(name) }),
      });
      refresh();
    } catch (e) { say(e.message); }
  });
  $("#upload").addEventListener("change", async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!file || !root) return;
    try {
      const r = await fetch("/api/files/upload?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(join(file.name)), {
        method: "POST",
        cache: "no-store",
        body: file,
      });
      if (r.status === 401) throw new Error("Pair this browser from StickLLM first.");
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.message || j.error || "Upload failed");
      refresh();
    } catch (e) { say(e.message); }
  });
  refresh();
})();
