/* Read piles and click or drag cards in the visible Solitaire tab.
 * Does not change Solitaire rules. Cards are children of .cardTable, not of
 * .pile, so each card is matched to a pile by where it sits on screen.
 * Card names: rank A 2-9 T J Q K, then suit S H D C. "#" is a face-down card.
 */
(function () {
  "use strict";
  const NAMES = ["stock", "waste", "f1", "f2", "f3", "f4", "t1", "t2", "t3", "t4", "t5", "t6", "t7"];
  const SUITS = { 1: "S", 2: "H", 3: "D", 4: "C" };
  const RANKS = { 1: "A", 10: "T", 100: "J", 101: "Q", 102: "K" };
  const SETTLE_MS = 300;

  function pileEls() {
    return Array.prototype.slice.call(document.querySelectorAll(".pile"));
  }

  function cardName(el) {
    const match = String(el.className || "").match(/\bs(\d)c\d+r(\d+)\b/);
    if (!match) return "?";
    const rank = RANKS[Number(match[2])] || match[2];
    return rank + (SUITS[Number(match[1])] || "?");
  }

  function layout() {
    const piles = pileEls().map(function (el, i) {
      return { name: NAMES[i] || "p" + i, el: el, rect: el.getBoundingClientRect(), cards: [] };
    });
    const cards = Array.prototype.slice.call(document.querySelectorAll(".cardTable .card"));
    cards.forEach(function (el) {
      if (el.classList.contains("dragging")) return;
      const r = el.getBoundingClientRect();
      let best = null;
      piles.forEach(function (p) {
        if (p.rect.top > r.top + 6 || p.rect.left > r.left + 6) return;
        if (!best || p.rect.top > best.rect.top + 6 ||
            (Math.abs(p.rect.top - best.rect.top) <= 6 && p.rect.left > best.rect.left)) best = p;
      });
      if (best) best.cards.push({ el: el, z: Number(el.style.zIndex) || 0, up: el.classList.contains("faceUp") });
    });
    piles.forEach(function (p) { p.cards.sort(function (a, b) { return a.z - b.z; }); });
    return piles;
  }

  function find(piles, name) {
    for (let i = 0; i < piles.length; i++) if (piles[i].name === name) return piles[i];
    return null;
  }

  function snapshot() {
    const piles = layout();
    const out = {};
    piles.forEach(function (p) {
      const shown = p.name === "stock" ? [] : p.cards.filter(function (c) { return c.up; }).map(function (c) { return cardName(c.el); });
      const down = p.cards.length - shown.length;
      out[p.name] = (down ? "#".repeat(Math.min(down, 24)) + " " : "") + (shown.join(" ") || (down ? "" : "-"));
      out[p.name] = out[p.name].trim();
    });
    const stock = find(piles, "stock");
    const score = document.querySelector(".gameScore");
    return {
      piles: out,
      stock_count: stock ? stock.cards.length : 0,
      won: !!document.querySelector(".card.won"),
      score: score ? String(score.textContent || "").trim() : "",
      help: "Top card is last. f1-f4 are foundations, t1-t7 tableau. #=face down.",
    };
  }

  function fire(target, type, x, y) {
    target.dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window, clientX: x, clientY: y,
      button: 0, buttons: type === "mouseup" ? 0 : 1,
    }));
  }

  function clickEl(el) {
    const r = el.getBoundingClientRect();
    const x = r.left + Math.min(10, r.width / 2);
    const y = r.top + Math.min(10, r.height / 2);
    fire(el, "mousedown", x, y);
    fire(window, "mouseup", x, y);
  }

  function dragEl(el, toPile) {
    const a = el.getBoundingClientRect();
    const target = toPile.cards.length ? toPile.cards[toPile.cards.length - 1].el : toPile.el;
    const b = target.getBoundingClientRect();
    // Land the card exactly on the target so it overlaps no other pile.
    const sx = a.left + 10, sy = a.top + 10;
    const ex = b.left + 10, ey = b.top + 10;
    fire(el, "mousedown", sx, sy);
    for (let i = 1; i <= 6; i++) {
      fire(window, "mousemove", sx + (ex - sx) * i / 6, sy + (ey - sy) * i / 6);
    }
    fire(window, "mouseup", ex, ey);
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function fingerprint() {
    return layout().map(key).join("|");
  }

  // Wait for animations and auto-moves to finish, then return value().
  async function settle(value) {
    await sleep(SETTLE_MS);
    let last = fingerprint();
    for (let i = 0; i < 20; i++) {
      await sleep(150);
      const now = fingerprint();
      if (now === last) break;
      last = now;
    }
    return value();
  }

  function key(p) {
    return p ? p.cards.map(function (c) { return cardName(c.el) + (c.up ? "+" : "-"); }).join(",") : "";
  }

  function fail(error) {
    return { ok: false, error: error, state: snapshot() };
  }

  async function doMove(action) {
    const parts = String(action.move).split("->").map(function (s) { return s.trim(); });
    if (parts.length !== 2) return fail("bad_move: use \"t3->f1\"");
    let piles = layout();
    let from = find(piles, parts[0]);
    let to = find(piles, parts[1]);
    if (!from || !to || from === to || parts[0] === "stock") return fail("bad_pile");
    const up = from.cards.filter(function (c) { return c.up; });
    if (!up.length) return fail("no_face_up_card");
    // Try the named card, else the top card, then longer runs (tableau to tableau).
    let tries = up.slice().reverse();
    if (parts[1].charAt(0) === "f") tries = tries.slice(0, 1);
    if (typeof action.card === "string") {
      const want = action.card.toUpperCase().replace("10", "T");
      tries = up.filter(function (c) { return cardName(c.el) === want; });
      if (!tries.length) return fail("card_not_face_up_on_" + parts[0]);
    }
    for (let i = 0; i < tries.length; i++) {
      const moving = tries[i].el;
      dragEl(moving, to);
      await settle(function () { return null; });
      piles = layout();
      to = find(piles, parts[1]);
      const landed = to && to.cards.some(function (c) { return c.el === moving; });
      if (landed) return snapshot();
      const still = find(piles, parts[0]).cards.some(function (c) { return c.el === moving; });
      if (!still) {
        // The game drops an illegal card on the nearest legal pile instead.
        // That is not the move asked for, so take it back.
        const undo = document.getElementById("undoButton");
        if (undo) undo.click();
        await settle(function () { return null; });
        return fail("illegal_move");
      }
    }
    return fail("illegal_move");
  }

  async function act(action) {
    action = action || {};
    if (action.draw) {
      const stock = find(layout(), "stock");
      if (!stock) return fail("no_stock");
      const top = stock.cards.length ? stock.cards[stock.cards.length - 1].el : stock.el;
      clickEl(top);
      return settle(snapshot);
    }
    if (typeof action.click === "string") {
      const pile = find(layout(), action.click);
      if (!pile) return fail("bad_pile");
      const top = pile.cards.length ? pile.cards[pile.cards.length - 1].el : pile.el;
      clickEl(top);
      return settle(snapshot);
    }
    if (typeof action.move === "string") return doMove(action);
    const button = action.new_game ? "newGameButton" : action.undo ? "undoButton" : action.redo ? "redoButton" : "";
    if (button) {
      const el = document.getElementById(button);
      if (!el) return fail("no_button");
      el.click();
      return settle(snapshot);
    }
    return fail("unknown_action: use move, draw, click, undo, redo, or new_game");
  }

  window.stickllmApp = {
    describe: function () {
      return {
        id: "solitaire",
        actions: ["move", "draw", "click", "undo", "redo", "new_game"],
        examples: [{ move: "t3->f1" }, { move: "t2->t5", card: "9H" }, { draw: true }, { click: "t4" }, { undo: true }],
      };
    },
    state: snapshot,
    act: act,
  };
})();
