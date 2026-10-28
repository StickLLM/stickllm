"""USB stick settings partition — planner and record helpers.

The settings area is a ~256 MiB partition on the StickLLM boot USB, beside
the live image. It is not a file inside the ISO and it is not the SSD vault.

Encryption uses the SSD vault's existing LUKS2 passphrase (and, when those
already exist, the same stick keyfile and recovery digest). There is no
second password. This module does not format disks and does not touch host
drives. stickllm-usb-claim creates the partition. stickllm-usb-settings
opens it after the vault passcode is accepted.

Layout inside the unlocked filesystem:
  computers/<machine-id>.json   per-computer SSD vault location (no passcode)
  secrets/<name>                portable API keys and passwords

Voice weights stay in /opt/stickllm/speech. Chats stay in the SSD vault.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

SETTINGS_MIB = 256
MIN_DATA_MIB = 1024
# Accept parted alignment slack around the requested 256 MiB.
SETTINGS_SIZE_LO = 200 * 1024 * 1024
SETTINGS_SIZE_HI = 320 * 1024 * 1024
SETTINGS_MNT = "/mnt/stickllm-settings"
DATA_MNT = "/mnt/stickllm-data"
VAULT_MNT = "/var/lib/stickllm/vault"
SPEECH_DIR = "/opt/stickllm/speech"
LAYOUT_DIRS = ("computers", "secrets")
POINTER_NAME = "stickllm-settings-part.json"
COMPUTER_ID_NAME = "this-computer-id"

SECRET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
WEIGHT_SUFFIXES = (
    ".gguf",
    ".onnx",
    ".bin",
    ".npz",
    ".pt",
    ".safetensors",
    ".ckpt",
)
RESERVED_SECRET_NAMES = {
    "chats",
    "models",
    "speech",
    "vault",
    "computers",
    "secrets",
    "whisper",
    "kitten",
}
REFUSE_LABELS = {
    "STICKLLM-DATA",
    "STICKLLM",
    "PRIVACYAI",
    "EFI",
    "ESP",
}
REFUSE_FSTYPES = {
    "vfat",
    "iso9660",
    "udf",
    "ext2",
    "ext3",
    "ext4",
    "xfs",
    "btrfs",
    "ntfs",
    "ntfs3",
    "exfat",
    "swap",
    "bitlocker",
    "linux_raid_member",
    "lvm2_member",
}
LOCATION_FIELDS = (
    "version",
    "blob",
    "root",
    "blob_name",
    "relative_under_mount",
    "relative_from_host_mnt",
    "mount_path",
    "mount_leaf",
    "part_name",
    "disk_model",
    "fstype",
    "source",
    "updated_utc",
    "safety",
    "machine_id",
    "machine_label",
    "id_source",
)
DMI_PLACEHOLDERS = {
    "",
    "none",
    "unknown",
    "to be filled by o.e.m.",
    "not specified",
    "default string",
    "system serial number",
    "0",
}


def plan_free_region(
    free_start_mib: int,
    free_size_mib: int,
    *,
    data_exists: bool = False,
    settings_exists: bool = False,
) -> dict:
    """Split a free region on the boot USB. Never shrinks an existing partition."""
    free_start_mib = int(free_start_mib)
    free_size_mib = int(free_size_mib)
    if free_start_mib < 0 or free_size_mib < 0:
        raise ValueError("free region must be non-negative")
    out = {
        "settings_mib": SETTINGS_MIB,
        "data": None,
        "settings": None,
        "note": "",
    }
    if data_exists and settings_exists:
        out["note"] = "STICKLLM-DATA and the settings partition are already present"
        return out
    if settings_exists and not data_exists:
        if free_size_mib < MIN_DATA_MIB:
            out["note"] = (
                f"settings partition already present; remaining {free_size_mib} MiB "
                f"is under {MIN_DATA_MIB} MiB so STICKLLM-DATA was not created"
            )
            return out
        out["data"] = _span(free_start_mib, free_size_mib)
        out["note"] = "settings partition already present; DATA uses the remaining free space"
        return out
    if data_exists and not settings_exists:
        if free_size_mib < SETTINGS_MIB:
            out["note"] = (
                "STICKLLM-DATA already fills the stick. Refusing to shrink it. "
                "No 256 MiB settings partition."
            )
            return out
        out["settings"] = _span(free_start_mib, SETTINGS_MIB)
        out["note"] = "settings partition only; existing STICKLLM-DATA is left untouched"
        return out
    if free_size_mib < MIN_DATA_MIB:
        out["note"] = f"free space {free_size_mib} MiB is under {MIN_DATA_MIB} MiB"
        return out
    if free_size_mib < MIN_DATA_MIB + SETTINGS_MIB:
        out["data"] = _span(free_start_mib, free_size_mib)
        out["note"] = (
            "free space fits STICKLLM-DATA but not a 256 MiB settings partition beside it"
        )
        return out
    settings_start = free_start_mib + free_size_mib - SETTINGS_MIB
    data_size = settings_start - free_start_mib
    out["data"] = _span(free_start_mib, data_size)
    out["settings"] = _span(settings_start, SETTINGS_MIB)
    out["note"] = "DATA plus a 256 MiB settings partition at the end of free space on the boot USB"
    return out


def _span(start_mib: int, size_mib: int) -> dict:
    return {
        "start_mib": int(start_mib),
        "size_mib": int(size_mib),
        "end_mib": int(start_mib) + int(size_mib),
    }


def classify_settings_partition(
    *,
    part: str,
    part_type: str,
    pkname: str,
    boot_disk: str,
    size_bytes: int,
    fstype: str = "",
    label: str = "",
    mountpoint: str = "",
    live_source: str = "",
) -> tuple[bool, str]:
    """True only for the boot USB's ~256 MiB settings slot. Host disks fail closed."""
    part = str(part or "")
    if not part.startswith("/dev/"):
        return False, "path is not a device node"
    if str(part_type or "") != "part":
        return False, "not a partition"
    boot_disk = str(boot_disk or "")
    pkname = str(pkname or "")
    if not boot_disk or pkname != boot_disk:
        return False, "not on the StickLLM boot USB"
    base = part.rsplit("/", 1)[-1]
    if base == pkname or base == boot_disk:
        return False, "refusing whole disk"
    live_source = str(live_source or "")
    if live_source and part == live_source:
        return False, "refusing the live image partition"
    if str(mountpoint or "").strip():
        return False, "partition is already mounted"
    lab = str(label or "").strip()
    if lab.upper() in REFUSE_LABELS:
        return False, "live image or STICKLLM-DATA partition"
    fs = str(fstype or "").strip()
    fs_key = fs.lower()
    if fs_key == "crypto_luks":
        if lab and lab != "STICKLLM-SETTINGS":
            return False, "LUKS label is not STICKLLM-SETTINGS"
    elif fs_key == "":
        if lab:
            return False, "raw partition has an unexpected label"
    elif fs_key in REFUSE_FSTYPES or fs_key:
        return False, f"filesystem {fs} is not an empty settings slot or LUKS"
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return False, "size missing"
    if size < SETTINGS_SIZE_LO or size > SETTINGS_SIZE_HI:
        return False, "size is not about 256 MiB"
    return True, "ok"


