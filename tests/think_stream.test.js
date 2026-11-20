"use strict";
// 0.5.6: 4B reasoning is hidden while streaming (orphan </think>, plain "Thinking Process:").
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const start = src.indexOf("function splitThink");
const st = src.indexOf("function stripThink");
const block = src.slice(start, st + src.slice(st).indexOf("\n}\n") + 3);
const api = new Function(block + "\nreturn { splitThink, stripThink, streamingAnswer };")();
assert.strictEqual(api.streamingAnswer("Thinking Process:\n1. The user wants"), "");
assert.strictEqual(api.streamingAnswer("Okay, the user is asking about"), "");
assert.strictEqual(api.streamingAnswer("Okay, the user asks.\n</think>\n\nParis."), "\n\nParis.");
assert.strictEqual(api.streamingAnswer("<think>hmm"), "");
assert.strictEqual(api.streamingAnswer("Paris is the capital."), "Paris is the capital.");
assert.strictEqual(api.stripThink("Thinking Process: x"), "Thinking Process: x", "no </think> at the end: shown");
assert.ok(src.includes("dropEmptyPlaceholder(streamingAnswer(content))"));
console.log("think_stream ok");
