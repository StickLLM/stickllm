/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StickSolitaire = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const RANKS = "A23456789TJQK";
  const SUITS = ["S", "H", "D", "C"];
  const RED = { H: 1, D: 1 };

  function create(rng) {
    return {
      stock: [],
      waste: [],
      found: [[], [], [], []],
      tab: [[], [], [], [], [], [], []],
      sel: null,
      status: "Klondike",
      rng: rng || Math.random,
    };
  }

  function rank(card) { return RANKS.indexOf(card[0]); }
  function suit(card) { return card[1]; }
  function color(card) { return RED[suit(card)] ? "red" : "black"; }
  function label(card) { return (card[0] === "T" ? "10" : card[0]) + suit(card); }

  function deck(rng) {
    const cards = [];
    SUITS.forEach((s) => { for (const r of RANKS) cards.push(r + s); });
    for (let i = cards.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      const tmp = cards[i];
      cards[i] = cards[j];
      cards[j] = tmp;
    }
    return cards;
  }

  function deal(game) {
    const cards = deck(game.rng);
    game.stock = [];
    game.waste = [];
    game.found = [[], [], [], []];
    game.tab = [[], [], [], [], [], [], []];
    game.sel = null;
    game.status = "Klondike";
    for (let i = 0; i < 7; i++) {
      for (let j = 0; j <= i; j++) game.tab[i].push({ card: cards.pop(), up: j === i });
    }
    while (cards.length) game.stock.push(cards.pop());
    return game;
  }

  function canTab(card, dest) {
    if (!dest.length) return rank(card) === 12;
    const top = dest[dest.length - 1];
    if (!top.up) return false;
    return color(card) !== color(top.card) && rank(card) === rank(top.card) - 1;
  }

  function canFound(card, dest) {
    if (!dest.length) return rank(card) === 0;
    const top = dest[dest.length - 1];
    return suit(card) === suit(top) && rank(card) === rank(top) + 1;
  }

  function takeSel(game) {
    const sel = game.sel;
    if (!sel) return null;
    if (sel.kind === "waste") {
      if (!game.waste.length) return null;
      return [game.waste.pop()];
    }
    if (sel.kind === "tab") {
      const pile = game.tab[sel.pile];
      const at = pile.findIndex((c) => c === sel.card);
      if (at < 0 || !pile[at].up) return null;
      return pile.splice(at);
    }
    return null;
  }

  function putBack(game, cards) {
    const sel = game.sel;
    if (!sel || !cards || !cards.length) return;
    if (sel.kind === "waste") game.waste.push(cards[0].card || cards[0]);
    else game.tab[sel.pile].push(...cards);
  }

  function movingOf(cards) {
    return cards.map((c) => (c && c.card ? c : { card: c, up: true }));
  }

  function tryMove(game, target) {
    const cards = takeSel(game);
    if (!cards) { game.sel = null; return game; }
    const moving = movingOf(cards);
    const card = moving[0].card;
    let ok = false;
    if (target.kind === "found" && moving.length === 1 && canFound(card, game.found[target.pile])) {
      game.found[target.pile].push(card);
      ok = true;
    } else if (target.kind === "tab" && canTab(card, game.tab[target.pile])) {
      game.tab[target.pile].push(...moving);
      ok = true;
    }
    if (!ok) putBack(game, cards);
    else if (game.sel && game.sel.kind === "tab") {
      const pile = game.tab[game.sel.pile];
      if (pile.length && !pile[pile.length - 1].up) pile[pile.length - 1].up = true;
    }
    game.sel = null;
    if (game.found.every((pile) => pile.length === 13)) game.status = "Done";
    return game;
  }

  function drawStock(game) {
    if (game.stock.length) game.waste.push(game.stock.pop());
    else {
      game.stock = game.waste.slice().reverse();
      game.waste = [];
    }
    game.sel = null;
    return game;
  }

  function boot() {
    if (typeof document === "undefined") return;
    const top = document.getElementById("toprow");
    const table = document.getElementById("tableau");
    const msg = document.getElementById("msg");
    const again = document.getElementById("again");
    if (!top || !table || !msg || !again) return;
    const game = create();

    function button(text, className, onclick) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = className;
      el.textContent = text;
      el.addEventListener("click", onclick);
      el.addEventListener("contextmenu", (ev) => ev.preventDefault());
      return el;
    }

    function render() {
      msg.textContent = game.status;
      top.innerHTML = "";
      table.innerHTML = "";
      top.appendChild(button(game.stock.length ? "Draw" : "Turn", "slot", () => { drawStock(game); render(); }));
      const wasteTop = game.waste[game.waste.length - 1];
      top.appendChild(button(
        wasteTop ? label(wasteTop) : "Waste",
        wasteTop ? "card " + color(wasteTop) + (game.sel && game.sel.kind === "waste" ? " on" : "") : "slot",
        () => {
          if (!wasteTop) return;
          if (game.sel && game.sel.kind === "waste") game.sel = null;
          else game.sel = { kind: "waste" };
          render();
        }
      ));
      game.found.forEach((pile, i) => {
        const topCard = pile[pile.length - 1];
        top.appendChild(button(
          topCard ? label(topCard) : "A",
          topCard ? "card " + color(topCard) : "slot",
          () => { tryMove(game, { kind: "found", pile: i }); render(); }
        ));
      });
      game.tab.forEach((pile, i) => {
        const col = document.createElement("div");
        col.className = "pile stack";
        if (!pile.length) {
          col.appendChild(button("", "slot", () => { tryMove(game, { kind: "tab", pile: i }); render(); }));
        }
        pile.forEach((item, n) => {
          const face = item.up ? label(item.card) : "";
          const on = game.sel && game.sel.kind === "tab" && game.sel.card === item;
          const el = button(face, "card" + (item.up ? " " + color(item.card) : " down") + (on ? " on" : ""), () => {
            if (!item.up) return;
            if (game.sel && game.sel.kind === "tab" && game.sel.card === item) {
              game.sel = null;
              render();
              return;
            }
            if (game.sel) tryMove(game, { kind: "tab", pile: i });
            else game.sel = { kind: "tab", pile: i, card: item };
            render();
          });
          if (n) el.style.marginTop = item.up ? "-64px" : "-72px";
          col.appendChild(el);
        });
        table.appendChild(col);
      });
    }

    again.addEventListener("click", () => { deal(game); render(); });
    deal(game);
    render();
  }

  boot();
  return { create, deal, canTab, canFound, tryMove, drawStock, label, rank, color };
});
