#!/usr/bin/env python3
"""StickLLM chat store: one chat list for the chat app and Agent Zero.

Design (docs/CHATS.md):
  * Durable chats live only in an encrypted store. Two stores exist:
      ssd -> <vault>/chats                 (LUKS blob, usually on the host SSD)
      usb -> /mnt/stickllm-settings/chats  (LUKS settings partition on the stick)
    Settings > Chat picks the active one. Both open with the vault passcode.
  * Session mode gates Agent Zero's bind mount:
      vault     -> <active store>/agent-zero  (persist)
      ephemeral -> /run/stickllm/a0-chats     (tmpfs/RAM; reboot clears)
    Mode switch remounts via stickllm-agent try-restart (does not lock LUKS).
  * The gateway lists both kinds: StickLLM chats (<id>.json) and A0 chats
    (agent-zero/<ctxid>/chat.json). Each StickLLM chat is also exported as an
    A0 chat (agent-zero/stickllm-<id>/chat.json) so the A0 panel lists it too.
    When A0 continued an exported chat (its file is newer), the new turns are
    read back into the StickLLM chat: newest wins.
  * Optional sync copies chats between the two stores (both ways, newest wins,
    deletions are carried by tombstones in .deleted/).

Never logs chat text or passcodes.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
SETTINGS_MNT = Path(os.environ.get("STICKLLM_SETTINGS_MNT", "/mnt/stickllm-settings"))
RUN_DIR = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
SESSION_MODE_PATH = Path(
    os.environ.get("STICKLLM_SESSION_MODE_PATH", str(RUN_DIR / "session-mode.json"))
)
# Ephemeral A0 chats: host /run is tmpfs. Never under the LUKS vault.
EPHEMERAL_A0_CHATS = Path(
    os.environ.get("STICKLLM_A0_EPHEMERAL_CHATS", str(RUN_DIR / "a0-chats"))
)
STORES = ("ssd", "usb")
SESSION_MODES = frozenset({"ephemeral", "vault"})
A0_SUBDIR = "agent-zero"
EXPORT_PREFIX = "stickllm-"
TOMBSTONES = ".deleted"
ID_RE = re.compile(r"[^a-zA-Z0-9_-]")
# The USB settings partition is about 256 MiB. Keep a floor free for secrets,
# A0 settings and the computers list.
USB_MIN_FREE = 24 * 1024 * 1024


def clean_id(raw: str | None) -> str:
    return ID_RE.sub("", str(raw or ""))[:64]


def is_mount(path: Path) -> bool:
    try:
        if os.path.ismount(str(path)):
            return True
    except OSError:
        pass
    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as fh:
            return any(len(p) >= 2 and p[1] == str(path) for p in (l.split() for l in fh))
    except OSError:
        return False


def store_roots(
    vault_mnt: Path = VAULT_MNT,
    settings_mnt: Path = SETTINGS_MNT,
    mounted: Callable[[Path], bool] = is_mount,
) -> dict[str, Path]:
    """Encrypted stores that are open right now."""
    out: dict[str, Path] = {}
    if mounted(vault_mnt):
        out["ssd"] = vault_mnt / "chats"
    if mounted(settings_mnt):
        out["usb"] = settings_mnt / "chats"
    return out


# --- preference ------------------------------------------------------------

def pref_paths(vault_mnt: Path = VAULT_MNT, settings_mnt: Path = SETTINGS_MNT) -> list[Path]:
    return [settings_mnt / "stickllm" / "chat-store.json", vault_mnt / "settings" / "chat-store.json"]


def load_pref(vault_mnt: Path = VAULT_MNT, settings_mnt: Path = SETTINGS_MNT) -> dict:
    for p in pref_paths(vault_mnt, settings_mnt):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            store = doc.get("store") if doc.get("store") in STORES else "ssd"
            return {"store": store, "sync": bool(doc.get("sync"))}
    return {"store": "ssd", "sync": False}


def save_pref(store: str, sync: bool, roots: dict[str, Path],
              vault_mnt: Path = VAULT_MNT, settings_mnt: Path = SETTINGS_MNT) -> dict:
    if store not in STORES:
        return {"ok": False, "error": "store must be ssd or usb"}
    if store not in roots:
        where = "USB vault (stick settings)" if store == "usb" else "SSD vault"
        return {"ok": False, "error": f"The {where} is not open. Unlock it first."}
    doc = {"store": store, "sync": bool(sync), "updated": int(time.time())}
    wrote = 0
    targets = []
    if "usb" in roots:
        targets.append(pref_paths(vault_mnt, settings_mnt)[0])
    if "ssd" in roots:
        targets.append(pref_paths(vault_mnt, settings_mnt)[1])
    for p in targets:
        try:
            write_atomic(p, json.dumps(doc, indent=2) + "\n")
            wrote += 1
        except OSError:
            pass
    if not wrote:
        return {"ok": False, "error": "could not save the chat setting"}
    return {"ok": True, **doc}


def active_root(pref: dict, roots: dict[str, Path]) -> tuple[str | None, Path | None, bool]:
    """(store, path, fell_back). Falls back to the other encrypted store."""
    want = pref.get("store") if pref.get("store") in STORES else "ssd"
    if want in roots:
        return want, roots[want], False
    for other in STORES:
        if other in roots:
            return other, roots[other], True
    return None, None, False


# --- files -----------------------------------------------------------------

def write_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    """tmp + fsync + rename: a chat is never half written (0.5.9 used write_text)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        try:
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path) -> tuple[dict | None, str]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        return None, f"unreadable: {e.__class__.__name__}"
    if not raw.strip():
        return None, "empty file"
    try:
        doc = json.loads(raw.decode("utf-8-sig", errors="replace"))
    except ValueError:
        return None, "not valid JSON"
    if not isinstance(doc, dict):
        return None, "not a chat object"
    return doc, ""


