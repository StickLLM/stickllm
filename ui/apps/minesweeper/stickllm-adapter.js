/* Drive the visible Minesweeper board. Does not change the game rules. */
(function () {
  "use strict";

  function cell(tile) {
    if (!tile) return "?";
    if (tile.isFlagged && tile.isFlagged()) return "F";
    if (tile.isCovered && tile.isCovered()) return "#";
    if (tile.isBomb && tile.isBomb()) return "*";
    if (tile.getValue) return String(tile.getValue());
    return "?";
  }

  function grid() {
    if (typeof board === "undefined" || !board || !board.getTileXY) return "";
    const rows = [];
    for (let r = 0; r < board.height; r++) {
      let line = "";
      for (let c = 0; c < board.width; c++) line += cell(board.getTileXY(c, r));
      rows.push(line);
    }
    return rows.join("\n");
  }

  function pair(value) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const r = Number(value.row != null ? value.row : value.y);
      const c = Number(value.col != null ? value.col : value.x);
      if (!Number.isInteger(r) || !Number.isInteger(c)) return null;
      return { row: r, col: c };
    }
    if (!Array.isArray(value) || value.length < 2) return null;
    const r = Number(value[0]);
    const c = Number(value[1]);
    if (!Number.isInteger(r) || !Number.isInteger(c)) return null;
    return { row: r, col: c };
  }

  function inBounds(p) {
    return !!(p && board && p.row >= 0 && p.col >= 0 && p.row < board.height && p.col < board.width);
  }

  function waitUnlocked(ms) {
    const deadline = Date.now() + (ms || 2500);
    return new Promise(function (resolve) {
      function tick() {
        if (typeof canvasLocked === "undefined" || !canvasLocked || Date.now() >= deadline) {
          resolve(!(typeof canvasLocked !== "undefined" && canvasLocked));
          return;
        }
        setTimeout(tick, 40);
      }
      tick();
    });
  }

  function snapshot() {
    const started = !!(board && board.isStarted && board.isStarted());
    const over = !!(board && board.isGameover && board.isGameover());
    return {
      grid: grid(),
      width: board ? board.width : 0,
      height: board ? board.height : 0,
      mines: board ? board.num_bombs : 0,
      started: started,
      game_over: over,
    };
  }

  function revealViaMouse(p) {
    if (typeof clickAction !== "function" || typeof releaseAction !== "function") {
      return { ok: false, error: "no_click_api" };
    }
    // Play-mode left click sets dragging=true; releaseAction sends the reveal.
    clickAction({ row: p.row, col: p.col, which: 1 });
    releaseAction({ row: p.row, col: p.col, which: 1 });
    return { ok: true };
  }

  function flagViaMouse(p) {
    if (typeof clickAction !== "function") return { ok: false, error: "no_click_api" };
    if (board && board.isStarted && !board.isStarted()) {
      return { ok: false, error: "flag_before_start", message: "Reveal a tile first, then flag." };
    }
    clickAction({ row: p.row, col: p.col, which: 3 });
    return { ok: true };
  }

  function newBeginner() {
    try {
      if (typeof doNewGame === "function") {
        doNewGame(9, 9, 10);
        return true;
      }
      if (typeof newGame === "function") {
        newGame(9, 9, 10, 0, true);
        return true;
      }
    } catch (_) {}
    return false;
  }

  window.stickllmApp = {
    describe: function () {
      return {
        id: "minesweeper",
        actions: ["reveal", "flag", "new_game"],
        note: "reveal/flag use [row,col] (row first). Prefer new_game then beginner-size board.",
      };
    },
    state: function () {
      return snapshot();
    },
    act: function (action) {
      return new Promise(function (resolve) {
        (async function () {
          try {
            if (!board || !board.getTileXY) {
              resolve({ ok: false, error: "no_board", state: snapshot() });
              return;
            }
            if (action && action.new_game) {
              if (!newBeginner()) {
                resolve({ ok: false, error: "new_game_failed", state: snapshot() });
                return;
              }
              await waitUnlocked(1500);
              resolve({ ok: true, state: snapshot() });
              return;
            }
            if (board.isGameover && board.isGameover()) {
              resolve({ ok: false, error: "game_over", state: snapshot() });
              return;
            }
            if (typeof canvasLocked !== "undefined" && canvasLocked) {
              const free = await waitUnlocked(2000);
              if (!free) {
                resolve({ ok: false, error: "busy", message: "Board still processing last click.", state: snapshot() });
                return;
              }
            }
            const reveal = pair(action && action.reveal);
            const flag = pair(action && action.flag);
            let result;
            if (reveal) {
              if (!inBounds(reveal)) {
                resolve({ ok: false, error: "out_of_bounds", state: snapshot() });
                return;
              }
              result = revealViaMouse(reveal);
            } else if (flag) {
              if (!inBounds(flag)) {
                resolve({ ok: false, error: "out_of_bounds", state: snapshot() });
                return;
              }
              result = flagViaMouse(flag);
            } else {
              resolve({ ok: false, error: "bad_action", message: "Use reveal:[row,col], flag:[row,col], or new_game:true", state: snapshot() });
              return;
            }
            if (!result.ok) {
              resolve(Object.assign({ state: snapshot() }, result));
              return;
            }
            await waitUnlocked(2500);
            // Give the async local engine a beat to paint.
            await new Promise(function (r) { setTimeout(r, 120); });
            resolve({ ok: true, state: snapshot() });
          } catch (err) {
            resolve({ ok: false, error: String(err), state: snapshot() });
          }
        })();
      });
    },
  };
})();
