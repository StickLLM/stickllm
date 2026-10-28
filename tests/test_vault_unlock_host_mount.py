"""Vault unlock after reboot: auto-mount the host SSD, never bump the fail count
for a missing drive. Runs the real bash functions with stubbed system calls."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-vault"
LEAF = "Fanxiang-S880-2TB-nvme0n1p2"


def find_bash() -> str | None:
    if os.name == "nt":
        # WindowsApps bash.exe is WSL; use Git Bash only.
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(p).is_file():
                return p
        return None
    return shutil.which("bash")


BASH = find_bash()


def func(text: str, name: str) -> str:
    one = re.search(rf"^{re.escape(name)}\(\) \{{[^\n]*\}}\n", text, re.M)
    if one:
        return one.group(0)
    # Multi-line: first column-0 "}" outside a python heredoc.
    lines = text.splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}() {{"))
    in_heredoc = False
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if in_heredoc:
            in_heredoc = ln.rstrip("\n") != "PY"
        elif "<<'PY'" in ln:
            in_heredoc = True
        elif ln.rstrip("\n") == "}":
            return "".join(lines[start : i + 1])
    raise AssertionError(name)


def posix(p: Path) -> str:
    return str(p).replace("\\", "/")


@unittest.skipUnless(BASH, "bash not available")
class UnlockHostMountTests(unittest.TestCase):
    def run_unlock(self, drive_present: bool):
        text = VAULT.read_text(encoding="utf-8")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        host = tmp / "host"
        blob = f"{posix(host)}/{LEAF}/home/nink/stickllm/stickllm-vault.img"
        meta = tmp / "meta"
        meta.mkdir()
        (meta / "container").write_text(blob + "\n", encoding="utf-8")
        name = LEAF if drive_present else "nvme0n1p2-nvme0n1p2"
        stubs = f"""
set -euo pipefail
HOST_MNT_ROOT='{posix(host)}'
META_DIR='{posix(meta)}'
LOG='{posix(tmp)}/log'
MAPPER_NAME=stickllm-vault; MAPPER=/dev/mapper/stickllm-vault; MNT_POINT='{posix(tmp)}/vault'
need_root() {{ :; }}
is_mounted() {{ [[ -f "$LOG" ]] && grep -q '^vaultmount' "$LOG"; }}
sync_usb_settings() {{ :; }}
maybe_bind_from_settings() {{ :; }}
vault_target() {{ cat "$META_DIR/container"; }}
is_block_device_path() {{ return 1; }}
findmnt() {{ [[ -f "$LOG" ]] && grep -qx "hostmount ${{*: -1}}" "$LOG"; }}
host_mount_name_for_dev() {{ echo '{name}'; }}
mount_host() {{
  [[ "${{STICKLLM_VAULT_CONFIRM:-}}" == MOUNT-HOST ]] || die "no confirm"
  [[ "$1" == /dev/nvme0n1p2 ]] || die "wrong dev $1"
  mkdir -p "$HOST_MNT_ROOT/{LEAF}/home/nink/stickllm"
  : >"$HOST_MNT_ROOT/{LEAF}/home/nink/stickllm/stickllm-vault.img"
  echo "hostmount $HOST_MNT_ROOT/{LEAF}" >>"$LOG"
  echo '{{"ok":true}}'
}}
cryptsetup() {{ return 1; }}
luks_pass() {{ echo luksopen >>"$LOG"; }}
mount() {{ echo vaultmount >>"$LOG"; }}
bump_fail() {{ echo bump_fail >>"$LOG"; }}
ensure_dirs_in_vault() {{ :; }}
json_state() {{ :; }}
refresh_gateway_vault_view() {{ :; }}
"""
        script = "\n".join([
            func(text, "die"),
            stubs,
            func(text, "ensure_host_mount_for_blob"),
            func(text, "cmd_unlock"),
            "STICKLLM_VAULT_PASS=test-passcode cmd_unlock",
        ])
        sh = tmp / "t.sh"
        sh.write_text(script, encoding="utf-8", newline="\n")
        p = subprocess.run([BASH, posix(sh)], capture_output=True, text=True, timeout=60)
        log_path = tmp / "log"
        log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        return p, log

    def test_unmounted_drive_is_mounted_and_unlock_proceeds(self):
        p, log = self.run_unlock(drive_present=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Vault unlocked", p.stdout)
        self.assertIn(f"hostmount", log)
        self.assertIn("luksopen", log)
        self.assertLess(log.index("hostmount"), log.index("luksopen"))
        self.assertNotIn("bump_fail", log)

    def test_missing_drive_gives_clear_error_without_fail_bump(self):
        p, log = self.run_unlock(drive_present=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("Host SSD not mounted: " + LEAF, p.stderr)
        self.assertIn("Press Mount on the drive, then Unlock.", p.stderr)
        self.assertNotIn("blob missing", p.stderr)
        self.assertNotIn("hostmount", log)
        self.assertNotIn("luksopen", log)
        self.assertNotIn("bump_fail", log)


class UnlockHostMountTextTests(unittest.TestCase):
    def test_auto_mount_reuses_mount_host_and_naming_matches(self):
        text = VAULT.read_text(encoding="utf-8")
        body = func(text, "ensure_host_mount_for_blob")
        self.assertIn("STICKLLM_VAULT_CONFIRM=MOUNT-HOST mount_host", body)
        for bad in ("mkfs", "wipefs", "parted", "sgdisk", "luksFormat", "cryptsetup"):
            self.assertNotIn(bad, body)
        naming = 'safe = re.sub(r"[^A-Za-z0-9_-]+", "-", '
        self.assertIn(naming, func(text, "mount_host"))
        self.assertIn(naming, func(text, "host_mount_name_for_dev"))
        self.assertIn('mname = f"{safe}-{part}"[:64]', func(text, "mount_host"))
        self.assertIn('print(f"{safe}-{part}"[:64])', func(text, "host_mount_name_for_dev"))

    def test_settings_failures_are_logged_not_silenced(self):
        text = VAULT.read_text(encoding="utf-8")
        for name in ("sync_usb_settings", "maybe_bind_from_settings"):
            body = func(text, name)
            self.assertNotIn("|| true", body.replace("ensure_host_mount_for_blob \"$blob\" >/dev/null || true", ""))
            self.assertIn(">&2", body)
            self.assertNotIn("$pass\" >&2", body)


if __name__ == "__main__":
    unittest.main()