def flatten_lsblk(doc: dict) -> list[dict]:
    rows: list[dict] = []

    def walk(nodes, parent_disk: str = "") -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name") or "")
            ntype = str(node.get("type") or "")
            pk = str(node.get("pkname") or "")
            if ntype == "disk":
                disk_name = name
            else:
                disk_name = pk or parent_disk
            path = str(node.get("path") or (f"/dev/{name}" if name else ""))
            rows.append(
                {
                    "name": name,
                    "path": path,
                    "type": ntype,
                    "pkname": disk_name,
                    "size": int(node.get("size") or 0),
                    "fstype": str(node.get("fstype") or ""),
                    "label": str(node.get("label") or ""),
                    "mountpoint": str(node.get("mountpoint") or ""),
                }
            )
            walk(node.get("children"), disk_name if ntype == "disk" else parent_disk)

    walk(doc.get("blockdevices") if isinstance(doc, dict) else None)
    return rows


def choose_settings_partition(
    rows: list[dict],
    boot_disk: str,
    *,
    preferred: str = "",
    live_source: str = "",
) -> tuple[dict | None, str]:
    ok: list[dict] = []
    for row in rows:
        good, _why = classify_settings_partition(
            part=str(row.get("path") or ""),
            part_type=str(row.get("type") or ""),
            pkname=str(row.get("pkname") or ""),
            boot_disk=boot_disk,
            size_bytes=int(row.get("size") or 0),
            fstype=str(row.get("fstype") or ""),
            label=str(row.get("label") or ""),
            mountpoint=str(row.get("mountpoint") or ""),
            live_source=live_source,
        )
        if good:
            ok.append(row)
    if preferred:
        for row in ok:
            if row.get("path") == preferred:
                return row, "preferred"
    if len(ok) == 1:
        return ok[0], "only candidate on the boot USB"
    if len(ok) > 1:
        return None, "ambiguous 256 MiB partitions on the boot USB; refusing to guess"
    return None, "no settings partition on the boot USB"


