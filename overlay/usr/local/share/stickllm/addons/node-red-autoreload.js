// StickLLM (MIT): loaded into the Node-RED editor page by settings.js
// (editorTheme.page.scripts). Node-RED itself is not changed.
// 0.5.6: when the flows on the server change behind the editor's back (the
// StickLLM app agent deployed or undid a change) and the editor has no
// unsaved edits, reload the editor so it shows the new flows. With unsaved
// edits Node-RED's own "flows have been updated" dialog is left alone.
(function () {
  "use strict";
  function hook() {
    var RED = window.RED;
    if (!RED || !RED.comms || !RED.nodes || typeof RED.comms.subscribe !== "function") {
      setTimeout(hook, 500);
      return;
    }
    RED.comms.subscribe("notification/runtime-deploy", function (topic, msg) {
      var rev = msg && msg.revision;
      if (!rev) return;
      // Give the editor's own Deploy a moment to record its new revision.
      setTimeout(function () {
        var cur = RED.nodes.version();
        if (cur === null || cur === rev) return;
        if (typeof RED.nodes.dirty === "function" && RED.nodes.dirty()) return;
        location.reload();
      }, 1200);
    });
  }
  hook();
})();
