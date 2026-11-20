"use strict";
// Desktop layout logic (ui/desktop-core.js) against a fake WinBox.
const assert = require("assert");
const path = require("path");
const core = require(path.join(__dirname, "..", "ui", "desktop-core.js"));

// ---- layout detection ----
const big = { pointerFine: true, hover: true, width: 1920, height: 1080 };
assert.strictEqual(core.detectLayout(big), "desktop");
assert.strictEqual(core.detectLayout({ ...big, width: 1023 }), "classic", "narrow window");
assert.strictEqual(core.detectLayout({ ...big, height: 599 }), "classic", "short window");
assert.strictEqual(core.detectLayout({ ...big, pointerFine: false }), "classic", "touch screen");
assert.strictEqual(core.detectLayout({ ...big, hover: false }), "classic", "no hover (tablet + pen)");
assert.strictEqual(core.detectLayout({ pointerFine: false, hover: false, width: 390, height: 844 }), "classic", "phone");
assert.strictEqual(core.detectLayout({ pointerFine: false, width: 390, height: 844, override: "desktop" }), "desktop");
assert.strictEqual(core.detectLayout({ ...big, override: "classic" }), "classic");
assert.strictEqual(core.detectLayout({ ...big, override: "bogus" }), "desktop", "bad override = auto");
assert.strictEqual(core.normOverride("DESKTOP"), "desktop");
assert.strictEqual(core.normOverride(null), "auto");

// ---- override storage ----
const ms = core.memStore();
assert.strictEqual(core.readOverride(ms), "auto");
core.writeOverride(ms, "classic");
assert.strictEqual(ms.get(core.LAYOUT_KEY), "classic");
core.writeOverride(ms, "<script>");
assert.strictEqual(core.readOverride(ms), "auto");
const brokenLs = core.localStore({ getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } });
assert.strictEqual(core.readOverride(brokenLs), "auto", "private mode storage errors fall back");
core.writeOverride(brokenLs, "desktop");
assert.deepStrictEqual(core.loadState({ get: () => "{not json" }), { geom: {} });

// ---- geometry ----
const area = { w: 1920, h: 1032 };
assert.deepStrictEqual(core.clampGeom({ x: -50, y: -10, w: 800, h: 600 }, area), { x: 0, y: 0, w: 800, h: 600 });
assert.deepStrictEqual(core.clampGeom({ x: 1800, y: 1000, w: 800, h: 600 }, area), { x: 1120, y: 432, w: 800, h: 600 });
assert.deepStrictEqual(core.clampGeom({ x: 0, y: 0, w: 5000, h: 5000 }, area), { x: 0, y: 0, w: 1920, h: 1032 });
const tiny = core.clampGeom({ x: 10, y: 10, w: 10, h: 10 }, area);
assert.ok(tiny.w >= 240 && tiny.h >= 160, "minimum window size");
const c0 = core.cascade({ w: 800, h: 560 }, 0, area), c1 = core.cascade({ w: 800, h: 560 }, 1, area);
assert.strictEqual(c1.x - c0.x, 28); assert.strictEqual(c1.y - c0.y, 28);
for (let n = 0; n < 20; n++) {
  const g = core.cascade({ w: 1000, h: 900 }, n, { w: 1024, h: 552 });
  assert.ok(g.x >= 0 && g.y >= 0 && g.x + g.w <= 1024 && g.y + g.h <= 552, "cascade stays on screen");
}

// ---- taskbar rule ----
assert.strictEqual(core.taskbarAction({ min: true, focused: false }), "restore");
assert.strictEqual(core.taskbarAction({ min: false, focused: true }), "minimize");
assert.strictEqual(core.taskbarAction({ min: false, focused: false }), "focus");
assert.strictEqual(core.taskbarAction(null), "none");

