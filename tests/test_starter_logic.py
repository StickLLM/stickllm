"""Drive the starter-app functions: calculator, minesweeper, solitaire, monitor."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_calculator_minesweeper_solitaire_and_monitor():
    node = shutil.which("node")
    assert node, "node is required to run the starter logic"
    script = ROOT / "tests" / "starter_logic.test.js"
    subprocess.run([node, str(script)], cwd=ROOT, check=True)
