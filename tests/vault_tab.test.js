"use strict";
// 0.5.5: a health/status answer that was requested before an unlock or lock
// finished must not repaint the vault card or the Ephemeral/Vault tabs.
// Before: right after unlock a stale "absent" health showed "No vault set up"
// (and Ephemeral, and a screen clear); right after lock a stale "unlocked"
// health lit the Vault tab and "Vault unlocked" for one poll.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const cut = (a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); assert.ok(i >= 0 && j > i, a); return src.slice(i, j); };

const absentBlock = cut("let vaultUnlocking = false;", "// Inline message under the unlock form");
const chromeBlock = cut("// Bumped on every vault open/locked change", "// Lock means nothing from any chat");

const els = {};
const $ = (s) => (els[s] = els[s] || { textContent: "", hidden: false, classList: { toggle() {} } });
const state = { vaultOpen: false };
const calls = [];
const api = new Function("$", "state", "applyModeUi", "clearOnLock", "unlockMessage", "sessionModeRef",
  "let clearingOnLock = false; let sessionMode = sessionModeRef.m;\n" + absentBlock + chromeBlock +
  "\nreturn { setVaultChrome, vaultIsAbsent, epoch: () => vaultEpoch, bump: () => { vaultEpoch += 1; }," +
  " busy: () => vaultBusy(), setUnlocking: (v) => { vaultUnlocking = v; }, setLocking: (v) => { vaultLocking = v; } };")(
  $, state, (m) => calls.push("mode:" + m), () => calls.push("clear"), () => {}, { m: "ephemeral" });

// Epoch moves only on a real open/locked change.
const e0 = api.epoch();
api.setVaultChrome(false);
assert.strictEqual(api.epoch(), e0, "locked -> locked keeps the epoch");
api.setVaultChrome(true);
assert.strictEqual(api.epoch(), e0 + 1, "locked -> unlocked bumps");
assert.strictEqual($("#vcState").textContent, "Vault unlocked");
api.setVaultChrome(true);
assert.strictEqual(api.epoch(), e0 + 1);
api.setVaultChrome(false);
assert.strictEqual(api.epoch(), e0 + 2, "unlocked -> locked bumps");

// vaultBusy covers both directions.
assert.strictEqual(api.busy(), false);
api.setUnlocking(true); assert.strictEqual(api.busy(), true); api.setUnlocking(false);
api.setLocking(true); assert.strictEqual(api.busy(), true); api.setLocking(false);

// A not-yet-bound vault the settings vault knows about is locked, not absent.
assert.strictEqual(api.vaultIsAbsent({ status: "absent", mounted: false, usb_settings: "present-locked" }), false);
assert.strictEqual(api.vaultIsAbsent({ status: "absent", mounted: false }), true);

// refreshStatus: snapshot the epoch before /api/health, apply vault/mode only if still fresh.
const rs = cut("async function refreshStatus()", "\n}\n");
assert.ok(rs.indexOf("const ep = vaultEpoch;") < rs.indexOf('fetch("/api/health"'), "epoch taken before the request");
assert.ok(rs.includes("const vaultFresh = () => ep === vaultEpoch && !vaultBusy();"));
assert.ok(rs.includes("if (j.session_mode && vaultFresh()) {"), "mode tabs only from a fresh answer");
assert.ok(rs.includes("if (j.vault && vaultFresh()) setVaultChrome(vaultIsOpen(j.vault), vaultIsAbsent(j.vault));"));
// refreshStorage: same guard around control status.
const rst = cut("async function refreshStorage()", "async function refreshDrivesLive()");
assert.ok(rst.indexOf("const ep = vaultEpoch;") < rst.indexOf('control("status")'));
assert.ok(rst.includes("if (ep !== vaultEpoch || vaultBusy()) return;"));
// Unlock start, the screen clear, and the end of a lock all invalidate in-flight answers.
assert.ok(/vaultUnlocking = true;\n  vaultEpoch \+= 1;/.test(src), "unlock start bumps");
assert.ok(cut("function clearOnLock()", "newChat();").includes("vaultEpoch += 1;"), "clear bumps (it sets vaultOpen=false itself)");
const lv = cut("async function lockVault()", "$(\"#lockBtn\").onclick");
assert.ok(lv.includes("vaultLocking = true;") && lv.includes("finally { vaultLocking = false; vaultEpoch += 1; }"));
console.log("vault_tab.test.js ok");