// ---- window manager with a fake WinBox ----
const all = [];
class FakeWinBox {
  constructor(p) {
    Object.assign(this, { p, id: p.id, title: p.title, x: p.x, y: p.y, width: p.width, height: p.height, min: false, max: false, focused: false, closed: false });
    all.push(this);
  }
  focus() {
    if (this.focused) return this;
    for (const w of all) if (w !== this && w.focused) { w.focused = false; w.p.onblur && w.p.onblur.call(w); }
    this.focused = true; this.p.onfocus && this.p.onfocus.call(this); return this;
  }
  blur() { if (this.focused) { this.focused = false; this.p.onblur && this.p.onblur.call(this); } return this; }
  minimize() { this.min = true; this.blur(); this.p.onminimize && this.p.onminimize.call(this); return this; }
  restore() {
    if (this.min) this.min = false; else if (this.max) this.max = false;
    this.p.onrestore && this.p.onrestore.call(this); return this;
  }
  maximize() { this.max = true; this.p.onmaximize && this.p.onmaximize.call(this); return this; }
  move(x, y) { this.x = x; this.y = y; this.p.onmove && this.p.onmove.call(this, x, y); return this; }
  resize(w, h) { this.width = w; this.height = h; this.p.onresize && this.p.onresize.call(this, w, h); return this; }
  close(force) {
    if (this.p.onclose && this.p.onclose.call(this, force)) return true;
    this.closed = true; this.focused = false; all.splice(all.indexOf(this), 1); return false;
  }
}
let changes = 0;
const store = core.memStore();
let scr = { w: 1920, h: 1032 };
const created = [];
const wm = new core.WindowManager({
  create: (p, spec) => { const w = new FakeWinBox(p); created.push({ p, spec }); return w; },
  area: () => scr, store, onchange: () => { changes++; },
});
const chat = wm.open({ id: "chat", title: "Chat", w: 1000, h: 720, pinned: true });
const notepad = wm.open({ id: "notepad", title: "Notepad", w: 780, h: 540 });
const calc = wm.open({ id: "calculator", title: "Calculator", w: 360, h: 560 });
assert.ok(changes > 0);
assert.strictEqual(created[1].p.bottom, core.TASKBAR_H, "maximise stops at the taskbar");
assert.strictEqual(created[1].p.id, "win-notepad");
assert.ok(created[1].p.minwidth >= 240);
assert.deepStrictEqual(wm.list().map((w) => w.id), ["chat", "notepad", "calculator"], "pinned chat first, then open order");
assert.strictEqual(wm.activeId(), "calculator", "newest window is active");
assert.deepStrictEqual(wm.list().filter((w) => w.active).map((w) => w.id), ["calculator"], "exactly one active");

// Opening an open app reuses its window.
assert.strictEqual(wm.open({ id: "notepad", title: "Notepad" }), notepad);
assert.strictEqual(created.length, 3);
assert.strictEqual(wm.activeId(), "notepad");

// Taskbar: active -> minimise; minimised -> restore + focus; background -> focus.
assert.strictEqual(wm.taskbarClick("notepad"), "minimize");
assert.ok(notepad.min && !notepad.focused);
assert.strictEqual(wm.activeId(), null, "a minimised window is never the active one");
assert.ok(wm.list().find((w) => w.id === "notepad").min);
assert.strictEqual(wm.taskbarClick("notepad"), "restore");
assert.ok(!notepad.min && notepad.focused);
assert.strictEqual(wm.taskbarClick("chat"), "focus");
assert.strictEqual(wm.activeId(), "chat");

// Maximise / restore, and the saved geometry.
calc.move(100, 120); calc.resize(400, 600);
wm.toggleMax("calculator");
assert.ok(calc.max && wm.list().find((w) => w.id === "calculator").max);
assert.strictEqual(JSON.parse(store.get(core.STATE_KEY)).geom.calculator.max, true);
wm.toggleMax("calculator");
assert.ok(!calc.max);
const saved = JSON.parse(store.get(core.STATE_KEY)).geom.calculator;
assert.deepStrictEqual(saved, { x: 100, y: 120, w: 400, h: 600, max: false });
assert.ok(!JSON.stringify(JSON.parse(store.get(core.STATE_KEY))).match(/title|url|text/), "only geometry is stored");

// Close: app windows go; the pinned chat window only minimises.
assert.strictEqual(wm.close("calculator"), true);
assert.ok(!wm.has("calculator") && calc.closed);
assert.strictEqual(wm.close("chat"), false);
assert.ok(wm.has("chat") && chat.min && !chat.closed, "closing chat minimises it");
wm.focus("chat");
assert.ok(!chat.min);

// Reopen restores the remembered geometry (clamped to the current screen).
const calc2 = wm.open({ id: "calculator", title: "Calculator", w: 360, h: 560 });
assert.deepStrictEqual([calc2.x, calc2.y, calc2.width, calc2.height], [100, 120, 400, 600]);
scr = { w: 1100, h: 552 };
const wm2 = new core.WindowManager({ create: (p) => new FakeWinBox(p), area: () => scr, store });
const calc3 = wm2.open({ id: "calculator", title: "Calculator" });
assert.ok(calc3.y + calc3.height <= 552 && calc3.x + calc3.width <= 1100, "saved geometry clamped to a smaller screen");
wm2.closeAll(true);

// fit(): browser window shrinks -> windows pulled back on screen.
notepad.move(1500, 900);
scr = { w: 1280, h: 672 };
wm.fit();
assert.ok(notepad.x + notepad.width <= 1280 && notepad.y + notepad.height <= 672);

// next(): cycles in taskbar order and restores minimised windows.
wm.minimize("notepad");
wm.focus("chat");
assert.strictEqual(wm.next(), "notepad");
assert.ok(!notepad.min && wm.activeId() === "notepad");

// Lock: closeAll() closes every app window, keeps the pinned chat window.
wm.closeAll();
assert.deepStrictEqual(wm.list().map((w) => w.id), ["chat"]);
assert.ok(notepad.closed && calc2.closed && !chat.closed);
// Leaving the layout: closeAll(true) closes chat too.
wm.closeAll(true);
assert.deepStrictEqual(wm.list(), []);
assert.ok(chat.closed);

console.log("desktop_ui.test.js: ok");
