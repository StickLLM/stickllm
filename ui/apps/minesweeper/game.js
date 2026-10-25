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

  const FLAG = '<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><path fill="#dc2626" d="M6 3h2v18H6z"/><path fill="#dc2626" d="M8 4h11l-3 4 3 4H8z"/></svg>';
  const MINE = '<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5" fill="#1c1917"/><path stroke="#1c1917" stroke-width="2" stroke-linecap="round" d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></svg>';

  function boot() {
    if (typeof document === "undefined") return;
    const board = document.getElementById("board");
    const status = document.getElementById("status");
    const again = document.getElementById("again");
    if (!board || !status || !again) return;
    let game = create();

    function paint() {
      const flags = game.cells.reduce((n, cell) => n + (cell.flag ? 1 : 0), 0);
      status.textContent = game.over ? game.status : String(game.mines - flags) + " mines";
      status.className = game.win ? "win" : game.over ? "lose" : "";
      document.body.dataset.state = game.win ? "win" : game.over ? "lose" : "";
      game.cells.forEach((cell, i) => {
        const btn = board.children[i];
        if (!btn) return;
        btn.className = "cell";
        btn.innerHTML = "";
        if (cell.open) {
          btn.classList.add("open");
          if (cell.mine) {
            btn.classList.add("mine");
            btn.innerHTML = MINE;
            btn.setAttribute("aria-label", "Mine");
          } else if (cell.n) {
            btn.textContent = String(cell.n);
            btn.classList.add("n" + cell.n);
            btn.setAttribute("aria-label", String(cell.n));
          } else {
            btn.setAttribute("aria-label", "Empty");
          }
        } else if (cell.flag) {
          btn.classList.add("flag");
          btn.innerHTML = FLAG;
          btn.setAttribute("aria-label", "Flagged");
        } else {
          btn.setAttribute("aria-label", "Cell " + (i + 1));
        }
      });
    }

    function bind(el, i) {
      let hold = 0;
      let suppress = false;
      let flagged = false;

      function stopHold() {
        if (!hold) return;
        clearTimeout(hold);
        hold = 0;
      }

      function putFlag() {
        flagged = true;
        suppress = true;
        flag(game, i);
        paint();
      }

      el.addEventListener("pointerdown", (ev) => {
        if (ev.button === 2) {
          ev.preventDefault();
          suppress = true;
          return;
        }
        if (ev.button !== 0) return;
        // A right-click that never emitted click must not swallow this tap.
        suppress = false;
        flagged = false;
        stopHold();
        if (ev.pointerType === "mouse") return;
        hold = setTimeout(() => {
          hold = 0;
          if (flagged) return;
          putFlag();
        }, 450);
      });
      el.addEventListener("pointerup", (ev) => {
        stopHold();
        if (ev.button === 2 && !flagged) putFlag();
      });
      el.addEventListener("pointercancel", stopHold);
      el.addEventListener("pointerleave", (ev) => {
        if (ev.pointerType === "mouse") return;
        stopHold();
      });
      el.addEventListener("contextmenu", (ev) => {
        ev.preventDefault();
        stopHold();
        if (flagged) return;
        putFlag();
      });
      el.addEventListener("click", (ev) => {
        stopHold();
        if (suppress || flagged) {
          suppress = false;
          flagged = false;
          ev.preventDefault();
          return;
        }
        reveal(game, i);
        paint();
      });
    }

    function build() {
      board.innerHTML = "";
      document.body.dataset.state = "";
      for (let i = 0; i < W * H; i++) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "cell";
        bind(el, i);
        board.appendChild(el);
      }
      paint();
    }

    board.addEventListener("contextmenu", (ev) => ev.preventDefault());
    again.addEventListener("click", () => {
      game = restart();
      build();
    });
    build();
  }

  boot();
  return { create, reveal, flag, restart, neighbors };
});