def pointer_doc(disk: str, part: str, size_bytes: int, start_mib: int | None = None) -> dict:
    doc = {
        "version": 1,
        "role": "usb-settings",
        "size_mib": SETTINGS_MIB,
        "size_bytes": int(size_bytes),
        "disk": str(disk),
        "part": str(part),
        "safety": "partition identity only — never a passcode or secret",
    }
    if start_mib is not None:
        doc["start_mib"] = int(start_mib)
    return doc


def _usable_dmi(value: str) -> bool:
    text = " ".join(str(value or "").split())
    return text.lower() not in DMI_PLACEHOLDERS


def machine_id(reads: dict | None = None) -> dict:
    """Stable per computer. Live-USB /etc/machine-id changes every boot, so prefer DMI."""
    paths = (
        "/sys/class/dmi/id/product_uuid",
        "/sys/class/dmi/id/product_serial",
        "/sys/class/dmi/id/board_serial",
    )
    name_path = "/sys/class/dmi/id/product_name"
    values: list[str] = []
    source = "dmi"

    def read_path(path: str) -> str:
        if reads is not None:
            return str(reads.get(path) or "")
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    for path in paths:
        text = " ".join(read_path(path).split())
        if _usable_dmi(text):
            values.append(text)
    label = " ".join(read_path(name_path).split())
    if not _usable_dmi(label):
        label = "this computer"
    label = label[:80]
    if not values:
        source = "unknown"
        values = ["stickllm-unknown-computer"]
        label = "unknown computer"
    digest = hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()
    return {"id": digest, "label": label, "id_source": source}


def location_record(source: dict, machine: dict | None = None) -> dict:
    """Copy path hints only. Block-device blobs and secret fields are dropped."""
    machine = machine or machine_id()
    blob = str(source.get("blob") or "")
    if blob.startswith("/dev/") or blob.startswith("\\\\.\\"):
        raise ValueError("refusing block device vault path")
    doc = {key: source.get(key) for key in LOCATION_FIELDS if key in source}
    doc["version"] = int(source.get("version") or 1)
    doc["blob"] = blob
    doc["machine_id"] = machine["id"]
    doc["machine_label"] = machine["label"]
    doc["id_source"] = machine["id_source"]
    doc["safety"] = "path hint only — never stores passcode or recovery phrase"
    for bad in ("pass", "passcode", "password", "recovery", "key", "pin", "token", "secret"):
        doc.pop(bad, None)
    return doc


