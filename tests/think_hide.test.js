"use strict";
// 0.5.5: a thinking model's reasoning (Qwen3.5) never shows in the chat bubble, not even while streaming.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const cut = (a, b) => { const i = src.indexOf(a); assert.ok(i >= 0, a); return src.slice(i, src.indexOf(b, i)); };
const thinkSrc = cut("function splitThink", "function renderConvs");
const textSrc = cut("function textOfMessage", "function answerFromChat");
const streamSrc = cut("async function takeChatStream", "function messagesForRequest");
const { splitThink, stripThink } = new Function(thinkSrc + "\nreturn { splitThink, stripThink };")();

assert.deepStrictEqual(splitThink("Hello"), { answer: "Hello", think: "" });
assert.deepStrictEqual(splitThink("<think>plan it</think>\n\nHi!"), { answer: "\n\nHi!", think: "plan it" });
assert.deepStrictEqual(splitThink("Okay, the user wants hi.\n</think>\n\nHi!"), { answer: "\n\nHi!", think: "Okay, the user wants hi." });
assert.deepStrictEqual(splitThink("<think>still going"), { answer: "", think: "still going" });
assert.deepStrictEqual(splitThink("<THINK>a</THINK>b<think>c"), { answer: "b", think: "a\n\nc" });
assert.strictEqual(stripThink("x</think>y</think>z"), "z");
assert.strictEqual(stripThink(null), "");

// Drive takeChatStream with a fake SSE stream: reasoning first, then the answer.
function sse(events) {
  const enc = new TextEncoder(); let k = 0;
  const chunks = events.map((e) => enc.encode("data: " + JSON.stringify(e) + "\n\n"));
  return { status: 200, ok: true, headers: { get: () => "text/event-stream" }, body: { getReader: () => ({ read: async () => (k < chunks.length ? { done: false, value: chunks[k++] } : { done: true }), cancel() {} }) } };
}
function run(events, json) {
  const make = new Function("fetch", "authHeaders", "dropEmptyPlaceholder",
    "let sendGen = 1, userStopGen = 0;\n" + textSrc + thinkSrc + streamSrc + "\nreturn takeChatStream;");
  const fetch = async () => (json ? { status: 200, ok: true, headers: { get: () => "application/json" }, json: async () => json, body: null } : sse(events));
  const drop = (t) => (String(t || "").trim() === "(empty response)" ? "" : String(t || ""));
  return make(fetch, (h) => h, drop);
}
(async () => {
  const shown = []; let thinks = 0;
  const take = run([
    { reasoning: "The user says hi. " }, { reasoning: "I should greet." },
    { content: "Hel" }, { content: "lo!" }, { done: true, content: "Hello!", reasoning: "The user says hi. I should greet." },
  ]);
  const acc = await take(1, { signal: { aborted: false } }, {}, (s) => shown.push(s), { onThink: () => thinks++ });
  assert.deepStrictEqual(shown, ["Hel", "Hello!", "Hello!"], "only answer text is ever painted");
  assert.ok(thinks >= 2, "Thinking… while only reasoning has arrived");
  assert.strictEqual(acc.shown, "Hello!");
  assert.strictEqual(acc.think, "The user says hi. I should greet.");

  // Reasoning inline in content (no reasoning_format): never painted, kept for Show reasoning.
  const shown2 = [];
  const acc2 = await run([{ content: "<think>hmm" }, { content: " ok</think>" }, { content: "Sure." }])(1, { signal: { aborted: false } }, {}, (s) => shown2.push(s), {});
  assert.deepStrictEqual(shown2, ["Sure."]);
  assert.strictEqual(acc2.shown, "Sure.");
  assert.strictEqual(acc2.think, "hmm ok");

  // Only reasoning (token budget spent): the reply is empty, so send() retries with thinking off
  // instead of showing the reasoning as the answer.
  const acc3 = await run([{ reasoning: "long thoughts" }, { done: true }])(1, { signal: { aborted: false } }, {}, () => assert.fail("painted"), {});
  assert.strictEqual(acc3.shown, "");
  assert.ok(/if \(!reply && gen === sendGen && userStopGen !== gen\)[\s\S]{0,200}enable_thinking: false/.test(src));

  // The bubble: answer only, reasoning in a collapsed <details>.
  const mh = cut("function msgHtml", "function renderThread");
  assert.ok(mh.includes('<details class="reasoning"><summary>Show reasoning</summary>') && !/<details[^>]* open/.test(mh));
  assert.ok(mh.includes("md(parts.answer)") && !mh.includes('md(m.t || "")'));
  assert.ok(/pend\.think = acc\.think/.test(src));
  assert.ok(/messages\.push\(\{ role: "assistant", content: reply \}\)/.test(src), "history sends the answer only");
  const css = fs.readFileSync(path.join(__dirname, "..", "ui", "style.css"), "utf8");
  assert.ok(css.includes("details.reasoning") && css.includes(".thinkNote"));
  console.log("think_hide ok");
})().catch((e) => { console.error(e); process.exit(1); });
