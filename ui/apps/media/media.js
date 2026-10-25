/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;
  const $ = (s) => document.querySelector(s);
  const MEDIA = /\.(png|jpe?g|gif|webp|bmp|mp3|wav|ogg|m4a|mp4|webm|ogv)$/i;
  let rel = "";
  function say(text) { $("#msg").textContent = text || ""; }
  function kind(name) {
    if (/\.(png|jpe?g|gif|webp|bmp)$/i.test(name)) return "img";
    if (/\.(mp3|wav|ogg|m4a)$/i.test(name)) return "audio";
    if (/\.(mp4|webm|ogv)$/i.test(name)) return "video";
    return "";
  }
  function join(name) { return rel ? rel + "/" + name : name; }
  function show(url, name) {
    const stage = $("#stage");
    stage.innerHTML = "";
    const tag = kind(name);
    if (!tag) { say("That file is not a picture, audio, or video."); return; }
    const el = document.createElement(tag);
    el.src = url;
    el.controls = tag !== "img";
    el.alt = name;
    stage.appendChild(el);
    say(name);
  }
  async function load() {
    const r = await fetch("/api/files/roots", { cache: "no-store" });
    const doc = await r.json().catch(() => ({}));
    if (r.status === 401) { say(doc.message || "Pair this browser from StickLLM first."); return; }
    if (!r.ok || doc.ok === false) { say(doc.message || doc.error || "Could not read folders."); return; }
    const sel = $("#root");
    sel.innerHTML = "";
    (doc.roots || []).forEach((item) => {
      if (!item.available) return;
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = item.label;
      sel.appendChild(opt);
    });
    rel = "";
    if (!sel.options.length) say("No folders are available. You can still pick a file on this computer.");
    else list();
  }
  async function list() {
    const root = $("#root").value;
    if (!root) return;
    const r = await fetch("/api/files/list?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(rel), { cache: "no-store" });
    const doc = await r.json().catch(() => ({}));
    if (r.status === 401) { say(doc.message || "Pair this browser from StickLLM first."); return; }
    if (!r.ok || doc.ok === false) { say(doc.message || doc.error || "Could not list files."); return; }
    const box = $("#files");
    box.innerHTML = "";
    const entries = doc.entries || [];
    const dirs = entries.filter((e) => e.dir && !e.symlink && !e.outside);
    const files = entries.filter((e) => !e.dir && !e.symlink && !e.outside && MEDIA.test(e.name));
    dirs.forEach((entry) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Folder  " + entry.name;
      btn.addEventListener("click", () => { rel = join(entry.name); list().catch((e) => say(e.message)); });
      li.appendChild(btn);
      box.appendChild(li);
    });
    files.forEach((entry) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = entry.name;
      btn.addEventListener("click", () => show("/api/files/read?root=" + encodeURIComponent(root) + "&path=" + encodeURIComponent(join(entry.name)), entry.name));
      li.appendChild(btn);
      box.appendChild(li);
    });
    if (!dirs.length && !files.length) say("No pictures, audio, or video in this folder. You can still pick a file on this computer.");
    else say(rel ? root + " / " + rel : "");
  }
  $("#root").addEventListener("change", () => { rel = ""; list().catch((e) => say(e.message)); });
  $("#up").addEventListener("click", () => {
    if (!rel) return;
    rel = rel.split("/").slice(0, -1).join("/");
    list().catch((e) => say(e.message));
  });
  $("#local").addEventListener("change", (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    show(url, file.name);
  });
  load().catch((e) => say(e.message));
})();
