/* Drive the visible Tetris game for StickLLM agents. Uses the game's own
   move/rotate/drop functions, so the rules are unchanged. Turn mode (the
   default once an agent acts) stops gravity between agent actions so a slow
   model can play one placement at a time. */
(function () {
  "use strict";

  const NAMES = { cyan: "I", blue: "J", orange: "L", yellow: "O", green: "S", purple: "T", red: "Z" };
  const W = 10;
  const H = 20;
  let mode = "realtime";
  let paused = false;
  let lost = false;

  function ready() {
    return typeof move === "function" && typeof rotate === "function" && typeof drop === "function" &&
      typeof play === "function" && typeof update === "function" && typeof DIR === "object";
  }

  function letter(type) {
    return (type && NAMES[type.color]) || "?";
  }

  function cells(type, dir) {
    const out = [];
    const bits = type.blocks[dir];
    let n = 0;
    for (let bit = 0x8000; bit > 0; bit = bit >> 1, n++) {
      if (bits & bit) out.push([n % 4, Math.floor(n / 4)]);
    }
    return out;
  }

  function bounds(type, dir) {
    const c = cells(type, dir);
    const xs = c.map(function (p) { return p[0]; });
    const ys = c.map(function (p) { return p[1]; });
    return { minx: Math.min.apply(null, xs), maxx: Math.max.apply(null, xs), miny: Math.min.apply(null, ys), maxy: Math.max.apply(null, ys), cells: c };
  }

  function shape(type, dir) {
    const b = bounds(type, dir);
    const rowsOut = [];
    for (let y = b.miny; y <= b.maxy; y++) {
      let line = "";
      for (let x = b.minx; x <= b.maxx; x++) {
        line += b.cells.some(function (p) { return p[0] === x && p[1] === y; }) ? "#" : ".";
      }
      rowsOut.push(line);
    }
    return rowsOut;
  }

  function filled(x, y) {
    return !!(blocks && blocks[x] && blocks[x][y]);
  }

  function grid() {
    const g = [];
    for (let y = 0; y < H; y++) {
      const row = [];
      for (let x = 0; x < W; x++) row.push(filled(x, y) ? 1 : 0);
      g.push(row);
    }
    return g;
  }

  function fits(g, type, x, y, dir) {
    return cells(type, dir).every(function (p) {
      const cx = x + p[0];
      const cy = y + p[1];
      return cx >= 0 && cx < W && cy >= 0 && cy < H && !g[cy][cx];
    });
  }

  // Simple one-piece lookahead (aggregate height, lines, holes, bumpiness).
  function evaluate(g) {
    let lines = 0;
    const kept = g.filter(function (row) {
      const full = row.every(Boolean);
      if (full) lines++;
      return !full;
    });
    while (kept.length < H) kept.unshift(new Array(W).fill(0));
    const heights = [];
    let holes = 0;
    for (let x = 0; x < W; x++) {
      let h = 0;
      for (let y = 0; y < H; y++) {
        if (kept[y][x]) { if (!h) h = H - y; } else if (h) holes++;
      }
      heights.push(h);
    }
    let bump = 0;
    for (let x = 0; x < W - 1; x++) bump += Math.abs(heights[x] - heights[x + 1]);
    const agg = heights.reduce(function (a, b) { return a + b; }, 0);
    return { score: -0.51 * agg + 0.76 * lines - 0.36 * holes - 0.18 * bump, lines: lines, holes: holes };
  }

  function suggest() {
    if (!playing || !current) return null;
    const g = grid();
    let best = null;
    const seen = {};
    for (let dir = 0; dir < 4; dir++) {
      const key = String(current.type.blocks[dir]);
      if (seen[key]) continue;
      seen[key] = true;
      const b = bounds(current.type, dir);
      for (let col = 0; col + (b.maxx - b.minx) < W; col++) {
        const x = col - b.minx;
        if (!fits(g, current.type, x, 0, dir)) continue;
        let y = 0;
        while (fits(g, current.type, x, y + 1, dir)) y++;
        const after = g.map(function (row) { return row.slice(); });
        b.cells.forEach(function (p) { after[y + p[1]][x + p[0]] = 1; });
        const e = evaluate(after);
        if (!best || e.score > best.score) best = { col: col, rot: dir, lines: e.lines, holes: e.holes, score: e.score };
      }
    }
    if (!best) return null;
    return { place: { col: best.col, rot: best.rot }, clears_lines: best.lines, holes_after: best.holes };
  }

  function rotations(type) {
    const out = [];
    for (let dir = 0; dir < 4; dir++) {
      const b = bounds(type, dir);
      out.push({ rot: dir, shape: shape(type, dir), cols: "0-" + (W - 1 - (b.maxx - b.minx)) });
    }
    return out;
  }

  function status() {
    if (playing) return paused ? "paused" : "playing";
    return lost ? "game_over" : "ready";
  }

  function state() {
    if (!ready()) return { status: "loading" };
    const g = grid();
    const board = g.map(function (row) { return row.map(function (v) { return v ? "#" : "."; }).join(""); });
    const out = {
      status: status(),
      mode: mode,
      score: score,
      lines: rows,
      board: board,
      next: next ? letter(next.type) : null,
      help: "board/view rows top to bottom, 10 columns 0-9, #=settled, @=falling piece. " +
        "place {col, rot}: col is the leftmost board column the piece will cover, rot 0-3 as listed in rotations. " +
        "Turn mode: the piece only moves when you act.",
    };
    if (playing && current) {
      const b = bounds(current.type, current.dir);
      const view = board.map(function (r) { return r.split(""); });
      b.cells.forEach(function (p) {
        const x = current.x + p[0];
        const y = current.y + p[1];
        if (y >= 0 && y < H && x >= 0 && x < W) view[y][x] = "@";
      });
      out.view = view.map(function (r) { return r.join(""); });
      out.current = {
        type: letter(current.type),
        rot: current.dir,
        col: current.x + b.minx,
        row: current.y + b.miny,
        shape: shape(current.type, current.dir),
      };
      out.rotations = rotations(current.type);
      out.suggest = suggest();
    }
    return out;
  }

  function count(value) {
    if (value === true) return 1;
    const n = Number(value);
    return Number.isInteger(n) && n > 0 ? Math.min(n, 20) : 0;
  }

  function hardDrop() {
    while (move(DIR.DOWN)) { /* fall */ }
    drop();
  }

  function place(spec) {
    let col = null;
    let rot = null;
    if (Array.isArray(spec)) { col = spec[0]; rot = spec[1]; }
    else if (spec && typeof spec === "object") { col = spec.col; rot = spec.rot; }
    else if (spec === "suggested" || spec === "suggest") {
      const s = suggest();
      if (!s) return "no_suggestion";
      col = s.place.col; rot = s.place.rot;
    }
    col = Number(col);
    rot = rot === undefined || rot === null ? current.dir : Number(rot);
    if (!Number.isInteger(col) || !Number.isInteger(rot) || rot < 0 || rot > 3) return "bad_place";
    const b = bounds(current.type, rot);
    if (col < 0 || col + (b.maxx - b.minx) >= W) return "col_out_of_range";
    // Rotate first; if a wall or stack blocks it, nudge toward the middle.
    for (let tries = 0; tries < 8 && current.dir !== rot; tries++) {
      const before = current.dir;
      rotate();
      if (current.dir === before) move(current.x < W / 2 - 2 ? DIR.RIGHT : DIR.LEFT);
    }
    if (current.dir !== rot) return "cannot_rotate";
    const target = col - b.minx;
    for (let tries = 0; tries < W + 2 && current.x !== target; tries++) {
      if (!move(current.x < target ? DIR.RIGHT : DIR.LEFT)) break;
    }
    if (current.x !== target) return "blocked";
    hardDrop();
    return null;
  }

  function setBanner() {
    let el = document.getElementById("stickllm-agent-mode");
    if (!el) {
      el = document.createElement("p");
      el.id = "stickllm-agent-mode";
      el.style.cssText = "margin:4px 12px;font:12px sans-serif;color:#555";
      const host = document.getElementById("tetris");
      if (host && host.parentNode) host.parentNode.insertBefore(el, host);
      else document.body.appendChild(el);
    }
    el.textContent = paused ? "Paused by agent." :
      mode === "turn" ? "Agent turn mode: the piece waits for the agent's next move." : "";
  }

  function install() {
    if (!ready() || window.stickllmApp) return;
    const baseUpdate = update;
    const basePlay = play;
    const baseLose = lose;
    // Same globals the game loop calls; only gravity timing changes.
    window.update = function (idt) {
      if (paused) { if (actions) actions.length = 0; return; }
      baseUpdate(mode === "turn" ? 0 : idt);
    };
    // A game started from the keyboard is a normal real-time game.
    window.play = function () { lost = false; paused = false; mode = "realtime"; basePlay(); setBanner(); };
    window.lose = function () { lost = true; baseLose(); };

    window.stickllmApp = {
      describe: function () {
        return { id: "tetris", actions: ["start", "new_game", "pause", "resume", "mode", "left", "right", "rotate", "soft_drop", "hard_drop", "place"] };
      },
      state: state,
      act: function (action) {
        action = action && typeof action === "object" ? action : {};
        let error = null;
        const before = { score: score, lines: rows };
        try {
          const want = action.mode === "realtime" || action.mode === "turn" ? action.mode : "turn";
          if (action.new_game || (action.start && !playing)) play();
          mode = want;
          if (action.pause) paused = true;
          if (action.resume) paused = false;
          const moves = ["left", "right", "rotate", "soft_drop", "hard_drop", "place"];
          const wants = moves.some(function (k) { return action[k] !== undefined && action[k] !== false; });
          if (wants) {
            if (!playing) error = lost ? "game_over" : "not_started";
            else {
              paused = false;
              if (actions) actions.length = 0;
              if (action.rotate) for (let n = count(action.rotate); n > 0; n--) rotate();
              if (action.left) for (let n = count(action.left); n > 0; n--) move(DIR.LEFT);
              if (action.right) for (let n = count(action.right); n > 0; n--) move(DIR.RIGHT);
              if (action.soft_drop) for (let n = count(action.soft_drop); n > 0 && playing; n--) drop();
              if (action.place !== undefined && action.place !== false) error = place(action.place);
              else if (action.hard_drop) hardDrop();
            }
          } else if (!action.new_game && !action.start && !action.pause && !action.resume && !action.mode) {
            error = "unknown_action";
          }
        } catch (err) {
          error = String(err);
        }
        setBanner();
        const st = state();
        st.last = { lines_cleared: rows - before.lines, score_gained: score - before.score };
        return error ? { ok: false, error: error, state: st } : { ok: true, state: st };
      },
    };
    setBanner();
  }

  install();
})();
