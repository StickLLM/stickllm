/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StickMines = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const W = 9, H = 9, MINES = 10;

  function create(rng) {
    const cells = [];
    for (let i = 0; i < W * H; i++) cells.push({ mine: false, open: false, flag: false, n: 0 });
    return {
      w: W,
      h: H,
      mines: MINES,
      cells: cells,
      started: false,
      over: false,
      win: false,
      left: W * H - MINES,
      status: MINES + " mines",
      rng: rng || Math.random,
    };
  }

  function idx(x, y) { return y * W + x; }

  function neighbors(i) {
    const x = i % W, y = (i / W) | 0, out = [];
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < W && ny < H) out.push(idx(nx, ny));
      }
    }
    return out;
  }

  function place(game, safe) {
    const bag = [];
    for (let i = 0; i < W * H; i++) if (i !== safe) bag.push(i);
    for (let i = bag.length - 1; i > 0; i--) {
      const j = Math.floor(game.rng() * (i + 1));
      const tmp = bag[i];
      bag[i] = bag[j];
      bag[j] = tmp;
    }
    bag.slice(0, MINES).forEach((i) => { game.cells[i].mine = true; });
    game.cells.forEach((cell, i) => {
      if (cell.mine) { cell.n = 0; return; }
      cell.n = neighbors(i).reduce((n, j) => n + (game.cells[j].mine ? 1 : 0), 0);
    });
  }

  function flood(game, i) {
    const stack = [i];
    while (stack.length) {
      const cur = stack.pop();
      const cell = game.cells[cur];
      if (!cell || cell.open || cell.flag) continue;
      cell.open = true;
      game.left--;
      if (cell.n === 0 && !cell.mine) {
        neighbors(cur).forEach((n) => { if (!game.cells[n].open) stack.push(n); });
      }
    }
  }

  function finish(game, win) {
    game.over = true;
    game.win = win;
    game.cells.forEach((cell) => { if (cell.mine) cell.open = true; });
    game.status = win ? "Cleared" : "You hit a mine";
  }

  function reveal(game, i) {
    if (game.over) return game;
    const cell = game.cells[i];
    if (!cell || cell.open || cell.flag) return game;
    if (!game.started) { place(game, i); game.started = true; }
    if (cell.mine) {
      cell.open = true;
      finish(game, false);
      return game;
    }
    flood(game, i);
    if (game.left <= 0) finish(game, true);
    return game;
  }

  function flag(game, i) {
    if (game.over) return game;
    const cell = game.cells[i];
    if (!cell || cell.open) return game;
    cell.flag = !cell.flag;
    return game;
  }

  function restart(rng) { return create(rng); }

  function boot() {
    if (typeof document === "undefined") return;
    const board = document.getElementById("board");
    const status = document.getElementById("status");
    const again = document.getElementById("again");
    if (!board || !status || !again) return;
    let game = create();

    function paint() {
      status.textContent = game.status;
      status.className = game.win ? "win" : game.over ? "lose" : "";
      game.cells.forEach((cell, i) => {
        const btn = board.children[i];
        if (!btn) return;
        btn.textContent = "";
        btn.className = "cell";
        if (cell.open) {
          btn.classList.add("open");
          if (cell.mine) { btn.textContent = "•"; btn.classList.add("mine"); }
          else if (cell.n) btn.textContent = String(cell.n);
        } else if (cell.flag) btn.textContent = "⚑";
      });
    }

    function build() {
      board.innerHTML = "";
      for (let i = 0; i < W * H; i++) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "cell";
        el.setAttribute("aria-label", "Cell " + (i + 1));
        el.addEventListener("pointerdown", (ev) => {
          if (ev.button !== 2) return;
          ev.preventDefault();
          el._right = true;
          flag(game, i);
          paint();
          setTimeout(() => { el._right = false; }, 0);
        });
        el.addEventListener("click", (ev) => {
          if (el._right || (ev.button != null && ev.button !== 0)) return;
          reveal(game, i);
          paint();
        });
        el.addEventListener("contextmenu", (ev) => {
          ev.preventDefault();
          if (el._right) return;
          flag(game, i);
          paint();
        });
        board.appendChild(el);
      }
      paint();
    }

    again.addEventListener("click", () => {
      game = restart();
      build();
    });
    build();
  }

  boot();
  return { create, reveal, flag, restart, neighbors };
});
