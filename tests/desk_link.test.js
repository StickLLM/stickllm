// 0.5.2 fix 5: appTabLink fallback (pulled out of ui/app.js, run with a fake DOM).
const fs = require("fs");
const assert = require("assert");
const src = fs.readFileSync(__dirname + "/../ui/app.js", "utf8");
const grab = (start, end) => src.slice(src.indexOf(start), src.indexOf(end, src.indexOf(start)));
const code = grab("const APP_ID_ALIASES", "function openAppTab(id)");
const icons = { 'data-starter="files"': { href: "/apps/files/", target: "stickllm-files" } };
const document = { querySelector: (s) => { for (const k of Object.keys(icons)) if (s.includes(k)) return { getAttribute: (a) => icons[k][a] }; return null; } };
const CSS = { escape: (v) => v };
const APP_LABELS = { files: "Files", notepad: "Notepad" };
const catalogApps = new Map([["radicale", { id: "radicale", open_url: "https://stick:8101/" }]]);
const appTabLink = new Function("document", "CSS", "APP_LABELS", "catalogApps", code + "\nreturn appTabLink;")(document, CSS, APP_LABELS, catalogApps);
assert.deepStrictEqual(appTabLink("files"), { href: "/apps/files/", target: "stickllm-files" });
assert.deepStrictEqual(appTabLink("notepad"), { href: "/apps/notepad/", target: "stickllm-notepad" });
assert.deepStrictEqual(appTabLink("radicale"), { href: "https://stick:8101/", target: "stickllm-radicale" });
assert.deepStrictEqual(appTabLink("docs"), { href: "/apps/docs/", target: "stickllm-onlyoffice" });
assert.strictEqual(appTabLink("bogus"), null);
console.log("desk link ok");
