// 0.5.4 rc2: lock clears the screen, and the mode tabs follow the vault.
// Pulls applyModeUi/setVaultChrome/clearOnLock/lockVault out of ui/app.js and
// runs them against a tiny fake DOM.
const fs = require("fs");
const assert = require("assert");
const src = fs.readFileSync(__dirname + "/../ui/app.js", "utf8");
const grab = (start, end) => {
  const i = src.indexOf(start);
  assert(i >= 0, "missing " + start);
  return src.slice(i, src.indexOf(end, i));
};
const code = [
  grab("function applyModeUi(", "\n}\n") + "\n}\n",
  grab("function setVaultChrome(", "\n}\n") + "\n}\n",
  grab("function clearOnLock(", "\nasync function lockVault(") ,
  grab("async function lockVault(", "\n}\n") + "\n}\n",
].join("\n");

function el(extra = {}) {
  const cls = new Set();
  return Object.assign({
    hidden: false, value: "", textContent: "", innerHTML: "", disabled: false,
    dataset: {}, style: {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), toggle: (c, on) => { if (on === undefined ? !cls.has(c) : on) cls.add(c); else cls.delete(c); }, contains: (c) => cls.has(c) },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; },
    querySelector: () => null, querySelectorAll: () => [],
  }, extra);
}
const modeBtns = ["ephemeral", "vault", "ephemeral", "vault"].map((m) => el({ dataset: { mode: m } }));
const textareas = [el({ value: "secret draft" }), el({ value: "note" })];
const byId = {};
const $ = (s) => { if (!byId[s]) byId[s] = el(); return byId[s]; };
const $$ = (s) => (s === "textarea" ? textareas : s.includes("data-mode") ? modeBtns : []);
const calls = [];
const closed = [];
const appTabs = new Map([["stickllm-trilium", { closed: false, close() { closed.push("trilium"); this.closed = true; } }]]);
const env = {
  $, $$, appTabs, calls, closed,
  state: { mode: "vault", vaultOpen: true, chats: [{ id: "1", title: "Tax plan" }], ephemeral: [{ id: "e", title: "Temp" }], current: { id: "1" }, attach: [{ name: "x.pdf" }] },
  sessionMode: "vault", vaultUnlocking: false, clearingOnLock: false, activeChatId: "1",
  sendAbort: { aborted: false, abort() { this.aborted = true; } },
};
const factory = new Function("env", `
  let { $, $$, appTabs, state, calls } = env;
  let sessionMode = env.sessionMode, vaultUnlocking = env.vaultUnlocking, clearingOnLock = false, activeChatId = env.activeChatId, sendAbort = env.sendAbort;
  const messages = [{ role: "system", content: "s" }, { role: "user", content: "hello secret" }];
  function stopSpeak() { calls.push("stopSpeak"); }
  function renderAttach() { calls.push("renderAttach"); }
  function renderConvs() { calls.push("renderConvs"); }
  function renderSaved() { calls.push("renderSaved"); }
  function newChat() { calls.push("newChat"); state.current = null; activeChatId = null; messages.length = 1; }
  function toast(m) { calls.push("toast:" + m); }
  function authHeaders(h) { return h || {}; }
  async function control(a) { calls.push("control:" + a); return { ok: true }; }
  async function fetch(u, o) { calls.push("fetch:" + u + ":" + (o && o.body)); return { ok: true, json: async () => ({ ok: true }) }; }
  let micState = "idle"; function heroModeLine() { return ""; } function unlockMessage() {}
  function syncHeaderStatus() {}
  function updateVaultBadge() {}
  ${code}
  return { applyModeUi, setVaultChrome, clearOnLock, lockVault, get sessionMode() { return sessionMode; }, set sessionMode(v) { sessionMode = v; }, messages, get activeChatId() { return activeChatId; } };
`);
const api = factory(env);
const on = () => modeBtns.filter((b) => b.classList.contains("on")).map((b) => b.dataset.mode);

// First load with a locked vault and a stale "vault" mode: Ephemeral is on.
api.applyModeUi("vault");
api.setVaultChrome(false);
assert.deepStrictEqual([...new Set(on())], ["ephemeral"], "locked vault must highlight Ephemeral");

// Unlocked: Vault may be on.
env.state.vaultOpen = false;
api.setVaultChrome(true);
api.applyModeUi("vault");
assert.deepStrictEqual([...new Set(on())], ["vault"]);
env.state.vaultOpen = true;
env.state.chats = [{ id: "1", title: "Tax plan" }];
env.state.ephemeral = [{ id: "e", title: "Temp" }];

(async () => {
  await api.lockVault();
  assert.deepStrictEqual([...new Set(on())], ["ephemeral"], "lock must go back to Ephemeral");
  assert.strictEqual(env.state.vaultOpen, false);
  assert.deepStrictEqual(env.state.chats, []);
  assert.deepStrictEqual(env.state.ephemeral, []);
  assert.deepStrictEqual(env.state.attach, []);
  assert.strictEqual(env.state.current, null);
  assert.strictEqual(api.messages.length, 1, "history must be dropped");
  assert(textareas.every((t) => t.value === ""), "drafts must be cleared");
  assert.deepStrictEqual(closed, ["trilium"], "open app tabs must close");
  assert.strictEqual(appTabs.size, 0);
  assert(env.sendAbort.aborted, "in-flight reply must be aborted");
  for (const c of ["stopSpeak", "newChat", "renderSaved", "control:vault_lock"]) assert(calls.includes(c), "missing " + c);
  assert(calls.some((c) => c.startsWith("fetch:/api/session-mode") && c.includes("ephemeral")));
  assert(calls.indexOf("newChat") < calls.indexOf("control:vault_lock"), "screen clears before the lock call");

  // A lock from elsewhere (kiosk combo, other browser) seen via health.
  calls.length = 0;
  env.state.vaultOpen = true;
  env.state.ephemeral = [{ id: "e2", title: "x" }];
  api.setVaultChrome(false);
  assert.deepStrictEqual(env.state.ephemeral, []);
  assert(calls.includes("newChat"));
  console.log("lock clear ok");
})().catch((e) => { console.error(e); process.exit(1); });
