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
    if (!Array.isArray(value) || value.length < 2) return null;
    const r = Number(value[0]);
    const c = Number(value[1]);
    if (!Number.isInteger(r) || !Number.isInteger(c)) return null;
    return { row: r, col: c };
  }

  window.stickllmApp = {
    describe: function () {
      return { id: "minesweeper", actions: ["reveal", "flag"] };
    },
    state: function () {
      return { grid: grid() };
    },
    act: function (action) {
      const reveal = pair(action && action.reveal);
      const flag = pair(action && action.flag);
      return new Promise(function (resolve) {
        try {
          if (reveal && typeof clickAction === "function" && typeof releaseAction === "function") {
            clickAction({ row: reveal.row, col: reveal.col, which: 1 });
            releaseAction({ row: reveal.row, col: reveal.col, which: 1 });
          } else if (flag && typeof clickAction === "function") {
            clickAction({ row: flag.row, col: flag.col, which: 3 });
          }
        } catch (err) {
          resolve({ ok: false, error: String(err), state: { grid: grid() } });
          return;
        }
        setTimeout(function () { resolve({ grid: grid() }); }, 280);
      });
    },
  };
})();
