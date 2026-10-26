/* Press the on-screen calculator keys for an expression. */
(function () {
  "use strict";
  function screen() {
    const el = document.getElementById("screen");
    return el ? el.textContent : "";
  }
  function pressKey(key) {
    const buttons = document.querySelectorAll("#keys button");
    for (let i = 0; i < buttons.length; i++) {
      if (buttons[i].textContent === key) {
        buttons[i].click();
        return true;
      }
    }
    return false;
  }
  window.stickllmApp = {
    describe: function () {
      return { id: "calculator", actions: ["expr"] };
    },
    state: function () {
      return { display: screen() };
    },
    act: function (action) {
      const expr = action && action.expr != null ? String(action.expr) : "";
      if (!expr) return { ok: false, error: "bad_expr", state: { display: screen() } };
      for (let i = 0; i < expr.length; i++) {
        if (!pressKey(expr[i])) return { ok: false, error: "bad_key", state: { display: screen() } };
      }
      return { display: screen() };
    },
  };
})();
