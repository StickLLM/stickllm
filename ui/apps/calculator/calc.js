/* External script: the gateway CSP is script-src 'self' and blocks inline scripts. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StickCalc = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function initial() {
    return { display: "0", acc: null, op: null, fresh: true };
  }

  function copy(state) {
    const src = state || {};
    const acc = typeof src.acc === "number" && Number.isFinite(src.acc) ? src.acc : null;
    return {
      display: src.display == null ? "0" : String(src.display),
      acc: acc,
      op: typeof src.op === "string" ? src.op : null,
      fresh: src.fresh !== false,
    };
  }

  function formatNumber(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "Error";
    if (Object.is(value, -0)) value = 0;
    const rounded = Math.round(value * 1e10) / 1e10;
    let text = String(rounded);
    if (text.length > 14) text = rounded.toPrecision(8);
    return text;
  }

  function currentNumber(display) {
    if (display === "Error" || display === "") return null;
    const n = Number(display);
    return Number.isFinite(n) ? n : null;
  }

  function apply(acc, op, cur) {
    if (op === "+") return acc + cur;
    if (op === "-") return acc - cur;
    if (op === "*") return acc * cur;
    if (op === "/") return cur === 0 ? NaN : acc / cur;
    return cur;
  }

  function known(key) {
    return key === "C" || key === "⌫" || key === "±" || key === "%" || key === "=" || "+-*/".includes(key) || /^[0-9.]$/.test(key);
  }

  function press(state, key) {
    if (!known(key)) return copy(state);
    if (key === "C") return initial();
    let s = copy(state);
    if (s.display === "Error" || currentNumber(s.display) === null) s = initial();

    if (key === "⌫") {
      if (s.fresh) return s;
      const next = s.display.slice(0, -1);
      s.display = next === "" || next === "-" ? "0" : next;
      if (currentNumber(s.display) === null) return initial();
      return s;
    }
    if (key === "±") {
      const n = currentNumber(s.display);
      if (n === null) return s;
      s.display = formatNumber(n * -1);
      s.fresh = false;
      return s;
    }
    if (key === "%") {
      const n = currentNumber(s.display);
      if (n === null) return s;
      s.display = formatNumber(n / 100);
      s.fresh = false;
      return s;
    }
    if ("+-*/".includes(key)) {
      const cur = currentNumber(s.display);
      if (cur === null) return { display: "Error", acc: null, op: null, fresh: true };
      if (s.acc === null || s.fresh || s.op === null) s.acc = cur;
      else {
        const next = apply(s.acc, s.op, cur);
        if (!Number.isFinite(next)) return { display: "Error", acc: null, op: null, fresh: true };
        s.acc = next;
      }
      s.op = key;
      s.fresh = true;
      s.display = formatNumber(s.acc);
      return s;
    }
    if (key === "=") {
      if (s.op === null || s.acc === null) return s;
      const cur = currentNumber(s.display);
      if (cur === null) return { display: "Error", acc: null, op: null, fresh: true };
      const result = apply(s.acc, s.op, cur);
      if (!Number.isFinite(result)) return { display: "Error", acc: null, op: null, fresh: true };
      return { display: formatNumber(result), acc: null, op: null, fresh: true };
    }
    if (s.fresh) {
      s.display = key === "." ? "0." : key;
      s.fresh = false;
      return s;
    }
    if (key === "." && s.display.includes(".")) return s;
    s.display = s.display === "0" && key !== "." ? key : s.display + key;
    if (s.display.length > 16) s.display = s.display.slice(0, 16);
    return s;
  }

  function run(keys) {
    return keys.reduce((s, key) => press(s, key), initial());
  }

  function boot() {
    if (typeof document === "undefined") return;
    const screen = document.getElementById("screen");
    const box = document.getElementById("keys");
    if (!screen || !box) return;
    const keys = ["C", "±", "%", "/", "7", "8", "9", "*", "4", "5", "6", "-", "1", "2", "3", "+", "0", ".", "⌫", "="];
    let state = initial();
    function render() { screen.textContent = state.display; }
    function hit(key) { state = press(state, key); render(); }
    keys.forEach((key) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = key;
      if ("+-*/=".includes(key)) btn.className = "op";
      btn.addEventListener("click", () => hit(key));
      box.appendChild(btn);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const map = { Enter: "=", Escape: "C", Backspace: "⌫", c: "C", C: "C", x: "*", X: "*", ",": "." };
      const key = Object.prototype.hasOwnProperty.call(map, ev.key) ? map[ev.key] : ev.key;
      if (!keys.includes(key)) return;
      ev.preventDefault();
      hit(key);
    });
    render();
  }

  boot();
  return { initial, press, run, formatNumber, apply };
});
