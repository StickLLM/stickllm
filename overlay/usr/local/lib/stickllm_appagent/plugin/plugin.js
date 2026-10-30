// StickLLM app-agent bridge: long-polls the app-agent service and runs Presentation API JS in this editor.
(function (window) {
  // Service base = this page's URL minus /oo/plugin/..., so it also works behind a path prefix (gateway /appagent).
  var base = window.location.href.split("?")[0].replace(/\/oo\/plugin\/[^\/]*$/, ""), cid = Math.random().toString(36).slice(2), started = false;
  function post(id, value) {
    return fetch(base + "/oo/result", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: id, value: value})}).catch(function () {});
  }
  function run(job) {
    return new Promise(function (resolve) {
      var done = false, timer = setTimeout(function () { if (!done) { done = true; resolve(JSON.stringify({__error: "callCommand timeout"})); } }, 20000);
      var f;
      try { f = new Function(job.code); } catch (e) { done = true; clearTimeout(timer); return resolve(JSON.stringify({__error: "compile: " + e})); }
      window.Asc.plugin.callCommand(f, false, true, function (res) { if (!done) { done = true; clearTimeout(timer); resolve(res); } });
    });
  }
  function loop() {
    fetch(base + "/oo/poll?client=" + cid).then(function (r) { return r.status === 200 ? r.json() : null; })
      .then(function (job) {
        if (!job) return loop();
        run(job).then(function (res) { return post(job.id, res); }).then(loop);
      })
      .catch(function () { setTimeout(loop, 1000); });
  }
  window.Asc.plugin.init = function () { if (!started) { started = true; loop(); } };
  window.Asc.plugin.button = function () {};
})(window);
