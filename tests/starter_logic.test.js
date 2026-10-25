"use strict";
const assert = require("assert");
const path = require("path");
const calc = require(path.join(__dirname, "..", "ui", "apps", "calculator", "calc.js"));
const mines = require(path.join(__dirname, "..", "ui", "apps", "minesweeper", "game.js"));
const monitor = require(path.join(__dirname, "..", "ui", "apps", "monitor", "monitor.js"));
require(path.join(__dirname, "..", "ui", "apps", "files", "files.js"));
require(path.join(__dirname, "..", "ui", "apps", "notepad", "notepad.js"));
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

for (let i = 0; i < 81; i++) {
  const game = mines.create(() => 0);
  mines.reveal(game, i);
  assert.strictEqual(game.cells[i].mine, false, "first click " + i);
  assert.strictEqual(game.cells[i].open, true, "opened " + i);
  assert.notStrictEqual(game.status, "You hit a mine");
}

const flagged = mines.create();
mines.flag(flagged, 4);
assert.strictEqual(flagged.cells[4].flag, true);
assert.strictEqual(flagged.cells[4].open, false);
mines.reveal(flagged, 4);
assert.strictEqual(flagged.cells[4].open, false);
mines.flag(flagged, 4);
assert.strictEqual(flagged.cells[4].flag, false);

const lost = mines.create(() => 0);
mines.reveal(lost, 0);
const mineAt = lost.cells.findIndex((cell) => cell.mine);
assert.ok(mineAt >= 0);
mines.reveal(lost, mineAt);
assert.strictEqual(lost.over, true);
assert.strictEqual(lost.win, false);
assert.strictEqual(lost.status, "You hit a mine");
assert.ok(lost.cells.every((cell) => !cell.mine || cell.open));

const fresh = mines.restart();
assert.strictEqual(fresh.status, "10 mines");
assert.strictEqual(fresh.over, false);
assert.ok(fresh.cells.every((cell) => !cell.open && !cell.mine && !cell.flag));

const won = mines.create(() => 0);
mines.reveal(won, 0);
for (let i = 0; i < 81; i++) {
  if (!won.cells[i].mine) mines.reveal(won, i);
}
assert.strictEqual(won.win, true);
assert.strictEqual(won.status, "Cleared");
assert.ok(won.cells.every((cell) => cell.open));

function mineCount(game, i) {
  return mines.neighbors(i).reduce((n, j) => n + (game.cells[j].mine ? 1 : 0), 0);
}
const counted = mines.create(() => 0.37);
mines.reveal(counted, 20);
assert.strictEqual(counted.cells[20].mine, false);
let mineTotal = 0;
for (let i = 0; i < 81; i++) {
  if (counted.cells[i].mine) {
    mineTotal++;
    assert.strictEqual(counted.cells[i].open, false);
    continue;
  }
  assert.strictEqual(counted.cells[i].n, mineCount(counted, i), "neighbour count " + i);
}
assert.strictEqual(mineTotal, 10);
for (let i = 0; i < 81; i++) {
  const cell = counted.cells[i];
  if (!cell.open || cell.n !== 0) continue;
  for (const j of mines.neighbors(i)) assert.strictEqual(counted.cells[j].open, true, "flood " + i);
}

const blocked = mines.create(() => 0.2);
mines.flag(blocked, 8);
mines.reveal(blocked, 0);
assert.strictEqual(blocked.cells[8].flag, true);
assert.strictEqual(blocked.cells[8].open, false);
mines.flag(blocked, 8);
assert.strictEqual(blocked.cells[8].flag, false);

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
assert.ok(text("Memory").includes("8.0 GB"));
assert.ok(text("Memory").includes("32.0 GB"));
assert.ok(text("GPU").includes("RTX 3090"));
assert.ok(text("GPU").includes("1024 / 24576 MiB"));
assert.ok(text("GPU").includes("42 °C"));
assert.ok(text("Disk").includes("System"));
assert.ok(text("Disk").includes("free"));
assert.ok(text("Model").includes("qwen"));
assert.ok(text("Model").includes("The model is not running."));

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
