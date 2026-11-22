/* Drive the visible Minesweeper board. Does not change the game rules. */
(function () {
  "use strict";

  function stickllmSkin() {
    try {
      document.body.classList.add("stickllm-ms");
      const title = document.getElementById("title");
      if (title) title.textContent = "Minesweeper";
      const ng = document.getElementById("noGuessMode");
      if (ng) {
        if (ng.checked) {
          ng.checked = false;
          try { if (typeof noGuessCancel === "function") noGuessCancel(); } catch (_) {}
        }
      }
      try { if (typeof ngCancel !== "undefined") ngCancel = true; } catch (_) {}
      [
        "localStorage", "noGuessBuilder", "properties", "xRayPanel",
        "exportBarBottom", "xRayLaunchButton", "selectAnalyser",
        "exportToPtta", "exportToLlama", "downloadBar", "AnalysisButton",
      ].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
      });
      const play1 = document.getElementById("play1");
      if (play1) play1.style.display = "none";
      const auto = document.getElementById("autoplay");
      if (auto) auto.checked = false;
      // Drop solver welcome / stuck builder text from the status line.
      try {
        const msg = document.getElementById("messageLineBottom");
        if (msg && /solver|Annie|No Guess|Working|FAILED/i.test(msg.textContent || "")) {
          msg.textContent = "";
        }
        const msg2 = document.getElementById("messageLine");
        if (msg2 && /solver|Annie|No Guess|Working|FAILED/i.test(msg2.textContent || "")) {
          msg2.textContent = "";
        }
      } catch (_) {}
    } catch (_) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", stickllmSkin);
  } else {
    stickllmSkin();
  }
  window.addEventListener("load", stickllmSkin);
  setTimeout(stickllmSkin, 0);
  setTimeout(stickllmSkin, 400);

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
    if (!Array.isArray(value) || value.length < 2) return null;
    const r = Number(value[0]);
    const c = Number(value[1]);
    if (!Number.isInteger(r) || !Number.isInteger(c)) return null;
    return { row: r, col: c };
  }

  function inBounds(p) {
    if (!p || typeof board === "undefined" || !board) return false;
    return p.row >= 0 && p.col >= 0 && p.row < board.height && p.col < board.width;
  }

  window.stickllmApp = {
    describe: function () {
      return {
        id: "minesweeper",
        actions: ["reveal", "flag"],
        note: "Coords are [row, col], 0-based. Flagging needs a started game (reveal first).",
      };
    },
    state: function () {
      const started = !!(typeof board !== "undefined" && board && board.isStarted && board.isStarted());
      const over = !!(typeof board !== "undefined" && board && board.isGameover && board.isGameover());
      return {
        grid: grid(),
        width: typeof board !== "undefined" && board ? board.width : 0,
        height: typeof board !== "undefined" && board ? board.height : 0,
        started: started,
        game_over: over,
      };
    },
    act: function (action) {
      const reveal = pair(action && action.reveal);
      const flag = pair(action && action.flag);
      return new Promise(function (resolve) {
        try {
          if (typeof board === "undefined" || !board) {
            resolve({ ok: false, error: "board_not_ready", state: { grid: "" } });
            return;
          }
          if (board.isGameover && board.isGameover()) {
            resolve({ ok: false, error: "game_over", state: { grid: grid() } });
            return;
          }
          if (typeof canvasLocked !== "undefined" && canvasLocked) {
            resolve({ ok: false, error: "busy", state: { grid: grid() } });
            return;
          }
          if (reveal) {
            if (!inBounds(reveal)) {
              resolve({ ok: false, error: "out_of_bounds", state: { grid: grid() } });
              return;
            }
            if (typeof clickAction !== "function" || typeof releaseAction !== "function") {
              resolve({ ok: false, error: "no_click_api", state: { grid: grid() } });
              return;
            }
            clickAction({ row: reveal.row, col: reveal.col, which: 1 });
            releaseAction({ row: reveal.row, col: reveal.col, which: 1 });
          } else if (flag) {
            if (!inBounds(flag)) {
              resolve({ ok: false, error: "out_of_bounds", state: { grid: grid() } });
              return;
            }
            if (board.isStarted && !board.isStarted()) {
              resolve({
                ok: false,
                error: "not_started",
                message: "Reveal a cell before flagging.",
                state: { grid: grid() },
              });
              return;
            }
            if (typeof clickAction !== "function") {
              resolve({ ok: false, error: "no_click_api", state: { grid: grid() } });
              return;
            }
            // Play-mode right-click is handled entirely in clickAction.
            clickAction({ row: flag.row, col: flag.col, which: 3 });
          } else {
            resolve({ ok: false, error: "bad_action", state: { grid: grid() } });
            return;
          }
        } catch (err) {
          resolve({ ok: false, error: String(err), state: { grid: grid() } });
          return;
        }
        setTimeout(function () {
          resolve({ ok: true, state: { grid: grid() } });
        }, 280);
      });
    },
  };
})();
