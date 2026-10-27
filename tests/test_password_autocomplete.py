"""Chrome must not offer to save vault passcodes or other secrets."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
INPUT = re.compile(r"<input\b[^>]*>", re.I)


class PasswordAutocompleteTests(unittest.TestCase):
    def test_every_password_input_is_new_password(self):
        seen = 0
        for f in (UI / "index.html", UI / "app.js"):
            for tag in INPUT.findall(f.read_text(encoding="utf-8")):
                if re.search(r"""type\s*=\s*["']?password""", tag, re.I):
                    seen += 1
                    self.assertRegex(tag, r"""autocomplete\s*=\s*["']new-password["']""", f"{f.name}: {tag}")
        self.assertGreaterEqual(seen, 4)

    def test_vault_folder_and_unlock_form_are_autocomplete_off(self):
        html = (UI / "index.html").read_text(encoding="utf-8")
        for ident in ("vaultPath", "fpPathIn"):
            tag = re.search(rf"""<input\b[^>]*\bid="{ident}"[^>]*>""", html).group(0)
            self.assertIn('autocomplete="off"', tag)
        form = re.search(r"""<form\b[^>]*\bid="unlockForm"[^>]*>""", html).group(0)
        self.assertIn('autocomplete="off"', form)


if __name__ == "__main__":
    unittest.main()
