"""0.6.0 (A6): Agent Zero's install_app uses StickLLM's own add-on installer."""
import importlib.machinery
import importlib.util
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay/usr/local/bin"
LIB = ROOT / "overlay/usr/local/lib"


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class _Addons:
    APPS = {"node-red": {}, "paisa": {}, "comfyui": {}}
    VAULT_LOCKED_MESSAGE = "Unlock your vault first."

    def __init__(self, vault=True):
        self.vault = vault
        self.status = {}

    def app(self, app_id):
        return {"name": {"node-red": "Node-RED", "paisa": "Paisa"}.get(app_id, app_id)}

    def vault_open(self):
        return self.vault

    def is_installed(self, app_id):
        return False

    def write_status(self, app_id, state, **_):
        self.status[app_id] = state

    def status_document(self, app_id):
        return {"installed": False, "running": False, "state": self.status.get(app_id, "not_installed")}


def _setup(monkeypatch, status="verified", vault=True, target=("kiosk", "kiosk")):
    gw = _load(BIN / "stickllm-gateway", "gw_v060_a6")
    addons = _Addons(vault)
    runs, events, confirms = [], [], []
    monkeypatch.setattr(gw, "addons_lib", lambda: addons)
    monkeypatch.setattr(gw, "app_verification", lambda app_id, check_upstream=False: {"status": status})
    monkeypatch.setattr(gw, "ui_target", lambda now=None: target)
    monkeypatch.setattr(gw.UI_OPEN, "ui_conn_for", lambda key: 7)
    monkeypatch.setattr(gw.UI_OPEN, "publish_install_started",
                        lambda app_id, name, target="", conn=None: events.append((app_id, name, target, conn)))
    monkeypatch.setattr(gw.UI_OPEN, "publish_install",
                        lambda app_id, name, target="", conn=None: confirms.append(app_id))

    def run(cmd, **_):
        runs.append(cmd)
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(gw.subprocess, "run", run)
    monkeypatch.setattr(gw.subprocess, "Popen", lambda *a, **k: runs.append(a[0]))
    h = object.__new__(gw.Handler)
    replies = []
    h._json = lambda code, doc: replies.append((code, doc))
    return gw, h, addons, runs, events, confirms, replies


def test_verified_addon_installs_through_the_apps_page_unit(monkeypatch):
    gw, h, addons, runs, events, confirms, replies = _setup(monkeypatch)
    h._agent_install_request({"id": "node-red"})
    assert runs == [["systemctl", "start", "--no-block", "stickllm-addon-install@node-red.service"]]
    assert addons.status["node-red"] == "installing"
    assert events == [("node-red", "Node-RED", "kiosk", 7)] and confirms == []
    code, doc = replies[-1]
    assert code == 200 and doc["status"] == "installing" and "desktop" in doc["message"]
    assert "never install it yourself" in doc["message"]
    # The second ask while it installs starts nothing new.
    h._agent_install_request({"id": "node-red"})
    assert len(runs) == 1 and replies[-1][1]["status"] == "installing"


def test_unverified_or_changed_still_asks_on_screen(monkeypatch):
    for status in ("changed", "unverified", None):
        gw, h, addons, runs, events, confirms, replies = _setup(monkeypatch, status=status)
        h._agent_install_request({"id": "paisa"})
        assert runs == [] and events == [] and confirms == ["paisa"]
        assert replies[-1][1]["status"] == "awaiting_user"


def test_docs_blocked_and_bad_ids_never_auto_install(monkeypatch):
    gw, h, addons, runs, events, confirms, replies = _setup(monkeypatch)
    monkeypatch.setattr(h, "_agent_catalog_status",
                        lambda app_id: {"id": app_id, "name": app_id, "installed": False, "running": False, "state": ""},
                        raising=False)
    h._agent_install_request({"id": "docs"})
    assert runs == [] and confirms == ["docs"]
    h._agent_install_request({"id": "comfyui"})  # GPU-heavy: on-screen confirm
    assert runs == [] and events == [] and confirms[-1] == "comfyui"
    monkeypatch.setattr(gw, "app_blocked", lambda app_id: app_id == "paisa")
    h._agent_install_request({"id": "paisa"})
    assert replies[-1][0] == 403 and runs == []
    h._agent_install_request({"id": "../../bin/sh"})
    assert replies[-1][0] == 400 and runs == []


def test_locked_vault_is_reported_not_worked_around(monkeypatch):
    gw, h, addons, runs, events, confirms, replies = _setup(monkeypatch, vault=False)
    h._agent_install_request({"id": "node-red"})
    code, doc = replies[-1]
    assert code == 423 and not doc["ok"] and "do not install it another way" in doc["message"]
    assert runs == [] and events == []


def test_apps_page_and_agent_share_one_installer():
    gw = (BIN / "stickllm-gateway").read_text()
    mutate = gw.split("def _addon_mutate", 1)[1].split("\n    def ", 1)[0]
    assert 'addon_start(action, app_id)' in mutate
    direct = gw.split("def _agent_direct_install", 1)[1].split("\n    def ", 1)[0]
    assert 'addon_start("install", app_id)' in direct and 'ver.get("status") != "verified"' in direct
    assert "app_blocked(app_id)" in direct and "docker" not in direct.lower()
    assert 'kind in ("install_confirm", "install_started")' in gw


def test_ui_follows_the_install_and_opens_the_window():
    app = (ROOT / "ui/app.js").read_text()
    assert 'addEventListener("install_started"' in app
    body = app.split("async function followAgentInstall", 1)[1].split("\nasync function ", 1)[0]
    assert "progressToast(" in body and "refreshApps()" in body and "openStickApp(id" in body


def test_prompt_steers_installs_to_the_desktop():
    agent = _load(LIB / "stickllm_agent.py", "agent_v060_a6")
    p = agent.install_app_tool_prompt()
    for ids in ("node-red", "paisa"):
        assert ids in p
    assert "not in your container" in p and "Never install these apps yourself" in p
    assert "plugins" in p and "still install inside Agent Zero" in p
    assert "hash pinned" in p and "never try to get around the warning" in p