def _ts(value, fallback: float = 0.0) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            pass
    return int(fallback)


def clean_messages(messages) -> list[dict]:
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        if role in ("user", "assistant", "system") and content:
            out.append({"role": role, "content": content[:100_000]})
    return out


# --- Agent Zero chat format (v2.15 helpers/persist_chat.py) ------------------

def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def stickllm_to_a0(doc: dict) -> dict:
    """A StickLLM chat as an A0 context A0 can load and continue."""
    cid = clean_id(doc.get("id"))
    updated = _ts(doc.get("updated"), time.time())
    created = _ts(doc.get("created"), updated)
    logs = []
    hist = []
    seq = 0
    for m in clean_messages(doc.get("messages")):
        if m["role"] == "system":
            continue
        ai = m["role"] == "assistant"
        logs.append({
            "no": len(logs),
            "id": str(uuid.uuid4()),
            "type": "response" if ai else "user",
            "heading": "StickLLM" if ai else "",
            "content": m["content"],
            "kvps": None,
            "timestamp": float(updated),
            "agentno": 0,
        })
        if ai:
            content = json.dumps({
                "thoughts": [],
                "headline": "Reply from the StickLLM chat app",
                "tool_name": "response",
                "tool_args": {"text": m["content"]},
            }, ensure_ascii=False)
        else:
            content = {"system_message": [], "user_message": m["content"], "attachments": []}
        hist.append({
            "_cls": "Message", "id": str(uuid.uuid4()), "ai": ai, "content": content,
            "metadata": {}, "sequence": seq, "summary": "", "tokens": 0,
        })
        seq += 1
    history = {
        "_cls": "History", "counter": seq, "bulks": [], "topics": [],
        "current": {"_cls": "Topic", "summary": "", "messages": hist},
    }
    return {
        "id": EXPORT_PREFIX + cid,
        "name": str(doc.get("title") or "Chat")[:120],
        "created_at": _iso(created),
        "type": "user",
        "last_message": _iso(updated),
        "agents": [{"number": 0, "agent_profile": "", "data": {},
                    "history": json.dumps(history, ensure_ascii=False)}],
        "streaming_agent": 0,
        "agent_profile": "",
        "log": {"guid": str(uuid.uuid4()), "logs": logs, "progress": "", "progress_no": 0},
        "data": {"stickllm_chat_id": cid, "stickllm_updated": updated},
        "output_data": {},
    }


def a0_to_messages(doc: dict) -> list[dict]:
    """What the chat app shows for an A0 chat: user lines and final replies."""
    out = []
    logs = ((doc.get("log") or {}).get("logs")) or []
    for item in logs:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        text = item.get("content")
        if not isinstance(text, str) or not text.strip():
            continue
        if kind == "user":
            out.append({"role": "user", "content": text})
        elif kind == "response" and int(item.get("agentno") or 0) == 0:
            out.append({"role": "assistant", "content": text})
    return out