def assert_settings_mount(mnt: str | Path) -> Path:
    path = Path(mnt)
    norm = os.path.normpath(str(path))
    for banned in (SPEECH_DIR, VAULT_MNT):
        if norm == os.path.normpath(banned):
            raise ValueError(f"refusing {banned}")
    speech = os.path.normpath(SPEECH_DIR)
    if norm == speech or norm.startswith(speech + os.sep):
        raise ValueError("voice weights stay in /opt/stickllm/speech")
    return path


def validate_secret_name(name: str) -> tuple[bool, str]:
    text = str(name or "")
    if not SECRET_NAME_RE.fullmatch(text):
        return False, "secret name must be a short lowercase file name"
    if text in RESERVED_SECRET_NAMES:
        return False, "secret name is reserved"
    lower = text.lower()
    if lower.endswith(WEIGHT_SUFFIXES) or "ggml" in lower or "whisper" in lower or "kitten" in lower:
        return False, "voice and model weights are not stored in stick settings"
    return True, "ok"


def secret_file(mnt: str | Path, name: str) -> Path:
    root = assert_settings_mount(mnt) / "secrets"
    ok, why = validate_secret_name(name)
    if not ok:
        raise ValueError(why)
    path = root / name
    if path.parent != root:
        raise ValueError("secret path escapes the secrets directory")
    return path


def _atomic_write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def write_computer_file(mnt: str | Path, source: dict, machine: dict | None = None) -> Path:
    root = assert_settings_mount(mnt)
    machine = machine or machine_id()
    doc = location_record(source, machine)
    if not doc.get("blob"):
        raise ValueError("location is missing a blob path")
    dest_dir = root / "computers"
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dest_dir, 0o700)
    except OSError:
        pass
    path = dest_dir / f"{machine['id']}.json"
    _atomic_write(path, json.dumps(doc, indent=2) + "\n", 0o600)
    _atomic_write(root / COMPUTER_ID_NAME, machine["id"] + "\n", 0o600)
    return path


