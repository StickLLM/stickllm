"""Chrome must not offer to save vault passcodes or other secrets.

Chrome's save-password prompt keys off type=password fields, so secret fields
are type=text masked with the .secret class (-webkit-text-security: disc).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
INPUT = re.compile(r"<input\b[^>]*>", re.I)
SECRETS = ("vaultPass", "np1", "np2", "hfToken", "wpass")


def tag_for(html: str, ident: str) -> str:
    m = re.search(rf"""<input\b[^>]*\bid="{ident}"[^>]*>""", html)
    assert m, ident
    return m.group(0)


class SecretFieldTests(unittest.TestCase):
    def test_no_password_type_inputs_remain(self):
        for f in (UI / "index.html", UI / "app.js"):
            text = f.read_text(encoding="utf-8")
            for tag in INPUT.findall(text):
                self.assertNotRegex(tag, r"""type\s*=\s*["']?password""", f"{f.name}: {tag}")
            # No JS that flips an input to type=password either.
            self.assertNotRegex(text, r"""\.type\s*=\s*[^;]*["']password["']""", f.name)

    def test_secret_fields_are_masked_text_with_autocomplete_off(self):
        html = (UI / "index.html").read_text(encoding="utf-8")
        for ident in SECRETS:
            tag = tag_for(html, ident)
            self.assertIn('type="text"', tag, ident)
            self.assertRegex(tag, r'class="[^"]*\bsecret\b', ident)
            self.assertIn('autocomplete="off"', tag, ident)
            self.assertIn('spellcheck="false"', tag, ident)
            self.assertIn('data-lpignore="true"', tag, ident)
        css = (UI / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.secret\s*\{[^}]*-webkit-text-security:\s*disc")

    def test_vault_folder_and_unlock_form_are_autocomplete_off(self):
        html = (UI / "index.html").read_text(encoding="utf-8")
        for ident in ("vaultPath", "fpPathIn"):
            self.assertIn('autocomplete="off"', tag_for(html, ident))
        form = re.search(r"""<form\b[^>]*\bid="unlockForm"[^>]*>""", html).group(0)
        self.assertIn('autocomplete="off"', form)

    def test_show_toggle_uses_secret_class(self):
        js = (UI / "app.js").read_text(encoding="utf-8")
        line = next(ln for ln in js.splitlines() if '$("#hfShow").onclick' in ln)
        self.assertIn('classList.toggle("secret")', line)


if __name__ == "__main__":
    unittest.main()
