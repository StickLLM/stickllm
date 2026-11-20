"use strict";
const assert = require("assert");
const path = require("path");
const calc = require(path.join(__dirname, "..", "ui", "apps", "calculator", "calc.js"));
const monitor = require(path.join(__dirname, "..", "ui", "apps", "monitor", "monitor.js"));
require(path.join(__dirname, "..", "ui", "apps", "files", "files.js"));
require(path.join(__dirname, "..", "ui", "apps", "media", "media.js"));

assert.strictEqual(calc.run(["2", "+", "2", "="]).display, "4");
assert.strictEqual(calc.run(["1", ".", "5", "+", "2", ".", "5", "="]).display, "4");
assert.strictEqual(calc.run([".", "5"]).display, "0.5");
assert.strictEqual(calc.run(["1", ".", "2", "."]).display, "1.2");
assert.strictEqual(calc.run(["2", "+", "+", "2", "="]).display, "4");

let cleared = calc.run(["9", "8"]);
cleared = calc.press(cleared, "C");
assert.strictEqual(cleared.display, "0");
assert.strictEqual(cleared.acc, null);
assert.strictEqual(cleared.op, null);

let broken = calc.run(["5", "/", "0", "="]);
assert.strictEqual(broken.display, "Error");
broken = calc.press(broken, "±");
assert.notStrictEqual(broken.display, "NaN");
assert.notStrictEqual(broken.display, "Error");
broken = calc.press(broken, "2");
broken = calc.press(broken, "+");
broken = calc.press(broken, "2");
broken = calc.press(broken, "=");
assert.strictEqual(broken.display, "4");

const chained = calc.run(["8", "/", "0", "+"]);
assert.strictEqual(chained.display, "Error");
assert.strictEqual(calc.press(chained, "3").display, "3");

const sample = {
  ok: true,
  cpu: { available: true, percent: 12.5, load: [0.1, 0.2, 0.3] },
  memory: { available: true, total: 32 * 1024 ** 3, used: 8 * 1024 ** 3, free: 24 * 1024 ** 3 },
  gpu: { available: true, gpus: [{ name: "RTX 3090", memory_used_mib: 1024, memory_total_mib: 24576, temperature_c: 42 }] },
  disk: { available: true, volumes: [{ label: "System", available: true, total: 100 * 1024 ** 3, free: 40 * 1024 ** 3 }] },
  model: { available: true, name: "qwen", llama_up: false, service: "inactive" },
};
const view = monitor.parseMonitor(sample);
function text(title) {
  return view.cards.find((card) => card.title === title).lines.map((line) => line.text).join("\n");
}
assert.ok(text("CPU").includes("12.5%"));
assert.ok(text("CPU").includes("0.10"));
assert.ok(text("Memory").includes("8.0 / 32.0 GB"));
assert.ok(text("Memory").includes("32.0 GB"));
const gpuCard = view.cards.find((card) => card.kind === "gpu");
assert.ok(gpuCard.title.includes("RTX 3090"));
assert.ok(gpuCard.lines.map((l) => l.text).join("\n").includes("1.0 / 24.0 GB"));
assert.ok(gpuCard.gauges.some((g) => g.label === "Temp" && g.text === "42°" && g.tone === "green"));
assert.ok(!gpuCard.badge, "no holds-the-model badge unless the backend says so");
const volTile = view.cards.find((card) => card.kind === "disk");
assert.ok(volTile.title.includes("System"));
assert.ok(volTile.lines.map((l) => l.text).join("\n").includes("free"));
assert.strictEqual(monitor.tempTone(65), "green");
assert.strictEqual(monitor.tempTone(75), "amber");
assert.strictEqual(monitor.tempTone(88), "red");

