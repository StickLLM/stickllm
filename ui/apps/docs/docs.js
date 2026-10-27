/* External script: the gateway CSP is script-src 'self' and blocks inline scripts.
 * Every document is read and written by the gateway in vault/Documents. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  const $ = (s) => document.querySelector(s);
  let editor = null;
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
  function loadApi() {
    if (window.DocsAPI) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/docs-server/web-apps/apps/api/documents/api.js";
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("ONLYOFFICE Docs is not reachable."));
      document.head.appendChild(s);
    });
  }
  async function open(path) {
    try {
      const doc = await api("/api/docs/config?path=" + encodeURIComponent(path) + "&lang=en");
      await loadApi();
      if (editor && editor.destroyEditor) editor.destroyEditor();
      $("#editorWrap").innerHTML = '<div id="editor"></div>';
      document.body.classList.add("editing");
      $("#close").hidden = false;
      editor = new window.DocsAPI.DocEditor("editor", Object.assign({ width: "100%", height: "100%" }, doc.config));
    } catch (e) { say(e.message); }
  }
  function closeEditor() {
    if (editor && editor.destroyEditor) editor.destroyEditor();
    editor = null;
    document.body.classList.remove("editing");
    $("#close").hidden = true;
    refresh();
  }
  async function refresh() {
    let st = null;
    try { st = await api("/api/docs/status"); } catch (e) { $("#state").textContent = e.message; }
    if (st) $("#state").textContent = st.message || st.state;
    const ready = !!(st && st.running);
    document.querySelectorAll("[data-new], #upload").forEach((el) => { el.disabled = !(st && st.vault_open && st.installed); });
    const list = $("#list");
    list.innerHTML = "";
    if (!st || !st.vault_open) return;
    try {
      const doc = await api("/api/docs/list");
      (doc.documents || []).forEach((d) => {
        const li = document.createElement("li");
        const name = document.createElement("span");
        name.textContent = d.path;
        const row = document.createElement("span");
        row.className = "row";
        const ob = document.createElement("button");
        ob.type = "button";
        ob.textContent = d.editable ? "Open" : "View";
        ob.disabled = !ready;
        ob.addEventListener("click", () => open(d.path));
        const dl = document.createElement("a");
        dl.href = "/api/docs/download?path=" + encodeURIComponent(d.path);
        dl.textContent = "Download";
        dl.style.color = "#2bb5a8";
        row.append(ob, dl);
        li.append(name, row);
        list.appendChild(li);
      });
      if (!(doc.documents || []).length) say("No documents in vault/Documents yet.");
    } catch (e) { say(e.message); }
  }
  document.querySelectorAll("[data-new]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const j = await api("/api/docs/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: btn.dataset.new, name: $("#name").value || "Untitled" }),
        });
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
  $("#close").addEventListener("click", closeEditor);
  const params = new URLSearchParams(location.search);
  refresh().then(() => { if (params.get("open")) open(params.get("open")); });
})();