def read_computer_blob(mnt: str | Path, machine: dict | None = None) -> str:
    """Location for this computer only. A record for another machine is ignored."""
    root = assert_settings_mount(mnt)
    machine = machine or machine_id()
    cid = str(machine.get("id") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", cid):
        return ""
    path = root / "computers" / f"{cid}.json"
    if not path.is_file():
        return ""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return ""
    blob = str(doc.get("blob") or "")
    if not blob or blob.startswith("/dev/") or blob.startswith("\\\\.\\"):
        return ""
    return blob


def write_secret(mnt: str | Path, name: str, value: str) -> dict:
    text = str(value or "")
    if not text or any(ch in text for ch in "\n\r\x00"):
        raise ValueError("secret value is empty or contains a newline")
    if len(text) > 4000:
        raise ValueError("secret value is too long")
    path = secret_file(mnt, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    _atomic_write(path, text + "\n", 0o600)
    return {"ok": True, "saved": True, "name": name}


def read_secret(mnt: str | Path, name: str) -> str:
    path = secret_file(mnt, name)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def delete_secret(mnt: str | Path, name: str) -> dict:
    path = secret_file(mnt, name)
    if path.is_file():
        path.unlink()
    return {"ok": True, "deleted": True, "name": name}


def list_secrets(mnt: str | Path) -> list[str]:
    root = assert_settings_mount(mnt) / "secrets"
    if not root.is_dir():
        return []
    names = []
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        ok, _why = validate_secret_name(path.name)
        if ok:
            names.append(path.name)
    return names


def _arg(flag: str, default: str = "") -> str:
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return default


def _cmd_plan() -> int:
    doc = plan_free_region(
        int(_arg("--free-start", "0")),
        int(_arg("--free-size", "0")),
        data_exists=_arg("--data-exists", "0") == "1",
        settings_exists=_arg("--settings-exists", "0") == "1",
    )
    print(json.dumps(doc))
    return 0


def _cmd_choose() -> int:
    raw = sys.stdin.read()
    try:
        doc = json.loads(raw or "{}")
    except json.JSONDecodeError:
        print("lsblk json was not readable", file=sys.stderr)
        return 1
    row, note = choose_settings_partition(
        flatten_lsblk(doc),
        _arg("--boot-disk"),
        preferred=_arg("--preferred"),
        live_source=_arg("--live-source"),
    )
    if row is None:
        print(note, file=sys.stderr)
        return 3 if "ambiguous" in note else 1
    print(row["path"])
    return 0


def _cmd_assert_part() -> int:
    ok, why = classify_settings_partition(
        part=_arg("--part"),
        part_type=_arg("--type", "part"),
        pkname=_arg("--pkname"),
        boot_disk=_arg("--boot-disk"),
        size_bytes=int(_arg("--size", "0") or "0"),
        fstype=_arg("--fstype"),
        label=_arg("--label"),
        mountpoint=_arg("--mountpoint"),
        live_source=_arg("--live-source"),
    )
    if not ok:
        print(why, file=sys.stderr)
        return 1
    print("ok")
    return 0


def _cmd_write_computer() -> int:
    src_path = Path(_arg("--from"))
    mnt = _arg("--mnt", SETTINGS_MNT)
    if not src_path.is_file():
        return 0
    source = json.loads(src_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        print("location file is not an object", file=sys.stderr)
        return 1
    path = write_computer_file(mnt, source)
    print(path)
    return 0


def _cmd_print_blob() -> int:
    blob = read_computer_blob(_arg("--mnt", SETTINGS_MNT))
    if not blob:
        return 1
    print(blob)
    return 0


def _cmd_write_pointer() -> int:
    mnt = Path(_arg("--mnt"))
    doc = pointer_doc(
        _arg("--disk"),
        _arg("--part"),
        int(_arg("--size", "0") or "0"),
        int(_arg("--start-mib")) if _arg("--start-mib") else None,
    )
    path = mnt / POINTER_NAME
    _atomic_write(path, json.dumps(doc, indent=2) + "\n", 0o644)
    print(path)
    return 0


def _cmd_write_secret() -> int:
    value = os.environ.get("STICKLLM_SECRET_VALUE", "")
    result = write_secret(_arg("--mnt", SETTINGS_MNT), _arg("--name"), value)
    print(json.dumps(result))
    return 0


def _cmd_read_secret() -> int:
    value = read_secret(_arg("--mnt", SETTINGS_MNT), _arg("--name"))
    if not value:
        return 1
    print(value)
    return 0


def _cmd_delete_secret() -> int:
    print(json.dumps(delete_secret(_arg("--mnt", SETTINGS_MNT), _arg("--name"))))
    return 0


def _cmd_list_secrets() -> int:
    print(json.dumps({"ok": True, "names": list_secrets(_arg("--mnt", SETTINGS_MNT))}))
    return 0


def main(argv: list[str] | None = None) -> int:
    global_argv = sys.argv
    if argv is not None:
        sys.argv = [global_argv[0], *argv]
    try:
        cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        commands = {
            "plan": _cmd_plan,
            "choose": _cmd_choose,
            "assert-part": _cmd_assert_part,
            "write-computer": _cmd_write_computer,
            "print-blob": _cmd_print_blob,
            "write-pointer": _cmd_write_pointer,
            "machine-id": lambda: (print(json.dumps(machine_id())) or 0),
            "write-secret": _cmd_write_secret,
            "read-secret": _cmd_read_secret,
            "delete-secret": _cmd_delete_secret,
            "list-secrets": _cmd_list_secrets,
        }
        fn = commands.get(cmd)
        if fn is None:
            print("usage: stickllm_usb_settings.py plan|choose|assert-part|write-computer|...", file=sys.stderr)
            return 2
        return int(fn())
    finally:
        sys.argv = global_argv


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
