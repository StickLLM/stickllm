/* External script: the gateway CSP is script-src 'self' and blocks inline scripts.
 * Every document is read and written by the gateway in vault/Documents. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  const $ = (s) => document.querySelector(s);
  let editor = null;
  let openPath = "";
  let openKey = "";
  const KIND_LABEL = { docx: "Document", xlsx: "Spreadsheet", pptx: "Presentation" };
  function say(text) { $("#msg").textContent = text || ""; }
  async function api(url, opt) {
    const o = Object.assign({ cache: "no-store" }, opt || {});
    o.headers = Object.assign({ "X-StickLLM-Client": "ui" }, o.headers || {});
    const r = await fetch(url, o);
    if (r.status === 401) throw new Error("Pair this browser from StickLLM first.");
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.message || j.error || "Request failed");
    return j;
  }
  function post(url, body) {
    return api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }
  function today() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }
  // Default for New: "Document 2026-10-28.docx" (local date).
  function defaultName(kind) { return (KIND_LABEL[kind] || "Document") + " " + today() + "." + kind; }
  function baseName(path) { return String(path || "").split("/").pop(); }
  function splitExt(name) {
    const i = name.lastIndexOf(".");
    return i > 0 ? [name.slice(0, i), name.slice(i)] : [name, ""];
  }

  // One small name dialog for New, Rename and Save copy. Resolves the typed
  // name or null on cancel. The stem is preselected so typing replaces it.
  function askName(title, okText, value, check) {
    const dlg = $("#nameDlg");
    const input = $("#nameInput");
    $("#nameTitle").textContent = title;
    $("#nameOk").textContent = okText;
    $("#nameErr").textContent = "";
    input.value = value;
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => {
        if (done) return;
        done = true;
        $("#nameForm").onsubmit = null;
        $("#nameCancel").onclick = null;
        dlg.onclose = null;
        if (dlg.open) dlg.close();
        resolve(v);
      };
      $("#nameForm").onsubmit = (ev) => {
        ev.preventDefault();
        const v = input.value.trim();
        const err = !v ? "Type a name." : (check ? check(v) : "");
        if (err) { $("#nameErr").textContent = err; return; }
        finish(v);
      };
      $("#nameCancel").onclick = () => finish(null);
      dlg.onclose = () => finish(null);
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
      input.focus();
      const stem = splitExt(value)[0].length;
      try { input.setSelectionRange(0, stem); } catch (_) {}
    });
  }
  function badChars(v) {
    if (/[\\/:*?"<>|]/.test(v)) return 'Names cannot contain \\ / : * ? " < > |';
    if (v.startsWith(".")) return "Names cannot start with a dot.";
    return "";
  }

  function loadApi() {
    if (window.DocsAPI) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/docs-server/web-apps/apps/api/documents/api.js";
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Office is not reachable."));
      document.head.appendChild(s);
    });
  }
  // The chat tab (same origin) selects ONLYOFFICE in its App picker while a slides
  // editor with the StickLLM agent plugin is open here.
  // Tell the chat tab (same origin) a deck with the agent plugin is open / closed, so its
  // "Send to" picker can auto-select Office. Channel created per message (nothing held open).
  function tellAppAgent(open) {
    try {
      const ch = new BroadcastChannel("stickllm-appagent");
      ch.postMessage({ app: "onlyoffice", open: !!open, path: open ? openPath : "" });
      ch.close();
    } catch (_) {}
  }
  if (typeof window.addEventListener === "function") window.addEventListener("pagehide", () => tellAppAgent(false));
  async function open(path) {
    try {
      const doc = await api("/api/docs/config?path=" + encodeURIComponent(path) + "&lang=en");
      await loadApi();
      if (editor && editor.destroyEditor) editor.destroyEditor();
      $("#editorWrap").innerHTML = '<div id="editor"></div>';
      document.body.classList.add("editing");
      $("#close").hidden = false;
      openPath = doc.path || path;
      openKey = (doc.config && doc.config.document && doc.config.document.key) || "";
      const cfg = Object.assign({ width: "100%", height: "100%" }, doc.config);
      // Handlers turn on the editor's own "Save Copy As" and "Rename" items.
      cfg.events = {
        onRequestSaveAs: (ev) => editorSaveAs(ev && ev.data),
        onRequestRename: (ev) => editorRename(ev && ev.data),
        onDownloadAs: () => say("Downloaded to vault/Downloads."),
      };
      editor = new window.DocsAPI.DocEditor("editor", cfg);
      tellAppAgent(/\.pptx$/i.test(openPath) && !!(doc.config && doc.config.editorConfig && doc.config.editorConfig.plugins));
    } catch (e) { say(e.message); }
  }
  async function editorSaveAs(data) {
    if (!data || !data.url) return;
    try {
      const j = await post("/api/docs/save-as", { path: openPath, title: data.title || "", fileType: data.fileType || "", url: data.url });
      say("Saved a copy as " + j.path);
      if (editor && editor.showMessage) editor.showMessage("Saved a copy as " + baseName(j.path));
    } catch (e) {
      say("Save copy failed: " + e.message);
      if (editor && editor.showMessage) editor.showMessage("Save copy failed: " + e.message);
    }
  }
  async function editorRename(title) {
    if (!title || !openPath) return;
    try {
      const j = await post("/api/docs/rename", { path: openPath, name: String(title), key: openKey });
      openPath = j.path;
      say("Renamed to " + j.path);
      if (editor && editor.setDocumentTitle) { try { editor.setDocumentTitle(baseName(j.path)); } catch (_) {} }
    } catch (e) {
      say("Rename failed: " + e.message);
      if (editor && editor.showMessage) editor.showMessage("Rename failed: " + e.message);
    }
  }
  function closeEditor() {
    if (editor && editor.destroyEditor) editor.destroyEditor();
    editor = null;
    openPath = "";
    openKey = "";
    tellAppAgent(false);
    document.body.classList.remove("editing");
    $("#close").hidden = true;
    refresh();
  }
  async function renameFromList(path) {
    const cur = baseName(path);
    const [, ext] = splitExt(cur);
    const v = await askName("Rename", "Rename", cur, badChars);
    if (v == null) return;
    try {
      const j = await post("/api/docs/rename", { path, name: v.endsWith(ext) ? v : v + ext });
      say("Renamed to " + j.path);
      await refresh();
    } catch (e) { say("Rename failed: " + e.message); }
  }
  async function copyFromList(path) {
    const [stem, ext] = splitExt(baseName(path));
    const v = await askName("Save copy as", "Save copy", stem + " copy" + ext, badChars);
    if (v == null) return;
    try {
      const j = await post("/api/docs/copy", { path, name: v });
      say("Saved a copy as " + j.path);
      await refresh();
    } catch (e) { say("Save copy failed: " + e.message); }
  }
  function btn(text, fn, disabled) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.disabled = !!disabled;
    b.addEventListener("click", fn);
    return b;
  }
  function when(t) {
    try { return new Date(t * 1000).toLocaleString(); } catch (_) { return ""; }
  }
  async function refreshDownloads(ready) {
    const box = $("#downloads");
    box.innerHTML = "";
    try {
      const doc = await api("/api/docs/downloads");
      const rows = doc.downloads || [];
      if (!rows.length) {
        const li = document.createElement("li");
        li.className = "muted";
        li.textContent = "Nothing downloaded yet. Download from Office or the browser and it shows up here.";
        box.appendChild(li);
        return;
      }
      rows.forEach((d) => {
        const li = document.createElement("li");
        const left = document.createElement("span");
        left.textContent = d.name + " ";
        const w = document.createElement("span");
        w.className = "when";
        w.textContent = when(d.mtime);
        left.appendChild(w);
        const row = document.createElement("span");
        row.className = "row";
        if (d.office) {
          row.append(btn("Open in Office", async () => {
            try {
              const j = await post("/api/docs/import-download", { name: d.name });
              say("Copied " + d.name + " to Documents as " + j.path);
              await refresh();
              open(j.path);
            } catch (e) { say(e.message); }
          }, !ready));
        } else {
          const m = document.createElement("span");
          m.className = "muted";
          m.textContent = "not an Office file";
          row.append(m);
        }
        li.append(left, row);
        box.appendChild(li);
      });
    } catch (e) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = e.message;
      box.appendChild(li);
    }
  }
  async function refresh() {
    let st = null;
    try { st = await api("/api/docs/status"); } catch (e) { $("#state").textContent = e.message; }
    if (st) $("#state").textContent = st.message || st.state;
    const ready = !!(st && st.running);
    document.querySelectorAll("[data-new], #upload").forEach((el) => { el.disabled = !(st && st.vault_open && st.installed); });
    const list = $("#list");
    list.innerHTML = "";
    $("#dlSec").hidden = !(st && st.vault_open);
    if (!st || !st.vault_open) return;
    try {
      const doc = await api("/api/docs/list");
      (doc.documents || []).forEach((d) => {
        const li = document.createElement("li");
        const name = document.createElement("span");
        name.textContent = d.path;
        const row = document.createElement("span");
        row.className = "row";
        const dl = document.createElement("a");
        dl.href = "/api/docs/download?path=" + encodeURIComponent(d.path);
        dl.textContent = "Download";
        dl.style.color = "#2bb5a8";
        dl.addEventListener("click", () => setTimeout(() => {
          say("Downloaded " + baseName(d.path) + " to vault/Downloads.");
          refreshDownloads(ready);
        }, 1500));
        row.append(
          btn(d.editable ? "Open" : "View", () => open(d.path), !ready),
          btn("Rename", () => renameFromList(d.path)),
          btn("Save copy as", () => copyFromList(d.path)),
          dl,
        );
        li.append(name, row);
        list.appendChild(li);
      });
      if (!(doc.documents || []).length) say("No documents in vault/Documents yet.");
    } catch (e) { say(e.message); }
    await refreshDownloads(ready);
  }
  document.querySelectorAll("[data-new]").forEach((b) => {
    b.addEventListener("click", async () => {
      const kind = b.dataset.new;
      const name = await askName("New " + (KIND_LABEL[kind] || "document").toLowerCase(), "Create", defaultName(kind), badChars);
      if (name == null) return;
      try {
        const j = await post("/api/docs/create", { kind, name });
        say("Created " + j.path);
        await refresh();
        open(j.path);
      } catch (e) { say(e.message); }
    });
  });
  $("#upload").addEventListener("change", async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    try {
      const j = await api("/api/docs/upload?name=" + encodeURIComponent(file.name), {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      say("Saved " + j.path + " in vault/Documents");
      ev.target.value = "";
      refresh();
    } catch (e) { say(e.message); }
  });
  $("#dlRefresh").addEventListener("click", () => refresh());
  $("#close").addEventListener("click", closeEditor);
  // Exposed for tests (node): pure helpers only.
  window.__stickDocs = { defaultName, today };
  const params = new URLSearchParams(location.search);
  refresh().then(() => { if (params.get("open")) open(params.get("open")); });
})();
