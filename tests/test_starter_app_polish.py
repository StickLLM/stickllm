"""Starter app polish: Minesweeper plays as a game, Files follows the theme,
Notepad's Back to Apps link does not collide with its title."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "ui" / "apps"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _is_checked(tag: str) -> bool:
    return re.search(r"\schecked(?=[\s/>=])", tag) is not None


def _checkbox(page: str, cid: str) -> str:
    m = re.search(r'<input[^>]*\bid="%s"[^>]*>' % re.escape(cid), page)
    assert m, cid
    return m.group(0)


def test_minesweeper_opens_without_solver_overlay():
    # Upstream JSMinesweeper ships as a solver: Show hints, Auto play and the
    # "Mine %" overlay are on, which printed "21" (99/480 mines) on every
    # covered Expert tile. The bundled app must start as a plain game.
    page = _read(APPS / "minesweeper" / "index.html")
    assert not _is_checked(_checkbox(page, "showhints"))
    assert not _is_checked(_checkbox(page, "autoplay"))
    assert _is_checked(_checkbox(page, "gameTypeZero"))
    sel = re.search(r'<select id="overlay".*?</select>', page, re.S).group(0)
    selected = re.findall(r'<option value="(\w+)"\s+selected', sel)
    assert selected == ["none"], selected
    # The tools are still available, just off.
    for opt in ("safety", "mine", "zero"):
        assert 'value="%s"' % opt in sel
    note = _read(APPS / "minesweeper" / "SOURCES.txt")
    assert "Solver hints, Auto play and the probability overlay are off by default" in note


def test_files_app_follows_light_theme():
    page = _read(APPS / "files" / "index.html")
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    assert ':root[data-theme="light"]' in style
    # No hard-coded dark colours outside the variable definitions.
    rules = [r for r in style.split("}") if ":root" not in r]
    assert not re.search(r"#[0-9a-fA-F]{3,6}", "}".join(rules))
    assert "files.js?v=desk3" in page
    js = _read(APPS / "files" / "files.js")
    assert "window.parent.document.documentElement.dataset.theme" in js
    assert "MutationObserver" in js and "prefers-color-scheme: light" in js


def test_files_theme_sync_logic():
    node = shutil.which("node")
    assert node
    script = r"""
const fs = require("fs"); const vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
function run(parentTheme, prefersLight) {
  const own = { dataset: {} }; let observed = null;
  const parentDoc = { documentElement: { dataset: parentTheme == null ? {} : { theme: parentTheme } } };
  const el = { textContent: "", addEventListener() {}, onclick: null, append() {}, replaceChildren() {} };
  const document = { documentElement: own, querySelector: () => el, createElement: () => Object.assign({}, el) };
  const win = { matchMedia: () => ({ matches: prefersLight }) };
  win.parent = parentTheme === "self" ? win : { document: parentDoc };
  const ctx = { window: win, document, fetch: () => new Promise(() => {}), console,
    MutationObserver: function (cb) { this.observe = (n) => { observed = { n, cb }; }; } };
  vm.runInNewContext(src, ctx);
  return { own, observed, parentDoc };
}
let r = run("light", false); if (r.own.dataset.theme !== "light") throw new Error("parent light");
r.parentDoc.documentElement.dataset.theme = "dark"; r.observed.cb();
if (r.own.dataset.theme !== "dark") throw new Error("follows parent change");
r = run("self", true); if (r.own.dataset.theme !== "light") throw new Error("standalone prefers light");
r = run("self", false); if (r.own.dataset.theme !== "dark") throw new Error("standalone default dark");
"""
    subprocess.run([node, "-e", script, str(APPS / "files" / "files.js")], cwd=ROOT, check=True)


def test_notepad_back_link_sits_clear_of_title():
    page = _read(APPS / "notepad" / "index.html")
    assert '<a class="stickBack" href="/#apps">Back to Apps</a>' in page
    links = re.findall(r'<link rel="stylesheet" href="styles/([\w.]+)">', page)
    assert links.index("stickllm.css") > links.index("main.css")
    assert links.index("stickllm.css") > links.index("standalone.css")
    css = _read(APPS / "notepad" / "styles" / "stickllm.css")
    assert re.search(r"header\s*\{\s*position:\s*relative", css)
    assert re.search(r"a\.stickBack\s*\{[^}]*position:\s*absolute", css)
    assert re.search(r"header h1\s*\{[^}]*padding-right", css)
    assert "stickllm.css" in _read(APPS / "notepad" / "SOURCES.txt")