// 0.5.9 cleanup: every drive with roles, real names, onboard folded into CPU.
const full = monitor.parseMonitor({
  ok: true,
  cpu: { available: true, percent: 30, load: [1, 1, 1] },
  memory: { available: true, total: 62.7 * 1024 ** 3, used: 20 * 1024 ** 3, free: 42.7 * 1024 ** 3 },
  gpu: { available: true, gpus: [
    { index: 1, name: "NVIDIA CMP 170HX", memory_used_mib: 4, memory_total_mib: 8192, util_percent: 0, temperature_c: 34, holds_model: false },
    { index: 2, name: "NVIDIA GeForce RTX 3090", memory_used_mib: 13000, memory_total_mib: 24576, util_percent: 50, temperature_c: 78, holds_model: true, model_mib: 12900 },
    { index: null, name: "ASPEED Graphics Family", onboard: true },
  ] },
  disk: { available: true, drives: [
    { name: "sda", model: "SanDisk", kind: "USB", size: 64e9, roles: ["boot"], fs_total: 50 * 1024 ** 3, fs_used: 10 * 1024 ** 3, fs_free: 40 * 1024 ** 3, read_mb_s: 1.5, write_mb_s: 0, busy_percent: 12.5 },
    { name: "nvme0n1", model: "Fanxiang S880", kind: "NVMe", size: 2e12, roles: ["models", "vault"], read_mb_s: 900, write_mb_s: 2 },
  ] },
  model: { available: true, name: "Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf", llama_up: true, service: "active" },
  llama: { available: true, gen_tok_s: 80, ctx_used: 16384, n_ctx: 65536 },
});
const gcards = full.cards.filter((c) => c.kind === "gpu");
assert.strictEqual(gcards.length, 2);
assert.strictEqual(gcards[0].title, "GPU1 · CMP 170HX");
assert.ok(gcards[1].badge.startsWith("Holds the model"));
assert.ok(gcards[1].gauges.find((g) => g.label === "Temp").tone === "amber");
const cpuText = full.cards.find((c) => c.kind === "cpu").lines.map((l) => l.text).join("\n");
assert.ok(cpuText.includes("ASPEED"));
// Round 2: one uniform tile per disk with Space + Util gauges and role tags.
const diskTiles = full.cards.filter((c) => c.kind === "disk");
assert.deepStrictEqual(diskTiles.map((c) => c.drive.name), ["sda", "nvme0n1"]);
assert.ok(diskTiles[0].title.startsWith("USB · sda"));
assert.deepStrictEqual(diskTiles[0].tags, ["Boot stick"]);
assert.deepStrictEqual(diskTiles[1].tags, ["Models", "Vault"]);
assert.deepStrictEqual(diskTiles[0].gauges.map((g) => g.label), ["Space", "Util"]);
assert.strictEqual(diskTiles[0].gauges[0].text, "20%");
assert.strictEqual(diskTiles[0].gauges[1].text, "13%");
assert.ok(diskTiles[0].lines.some((l) => l.text.includes("free")));
assert.ok(diskTiles[1].lines.some((l) => l.text.includes("R 900.0")));
const mcard = full.cards.find((c) => c.kind === "model");
assert.strictEqual(mcard.spark.key, "toks");
assert.strictEqual(mcard.tip, "Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M");
assert.ok(mcard.lines[0].cls.includes("clip") && mcard.lines[0].tip === mcard.tip);
assert.ok(mcard.lines.some((l) => l.text.includes("16,384 / 65,536 (64K)")));
assert.strictEqual(mcard.gauges[0].text, "25%");
assert.ok(!full.cards.some((c) => c.title === "Disks"), "no wide disk table any more");
assert.ok(monitor.arcPath(28, 28, 23, 0.5).startsWith("M"));
assert.ok(text("Model").includes("qwen"));
assert.ok(text("Model").includes("the model is not running."));

const stopped = monitor.parseMonitor({
  ok: true,
  cpu: { available: false, message: "CPU stats are unavailable" },
  memory: { available: false },
  gpu: { available: false, message: "GPU stats are unavailable" },
  disk: { available: false },
  model: { available: false, message: "No model is loaded" },
});
assert.ok(stopped.cards.find((card) => card.title === "Model").lines[0].text.includes("No model is loaded"));
assert.strictEqual(monitor.parseMonitor(null).error, "Status response was empty.");
assert.strictEqual(
  monitor.parseMonitor({ ok: false, error: "system status failed" }).error,
  "system status failed"
);
assert.strictEqual(monitor.failureMessage(0, null, { name: "AbortError" }), "The status request timed out.");
assert.ok(monitor.failureMessage(500, { error: "system status failed" }, null).includes("system status failed"));
assert.ok(monitor.failureMessage(500, { error: "system status failed" }, null).includes("500"));

console.log("starter logic ok");
