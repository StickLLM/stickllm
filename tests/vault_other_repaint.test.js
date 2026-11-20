"use strict";
// 0.5.6: "Vault is on another computer" must survive the health poll's
// setVaultChrome(false) repaint (it flipped back to "Vault locked").
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const cut = (a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); assert.ok(i >= 0 && j > i, a); return src.slice(i, j); };
const absentBlock = cut("let vaultUnlocking = false;", "// Inline message under the unlock form");
const otherBlock = cut("const VAULT_OTHER_RE", "\n}\n") + "\n}\n";
const chromeBlock = cut("// Bumped on every vault open/locked change", "// Lock means nothing from any chat");
const els = {};
const $ = (s) => (els[s] = els[s] || { textContent: "", hidden: false, classList: { toggle() {} } });
const state = { vaultOpen: false };
const api = new Function("$", "state", "applyModeUi", "clearOnLock", "unlockMessage",
  "let clearingOnLock = false; let sessionMode = 'ephemeral';\n" + absentBlock + otherBlock + chromeBlock +
  "\nreturn { setVaultChrome, showVaultOther };")($, state, () => {}, () => {}, () => {});
api.showVaultOther(true, "Other PC");
assert.strictEqual(els["#vcState"].textContent, "Vault is on another computer");
api.setVaultChrome(false);
assert.strictEqual(els["#vcState"].textContent, "Vault is on another computer", "health repaint keeps it");
api.showVaultOther(false);
api.setVaultChrome(false);
assert.strictEqual(els["#vcState"].textContent, "Vault locked");
api.setVaultChrome(true);
assert.strictEqual(els["#vcState"].textContent, "Vault unlocked");
console.log("vault_other_repaint ok");