def a0_updated(doc: dict, path: Path) -> int:
    fallback = 0.0
    try:
        fallback = path.stat().st_mtime
    except OSError:
        pass
    best = _ts(doc.get("last_message"), fallback)
    # A0 rewrites the file on every turn; mtime is the real last change.
    return max(best, int(fallback))


# --- listing ----------------------------------------------------------------

def list_chats(root: Path, log: Callable[[str], None] | None = None) -> dict:
    """Both kinds of chats in one list. Bad files are reported, not dropped silently."""
    chats: dict[str, dict] = {}
    skipped: list[dict] = []
    if not root.is_dir():
        return {"chats": [], "skipped": [], "root_exists": False}
    for p in sorted(root.glob("*.json")):
        doc, why = read_json(p)
        if doc is None:
            skipped.append({"file": p.name, "reason": why})
            continue
        cid = clean_id(doc.get("id")) or p.stem
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0
        chats[cid] = {
            "id": cid,
            "title": str(doc.get("title") or p.stem)[:120],
            "updated": _ts(doc.get("updated"), mtime),
            "messages": len(doc.get("messages") or []),
            "source": "stickllm",
        }
    a0 = root / A0_SUBDIR
    if a0.is_dir():
        for folder in sorted(a0.iterdir()):
            f = folder / "chat.json"
            if not f.is_file():
                continue
            doc, why = read_json(f)
            if doc is None:
                skipped.append({"file": f"{A0_SUBDIR}/{folder.name}/chat.json", "reason": why})
                continue
            if str(doc.get("type") or "user") != "user":
                continue  # tasks and background contexts stay in A0
            upd = a0_updated(doc, f)
            if folder.name.startswith(EXPORT_PREFIX):
                cid = folder.name[len(EXPORT_PREFIX):]
                row = chats.get(cid)
                if row is not None:
                    if upd > int(row["updated"]) + 2:
                        row["updated"] = upd
                        row["a0_newer"] = True
                    row["in_agent_zero"] = True
                    continue
            cid = "a0-" + clean_id(folder.name)
            chats[cid] = {
                "id": cid,
                "title": str(doc.get("name") or "Agent Zero chat")[:120],
                "updated": upd,
                "messages": len(a0_to_messages(doc)),
                "source": "agent-zero",
                "in_agent_zero": True,
            }
    rows = sorted(chats.values(), key=lambda r: int(r.get("updated") or 0), reverse=True)
    if skipped and log:
        log(f"chat list: skipped {len(skipped)} unreadable file(s) in {root}: "
            + ", ".join(f"{s['file']} ({s['reason']})" for s in skipped[:5]))
    return {"chats": rows, "skipped": skipped, "root_exists": True}


def load_chat(root: Path, chat_id: str) -> dict:
    cid = clean_id(chat_id)
    if not cid:
        return {"ok": False, "error": "id required"}
    if cid.startswith("a0-"):
        f = root / A0_SUBDIR / cid[3:] / "chat.json"
        doc, why = read_json(f)
        if doc is None:
            return {"ok": False, "error": "not found" if "unreadable" in why else why}
        return {"ok": True, "id": cid, "title": doc.get("name") or "Agent Zero chat",
                "updated": a0_updated(doc, f), "messages": a0_to_messages(doc),
                "source": "agent-zero"}
    path = root / f"{cid}.json"
    doc, why = read_json(path)
    if doc is None:
        return {"ok": False, "error": "not found" if not path.exists() else why}
    exp = root / A0_SUBDIR / (EXPORT_PREFIX + cid) / "chat.json"
    a0doc, _ = read_json(exp) if exp.is_file() else (None, "")
    if a0doc is not None:
        upd = a0_updated(a0doc, exp)
        if upd > _ts(doc.get("updated")) + 2:
            msgs = a0_to_messages(a0doc)
            if msgs:
                # A0 continued this chat: its version is newer, so it wins.
                doc["messages"] = msgs
                doc["updated"] = upd
                write_atomic(path, json.dumps(doc, indent=2) + "\n")
    doc["ok"] = True
    doc.setdefault("source", "stickllm")
    return doc


