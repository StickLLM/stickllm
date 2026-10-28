/* Set the visible textarea and use Notepad's own Save As. */
(function () {
  "use strict";
  function editor() {
    return document.getElementById("textEditor");
  }
  window.stickllmApp = {
    describe: function () {
      return { id: "notepad", actions: ["set_text", "save_as"] };
    },
    state: function () {
      const box = editor();
      return { text: box ? box.value : "" };
    },
    act: function (action) {
      const box = editor();
      if (!box) return { ok: false, error: "no_editor" };
      if (action && Object.prototype.hasOwnProperty.call(action, "set_text")) {
        box.value = String(action.set_text == null ? "" : action.set_text);
        box.dispatchEvent(new Event("input", { bubbles: true }));
        return { text: box.value };
      }
      if (action && Object.prototype.hasOwnProperty.call(action, "save_as")) {
        if (typeof app !== "undefined" && app && typeof app.saveFileAs === "function") app.saveFileAs();
        else {
          const button = document.getElementById("butSaveAs");
          if (button) button.click();
        }
        return { text: box.value, save_as: true };
      }
      return { ok: false, error: "bad_action", state: { text: box.value } };
    },
  };
})();
