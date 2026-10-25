"""USB settings partition planner and record rules. No disks, no cryptsetup."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_usb_settings.py"
CLAIM = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-usb-claim"
SETTINGS = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-usb-settings"
VAULT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-vault"


def load_mod():
    spec = importlib.util.spec_from_file_location("stickllm_usb_settings", LIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = load_mod()


class PlanTests(unittest.TestCase):
    def test_sixty_gb_stick_puts_256_mib_beside_data(self):
        # ~60 GB stick with the live image already occupying the front.
        # 45000 MiB free is the unallocated tail, not space inside the ISO.
        plan = S.plan_free_region(8192, 45000)
        self.assertEqual(plan["settings"]["size_mib"], 256)
        self.assertEqual(plan["settings"]["start_mib"], 8192 + 45000 - 256)
        self.assertEqual(plan["data"]["start_mib"], 8192)
        self.assertEqual(plan["data"]["end_mib"], plan["settings"]["start_mib"])
        self.assertEqual(
            plan["data"]["size_mib"] + plan["settings"]["size_mib"],
            45000,
        )
        self.assertNotIn("iso", plan["note"].lower())

    def test_existing_data_is_not_shrunk(self):
        plan = S.plan_free_region(60000, 40, data_exists=True)
        self.assertIsNone(plan["settings"])
        self.assertIsNone(plan["data"])
        self.assertIn("Refusing to shrink", plan["note"])

    def test_existing_data_gets_settings_when_space_remains(self):
        plan = S.plan_free_region(60000, 300, data_exists=True)
        self.assertIsNone(plan["data"])
        self.assertEqual(plan["settings"]["size_mib"], 256)
        self.assertEqual(plan["settings"]["start_mib"], 60000)

    def test_small_gap_keeps_data_and_skips_settings(self):
        # 1024 MiB fits DATA. 256 more is required before a settings partition.
        plan = S.plan_free_region(100, 1200)
        self.assertEqual(plan["data"]["size_mib"], 1200)
        self.assertIsNone(plan["settings"])

    def test_settings_already_present_does_not_allocate_another(self):
        plan = S.plan_free_region(4000, 20000, settings_exists=True)
        self.assertIsNone(plan["settings"])
        self.assertEqual(plan["data"]["size_mib"], 20000)


class ClassifyTests(unittest.TestCase):
    def _row(self, **kwargs):
        base = dict(
            part="/dev/sdb3",
            part_type="part",
            pkname="sdb",
            boot_disk="sdb",
            size_bytes=256 * 1024 * 1024,
            fstype="",
            label="",
            mountpoint="",
            live_source="/dev/sdb1",
        )
        base.update(kwargs)
        return base

    def test_accepts_raw_256_on_boot_usb(self):
        ok, why = S.classify_settings_partition(**self._row())
        self.assertTrue(ok, why)

    def test_accepts_luks_label(self):
        ok, why = S.classify_settings_partition(
            **self._row(fstype="crypto_LUKS", label="STICKLLM-SETTINGS")
        )
        self.assertTrue(ok, why)

    def test_rejects_host_disk_data_live_and_wrong_size(self):
        self.assertFalse(S.classify_settings_partition(**self._row(boot_disk="nvme0n1"))[0])
        self.assertFalse(S.classify_settings_partition(**self._row(label="STICKLLM-DATA"))[0])
        self.assertFalse(S.classify_settings_partition(**self._row(part="/dev/sdb1", live_source="/dev/sdb1"))[0])
        self.assertFalse(S.classify_settings_partition(**self._row(fstype="vfat", label="EFI"))[0])
        self.assertFalse(S.classify_settings_partition(**self._row(part_type="disk", part="/dev/sdb"))[0])
        self.assertFalse(S.classify_settings_partition(**self._row(size_bytes=50 * 1024 * 1024 * 1024))[0])

    def test_choose_is_fail_closed_when_ambiguous(self):
        rows = [
            {"path": "/dev/sdb3", "type": "part", "pkname": "sdb", "size": 256 * 1024 * 1024, "fstype": "", "label": "", "mountpoint": ""},
            {"path": "/dev/sdb4", "type": "part", "pkname": "sdb", "size": 256 * 1024 * 1024, "fstype": "", "label": "", "mountpoint": ""},
        ]
        row, note = S.choose_settings_partition(rows, "sdb")
        self.assertIsNone(row)
        self.assertIn("ambiguous", note)


class RecordTests(unittest.TestCase):
    def test_location_drops_secrets_and_block_devices(self):
        machine = {"id": "a" * 64, "label": "lab", "id_source": "dmi"}
        doc = S.location_record(
            {
                "blob": "/mnt/stickllm-host/disk/stickllm-vault.img",
                "root": "/mnt/stickllm-host/disk",
                "password": "should-not-stick",
                "passcode": "should-not-stick",
                "token": "should-not-stick",
                "recovery": "should-not-stick",
            },
            machine,
        )
        self.assertNotIn("password", doc)
        self.assertNotIn("passcode", doc)
        self.assertNotIn("token", doc)
        self.assertNotIn("recovery", doc)
        self.assertEqual(doc["machine_id"], "a" * 64)
        self.assertTrue(doc["blob"].endswith("stickllm-vault.img"))
        with self.assertRaises(ValueError):
            S.location_record({"blob": "/dev/sdb1"}, machine)

    def test_per_computer_records_do_not_leak_across_machines(self):
        mnt = Path(self._tmp())
        a = {"id": "a" * 64, "label": "a", "id_source": "dmi"}
        b = {"id": "b" * 64, "label": "b", "id_source": "dmi"}
        S.write_computer_file(mnt, {"blob": "/data/a/stickllm-vault.img", "version": 1}, a)
        S.write_computer_file(mnt, {"blob": "/data/b/stickllm-vault.img", "version": 1}, b)
        self.assertEqual(S.read_computer_blob(mnt, a), "/data/a/stickllm-vault.img")
        self.assertEqual(S.read_computer_blob(mnt, b), "/data/b/stickllm-vault.img")
        text = (mnt / "computers" / f"{'a' * 64}.json").read_text(encoding="utf-8")
        self.assertNotIn("password", text)

    def test_secrets_roundtrip_without_weight_names(self):
        mnt = Path(self._tmp())
        value = "example-secret-value"
        result = S.write_secret(mnt, "hf-token", value)
        self.assertTrue(result["saved"])
        self.assertEqual(S.read_secret(mnt, "hf-token"), value)
        self.assertEqual(S.list_secrets(mnt), ["hf-token"])
        listed = json.dumps(S.list_secrets(mnt))
        self.assertNotIn(value, listed)
        for bad in ("../x", "Chats", "ggml-tiny.en.bin", "voices.onnx", "chats"):
            ok, _why = S.validate_secret_name(bad)
            self.assertFalse(ok, bad)
        with self.assertRaises(ValueError):
            S.write_secret(S.SPEECH_DIR, "hf-token", value)
        with self.assertRaises(ValueError):
            S.assert_settings_mount(S.VAULT_MNT)

    def test_layout_constants(self):
        self.assertEqual(S.SETTINGS_MIB, 256)
        self.assertEqual(S.LAYOUT_DIRS, ("computers", "secrets"))
        self.assertNotIn("chats", S.LAYOUT_DIRS)
        self.assertNotEqual(S.SETTINGS_MNT, S.SPEECH_DIR)
        self.assertNotEqual(S.SETTINGS_MNT, S.VAULT_MNT)
        self.assertEqual(S.SPEECH_DIR, "/opt/stickllm/speech")

    def test_machine_id_ignores_oem_placeholders(self):
        mid = S.machine_id(
            {
                "/sys/class/dmi/id/product_uuid": "To be filled by O.E.M.",
                "/sys/class/dmi/id/product_serial": "lab-serial",
                "/sys/class/dmi/id/board_serial": "",
                "/sys/class/dmi/id/product_name": "Test Board",
            }
        )
        self.assertEqual(mid["id_source"], "dmi")
        self.assertEqual(mid["label"], "Test Board")
        self.assertEqual(len(mid["id"]), 64)
        unknown = S.machine_id({})
        self.assertEqual(unknown["id_source"], "unknown")

    def _tmp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="stickllm-settings-")


class ScriptGuardTests(unittest.TestCase):
    def test_claim_reserves_settings_and_does_not_shrink(self):
        text = CLAIM.read_text(encoding="utf-8")
        self.assertIn("--settings-only", text)
        self.assertIn("stickllm_usb_settings.py", text)
        self.assertNotIn("resizepart", text)
        self.assertNotIn("ntfsresize", text)
        self.assertNotIn("mkfs.ext4 -F -L STICKLLM-SETTINGS", text)

    def test_settings_format_is_gated_and_speech_stays_out(self):
        text = SETTINGS.read_text(encoding="utf-8")
        self.assertIn("assert-part", text)
        self.assertIn("/opt/stickllm/speech", text)
        self.assertIn("STICKLLM_SETTINGS_INIT", text)
        self.assertNotIn("wipefs", text)
        body = text.split("cmd_open_or_init()", 1)[1].split("\ncmd_", 1)[0]
        self.assertLess(body.index("assert_part"), body.index("luksFormat"))

    def test_vault_still_refuses_host_partition_and_formats_only_the_blob(self):
        text = VAULT.read_text(encoding="utf-8")
        self.assertIn("create-partition is disabled", text)
        self.assertIn("sync_usb_settings", text)
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            self.assertNotIn("wipefs", line)
            if "luks_pass" in line and "luksFormat" in line:
                self.assertIn("blob", line)


if __name__ == "__main__":
    unittest.main()