def _space_ok(root: Path, need: int) -> bool:
    try:
        st = os.statvfs(str(root if root.exists() else root.parent))
    except OSError:
        return True
    return st.f_bavail * st.f_frsize - need > USB_MIN_FREE


def save_chat(root: Path, title: str, messages, chat_id: str | None = None,
              store: str = "ssd", export_a0: bool = True) -> dict:
    cid = clean_id(chat_id)
    if cid.startswith("a0-"):
        # Continuing an A0 chat in the small app keeps it in one list: the
        # copy is a normal StickLLM chat that A0 also sees (stickllm-<id>).
        cid = "a0c-" + cid[3:]
    if not cid:
        cid = uuid.uuid4().hex[:16]
    clean = clean_messages(messages)
    title = (str(title or "Chat").strip()[:120]) or "Chat"
    now = int(time.time())
    prev, _ = read_json(root / f"{cid}.json")
    doc = {"id": cid, "title": title, "created": int((prev or {}).get("created") or now),
           "updated": now, "messages": clean}
    text = json.dumps(doc, indent=2) + "\n"
    if store == "usb" and not _space_ok(root, len(text.encode()) * 2):
        return {"ok": False, "error": "The USB vault is almost full. Switch chats to the SSD vault in Settings > Chat."}
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    write_atomic(root / f"{cid}.json", text)
    _untomb(root, cid)
    if export_a0:
        try:
            export_to_a0(root, doc)
        except OSError:
            pass
    return {"ok": True, "id": cid, "title": title, "updated": now}


def export_to_a0(root: Path, doc: dict) -> Path:
    a0doc = stickllm_to_a0(doc)
    path = root / A0_SUBDIR / a0doc["id"] / "chat.json"
    write_atomic(path, json.dumps(a0doc, ensure_ascii=False) + "\n")
    return path


def delete_chat(root: Path, chat_id: str) -> dict:
    import shutil
    cid = clean_id(chat_id)
    if not cid:
        return {"ok": False, "error": "id required"}
    if cid.startswith("a0-"):
        shutil.rmtree(root / A0_SUBDIR / cid[3:], ignore_errors=True)
    else:
        try:
            (root / f"{cid}.json").unlink()
        except FileNotFoundError:
            pass
        shutil.rmtree(root / A0_SUBDIR / (EXPORT_PREFIX + cid), ignore_errors=True)
        folder = root / cid
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    tomb = root / TOMBSTONES
    tomb.mkdir(parents=True, exist_ok=True)
    (tomb / cid).write_text(str(int(time.time())) + "\n", encoding="utf-8")
    return {"ok": True, "id": cid}


def _untomb(root: Path, cid: str) -> None:
    try:
        (root / TOMBSTONES / cid).unlink()
    except OSError:
        pass


