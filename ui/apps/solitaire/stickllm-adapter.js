/* Read piles and click or drag cards. Does not change Solitaire rules. */
(function () {
  "use strict";
  const RANKS = { 1: "A", 11: "J", 12: "Q", 13: "K" };

  function piles() {
    return Array.prototype.slice.call(document.querySelectorAll(".pile"));
  }

  function cardName(el) {
    if (!el) return "";
    const match = String(el.className || "").match(/s(\d+)c(\d+)r(\d+)/);
    if (!match) return el.classList.contains("faceUp") ? "?" : "";
    const rank = RANKS[Number(match[3])] || match[3];
    return "s" + match[1] + rank;
  }

  function topCard(pile) {
    const cards = pile ? pile.querySelectorAll(".card") : [];
    if (!cards.length) return "-";
    const top = cards[cards.length - 1];
    if (!top.classList.contains("faceUp")) return "#";
    return cardName(top) || "?";
  }

  function describePiles() {
    const all = piles();
    const names = ["stock", "waste", "f1", "f2", "f3", "f4", "t1", "t2", "t3", "t4", "t5", "t6", "t7"];
    const out = {};
    all.forEach(function (pile, i) { out[names[i] || ("p" + i)] = topCard(pile); });
    return out;
  }

  function pileByName(name) {
    const all = piles();
    const map = { stock: 0, waste: 1, f1: 2, f2: 3, f3: 4, f4: 5, t1: 6, t2: 7, t3: 8, t4: 9, t5: 10, t6: 11, t7: 12 };
    const index = map[name];
    return index == null ? null : all[index] || null;
  }

  function fire(el, type, x, y) {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, buttons: type === "mouseup" ? 0 : 1 }));
  }

  window.stickllmApp = {
    describe: function () {
      return { id: "solitaire", actions: ["move", "draw"] };
    },
    state: function () {
      return { piles: describePiles() };
    },
    act: function (action) {
      if (action && action.draw) {
        const stock = pileByName("stock");
        if (!stock) return { ok: false, error: "no_stock", state: { piles: describePiles() } };
        const rect = stock.getBoundingClientRect();
        fire(stock, "mousedown", rect.left + 8, rect.top + 8);
        fire(stock, "mouseup", rect.left + 8, rect.top + 8);
        return { piles: describePiles() };
      }
      const move = action && typeof action.move === "string" ? action.move : "";
      const parts = move.split("->");
      if (parts.length !== 2) return { ok: false, error: "bad_move", state: { piles: describePiles() } };
      const from = pileByName(parts[0]);
      const to = pileByName(parts[1]);
      if (!from || !to) return { ok: false, error: "bad_pile", state: { piles: describePiles() } };
      const cards = from.querySelectorAll(".card");
      const card = cards.length ? cards[cards.length - 1] : from;
      const a = card.getBoundingClientRect();
      const b = to.getBoundingClientRect();
      fire(card, "mousedown", a.left + 8, a.top + 8);
      fire(document, "mousemove", b.left + 12, b.top + 12);
      fire(to, "mouseup", b.left + 12, b.top + 12);
      return { piles: describePiles() };
    },
  };
})();
