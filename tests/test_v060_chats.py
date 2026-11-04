"""0.6.0: shared chat store (B4/B9/B10, A2) and the Ephemeral toggle (B3)."""
import importlib.machinery
import importlib.util
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay/usr/local/lib/stickllm_chats.py"
GW = ROOT / "overlay/usr/local/bin/stickllm-gateway"
VAULT = ROOT / "overlay/usr/local/bin/stickllm-vault"


def _lib():
    loader = importlib.machinery.SourceFileLoader("stickllm_chats_t", str(LIB))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_save_is_atomic_and_exports_to_agent_zero(tmp_path):
    c = _lib()
    root = tmp_path / "chats"
    r = c.save_chat(root, "Taxes", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    assert r["ok"]
    cid = r["id"]
    assert json.loads((root / f"{cid}.json").read_text())["messages"][1]["content"] == "hello"
    a0 = json.loads((root / "agent-zero" / f"stickllm-{cid}" / "chat.json").read_text())
    assert a0["id"] == f"stickllm-{cid}" and a0["type"] == "user"
    hist = json.loads(a0["agents"][0]["history"])
    assert hist["current"]["messages"][0]["content"]["user_message"] == "hi"
    assert [l["type"] for l in a0["log"]["logs"]] == ["user", "response"]
    assert not list(root.glob(".*.tmp"))
    rows = c.list_chats(root)["chats"]
    assert [r["id"] for r in rows] == [cid], "export must not show twice"


def test_agent_zero_chats_listed_and_loaded(tmp_path):
    c = _lib()
    root = tmp_path / "chats"
    d = root / "agent-zero" / "abc123"
    d.mkdir(parents=True)
    (d / "chat.json").write_text(json.dumps({
        "id": "abc123", "name": "From A0", "type": "user", "last_message": "2026-11-01T10:00:00+00:00",
        "log": {"logs": [
            {"type": "user", "content": "q", "agentno": 0},
            {"type": "agent", "content": "thinking", "agentno": 0},
            {"type": "response", "content": "a", "agentno": 0},
        ]},
    }))
    rows = c.list_chats(root)["chats"]
    assert rows[0]["id"] == "a0-abc123" and rows[0]["source"] == "agent-zero"
    doc = c.load_chat(root, "a0-abc123")
    assert doc["messages"] == [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]


def test_a0_continued_chat_merges_back_newest_wins(tmp_path):
    c = _lib()
    root = tmp_path / "chats"
    cid = c.save_chat(root, "T", [{"role": "user", "content": "1"}])["id"]
    f = root / "agent-zero" / f"stickllm-{cid}" / "chat.json"
    doc = json.loads(f.read_text())
    doc["log"]["logs"].append({"type": "response", "content": "from a0", "agentno": 0})
    f.write_text(json.dumps(doc))
    later = time.time() + 60
    os.utime(f, (later, later))
    out = c.load_chat(root, cid)
    assert out["messages"][-1]["content"] == "from a0"


def test_bad_files_reported_not_silently_dropped(tmp_path):
    c = _lib()
    root = tmp_path / "chats"
    root.mkdir()
    (root / "broken.json").write_text("{nope")
    (root / "empty.json").write_text("")
    seen = []
    res = c.list_chats(root, seen.append)
    assert {s["file"] for s in res["skipped"]} == {"broken.json", "empty.json"}
    assert seen and "skipped 2" in seen[0]


def test_store_choice_and_fallback(tmp_path):
    c = _lib()
    vault, settings = tmp_path / "vault", tmp_path / "settings"
    vault.mkdir(); settings.mkdir()
    both = c.store_roots(vault, settings, lambda p: True)
    assert set(both) == {"ssd", "usb"}
    r = c.save_pref("usb", True, both, vault, settings)
    assert r["ok"]
    pref = c.load_pref(vault, settings)
    assert pref == {"store": "usb", "sync": True}
    only_ssd = c.store_roots(vault, settings, lambda p: p == vault)
    store, root, fell = c.active_root(pref, only_ssd)
    assert store == "ssd" and fell
    assert not c.save_pref("usb", False, only_ssd, vault, settings)["ok"]


def test_sync_both_ways_newest_wins_and_deletes(tmp_path):
    c = _lib()
    a, b = tmp_path / "a", tmp_path / "b"
    ida = c.save_chat(a, "only a", [{"role": "user", "content": "x"}])["id"]
    idb = c.save_chat(b, "only b", [{"role": "user", "content": "y"}])["id"]
    r = c.sync_stores(a, b)
    assert r["copied"] == 2
    assert (a / f"{idb}.json").is_file() and (b / f"{ida}.json").is_file()
    # newer edit in b wins
    doc = json.loads((b / f"{ida}.json").read_text())
    doc["title"] = "edited"; doc["updated"] = int(time.time()) + 100
    (b / f"{ida}.json").write_text(json.dumps(doc))
    c.sync_stores(a, b)
    assert json.loads((a / f"{ida}.json").read_text())["title"] == "edited"
    # delete propagates
    time.sleep(0.01)
    c.delete_chat(a, idb)
    (a / ".deleted" / idb).write_text(str(int(time.time()) + 200))
    c.sync_stores(a, b)
    assert not (b / f"{idb}.json").exists()


def test_migrate_private_a0_chats(tmp_path):
    c = _lib()
    old = tmp_path / "state" / "chats" / "ctx1"
    old.mkdir(parents=True)
    (old / "chat.json").write_text("{}")
    assert c.migrate_a0_state_chats(tmp_path / "state" / "chats", tmp_path / "shared") == 1
    assert (tmp_path / "shared" / "ctx1" / "chat.json").is_file()


def test_ephemeral_toggle_never_locks_or_stops():
    gw = GW.read_text()
    body = gw[gw.index("def set_session_mode("):gw.index("VAULT_MNT = Path(")]
    assert '"stickllm-vault", "lock"' not in body and "stickllm-vault\", \"lock\"" not in body
    assert "systemctl\", \"stop\"" not in body
    assert "ensure-addons" in body
    js = (ROOT / "ui/app.js").read_text()
    sm = js[js.index("async function setSessionMode(m)"):]
    sm = sm[: sm.index("\n}\n")]
    assert "clearOnLock()" not in sm


def test_lock_keeps_gateway_view_when_umount_fails():
    v = VAULT.read_text()
    body = v[v.index("cmd_lock()"):]
    body = body[: body.index("\n}\n")]
    assert body.index("umount") < body.index("drop_gateway_vault_view")
    assert "ui-refresh)" in v and "ensure-addons)" in v


def test_vault_boot_txt_follows_state():
    v = VAULT.read_text()
    js = v[v.index("json_state()"):]
    js = js[: js.index("\n}\n")]
    assert "vault-boot.txt" in js and "deferred-to-ui" in js