def _tomb_ts(root: Path, cid: str) -> int:
    try:
        return int((root / TOMBSTONES / cid).read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


# --- sync (B10) ---------------------------------------------------------------

def _units(root: Path) -> dict[str, tuple[int, Path]]:
    """Syncable unit -> (updated, path). StickLLM json files and A0 folders."""
    out: dict[str, tuple[int, Path]] = {}
    if not root.is_dir():
        return out
    for p in root.glob("*.json"):
        doc, _ = read_json(p)
        if doc is None:
            continue
        out[p.stem] = (_ts(doc.get("updated"), p.stat().st_mtime), p)
    a0 = root / A0_SUBDIR
    if a0.is_dir():
        for folder in a0.iterdir():
            f = folder / "chat.json"
            if f.is_file() and not folder.name.startswith(EXPORT_PREFIX):
                doc, _ = read_json(f)
                if doc is not None:
                    out["a0-" + folder.name] = (a0_updated(doc, f), folder)
    return out


def _copy_unit(src: Path, dst: Path) -> None:
    import shutil
    if src.is_dir():
        tmp = dst.with_name(dst.name + ".sync-tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp)
        shutil.rmtree(dst, ignore_errors=True)
        os.replace(tmp, dst)
    else:
        write_atomic(dst, src.read_text(encoding="utf-8"))
        os.utime(dst, (src.stat().st_atime, src.stat().st_mtime))


def sync_stores(a: Path, b: Path) -> dict:
    """Both ways, newest wins. A tombstone newer than the copy deletes it."""
    import shutil
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    ua, ub = _units(a), _units(b)
    copied = deleted = 0
    for key in sorted(set(ua) | set(ub)):
        ta = ua.get(key, (0, None))
        tb = ub.get(key, (0, None))
        tomb = max(_tomb_ts(a, key), _tomb_ts(b, key))
        newest = max(ta[0], tb[0])
        if tomb and tomb >= newest:
            for root, (_, p) in ((a, ta), (b, tb)):
                if p is not None:
                    if p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        p.unlink(missing_ok=True)
                        shutil.rmtree(root / A0_SUBDIR / (EXPORT_PREFIX + key), ignore_errors=True)
                    deleted += 1
                (root / TOMBSTONES).mkdir(exist_ok=True)
                (root / TOMBSTONES / key).write_text(f"{tomb}\n", encoding="utf-8")
            continue
        if ta[0] == tb[0]:
            continue
        src_root, src, dst_root = (a, ta[1], b) if ta[0] > tb[0] else (b, tb[1], a)
        if key.startswith("a0-"):
            dst = dst_root / A0_SUBDIR / key[3:]
            dst.parent.mkdir(parents=True, exist_ok=True)
        else:
            dst = dst_root / f"{key}.json"
        _copy_unit(src, dst)
        if not key.startswith("a0-"):
            doc, _ = read_json(dst)
            if doc:
                try:
                    export_to_a0(dst_root, doc)
                except OSError:
                    pass
        _untomb(dst_root, key)
        copied += 1
    return {"ok": True, "copied": copied, "deleted": deleted}


# --- Agent Zero bind mount -----------------------------------------------------

def get_session_mode(path: Path = SESSION_MODE_PATH) -> str:
    """UI header mode: ephemeral (default) or vault. Gates A0 chat persistence."""
    env = str(os.environ.get("STICKLLM_SESSION_MODE") or "").strip().lower()
    if env in SESSION_MODES:
        return env
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "ephemeral"
    if not isinstance(doc, dict):
        return "ephemeral"
    mode = str(doc.get("mode") or "ephemeral").strip().lower()
    return mode if mode in SESSION_MODES else "ephemeral"


def a0_chats_dir(vault_mnt: Path = VAULT_MNT, settings_mnt: Path = SETTINGS_MNT,
                 mounted: Callable[[Path], bool] = is_mount,
                 session_mode: str | None = None,
                 ephemeral_dir: Path = EPHEMERAL_A0_CHATS) -> Path | None:
    """Host path bind-mounted at /a0/usr/chats.

    Ephemeral → tmpfs under /run (never the vault). Vault mode → active store.
    """
    mode = (session_mode or get_session_mode()).strip().lower()
    if mode != "vault":
        return ephemeral_dir
    roots = store_roots(vault_mnt, settings_mnt, mounted)
    _, root, _ = active_root(load_pref(vault_mnt, settings_mnt), roots)
    if root is None:
        return None
    return root / A0_SUBDIR


def migrate_a0_state_chats(state_chats: Path, target: Path) -> int:
    """Move chats A0 kept in its private usr/chats (0.5.x) into the shared folder once."""
    import shutil
    if not state_chats.is_dir() or state_chats.is_symlink():
        return 0
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for folder in state_chats.iterdir():
        if folder.is_dir() and (folder / "chat.json").is_file():
            dst = target / folder.name
            if not dst.exists():
                shutil.move(str(folder), str(dst))
                moved += 1
    return moved


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "a0-chats-dir":
        mode = get_session_mode()
        d = a0_chats_dir(session_mode=mode)
        if d is None:
            return 3
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        # Only migrate private vault state chats into the encrypted store.
        # Never yank them into ephemeral RAM.
        if len(argv) > 2 and mode == "vault":
            moved = migrate_a0_state_chats(Path(argv[2]), d)
            if moved:
                print(f"moved {moved} Agent Zero chat(s) into the shared chat folder", file=sys.stderr)
        print(d)
        return 0
    if cmd == "sync":
        roots = store_roots()
        if not load_pref().get("sync") and "--force" not in argv:
            print("sync is off", file=sys.stderr)
            return 0
        if "ssd" in roots and "usb" in roots:
            print(json.dumps(sync_stores(roots["ssd"], roots["usb"])))
            return 0
        print("both vaults must be open to sync", file=sys.stderr)
        return 3
    print("usage: stickllm_chats.py {a0-chats-dir [old-state-chats]|sync [--force]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
