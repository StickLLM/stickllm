"""0.5.2 fixes 6/7: Agent Zero install_app (user confirms on screen) and the
docs tools (create_spreadsheet / create_document / open_document)."""
import ast
import importlib.machinery
import importlib.util
import io
import json
import os
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay" / "usr" / "local" / "lib"
GW = (ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway").read_text(encoding="utf-8")
APP = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


def _load(path: Path, name: str, env: dict | None = None):
    if env:
        os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _agent():
    return _load(LIB / "stickllm_agent.py", "stickllm_agent_052t")


def _docs(tmp_path):
    v = tmp_path / "vault"
    s = tmp_path / "settings"
    for p in (v, s, tmp_path / "run"):
        p.mkdir(exist_ok=True)
    (tmp_path / "mounts").write_text(f"/dev/mapper/v {v} ext4 rw 0 0\n/dev/mapper/s {s} ext4 rw 0 0\n", encoding="utf-8")
    return _load(LIB / "stickllm_docs.py", "stickllm_docs_052t", {
        "STICKLLM_VAULT_MNT": str(v), "STICKLLM_SETTINGS_MNT": str(s),
        "STICKLLM_RUN": str(tmp_path / "run"), "STICKLLM_MOUNTS_FILE": str(tmp_path / "mounts"),
    })


def test_ids_and_aliases():
    a = _agent()
    for cid in ("docs", "radicale", "vikunja", "actual", "trilium", "node-red"):
        assert a.catalog_app_id_ok(cid) and a.open_target_ok(cid)
    assert a.normalize_app_id("OnlyOffice") == "docs"
    assert a.normalize_app_id("nodered") == "node-red"
    assert a.normalize_app_id("actual-budget") == "actual"
    for bad in ("../docs", "http://x/", "node red", "", None, 3, "agent-zero"):
        assert not a.open_target_ok(a.normalize_app_id(bad))
    assert a.open_app_id_ok("minesweeper") and not a.catalog_app_id_ok("minesweeper")
    assert a.catalog_app_path("docs") == "/apps/docs/"


def test_tool_sources_compile_and_have_loop_guard():
    a = _agent()
    for fn in (a.install_app_tool_source, a.create_spreadsheet_tool_source,
               a.create_document_tool_source, a.open_document_tool_source):
        src = fn()
        ast.parse(src)
        assert "_MAX_TRIES = 2" in src and "172.30.0.1:8082" in src
        assert "Bearer " in src and "/stickllm-open-app.token" in src
    assert '"/install"' in a.install_app_tool_source() or "8082/install" in a.install_app_tool_source()
    assert "8082/docs" in a.create_spreadsheet_tool_source()


def test_prompts_rules():
    a = _agent()
    p = a.docs_tools_prompt()
    assert "[[1],[2],[3],[4],[5],[6],[7],[8],[9],[10]]" in p
    assert "libreoffice" in p and "Never start GUI programs" in p
    assert "fails twice" in p
    i = a.install_app_tool_prompt()
    assert "click" in i.lower() and "do not call install_app again" in i
    assert "install_app" in a.open_app_tool_prompt()


def test_plugin_writes_new_tools(tmp_path, monkeypatch):
    a = _agent()
    import inspect
    src = inspect.getsource(a)
    for name in ("install_app.py", "create_spreadsheet.py", "create_document.py", "open_document.py",
                 "agent.system.tool.install_app.md", "agent.system.tool.docs.md"):
        assert name in src


def _bridge(a, tmp_path, relay=None, notify=None):
    token = "tok-0123456789abcdef0123456789"
    tf = tmp_path / "t.token"
    tf.write_text(token, encoding="utf-8")
    apps = tmp_path / "apps"
    apps.mkdir(exist_ok=True)
    srv = a.open_app_server("127.0.0.1", 0, root=apps, token_file=tf, relay=relay, notify=notify)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def post(path, body, auth=True):
        h = {"Content-Type": "application/json"}
        if auth:
            h["Authorization"] = "Bearer " + token
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    return srv, post


def test_bridge_install_and_docs_relay(tmp_path):
    a = _agent()
    seen = []

    def relay(path, app_id, body):
        seen.append((path, body))
        return {"ok": True, "status": "awaiting_user"}
    srv, post = _bridge(a, tmp_path, relay=relay)
    try:
        assert post("/install", {"id": "docs"}, auth=False)[0] == 401
        assert post("/install", {"id": "evil"})[0] == 400
        assert post("/install", {"id": "../x"})[0] == 400
        code, body = post("/install", {"id": "ONLYOFFICE"})
        assert code == 200 and seen[-1] == ("/install", {"id": "docs"})
        assert post("/docs", {"op": "rm"})[0] == 400
        rows = [[i] for i in range(1, 11)]
        code, _ = post("/docs", {"op": "create", "kind": "xlsx", "name": "N", "rows": rows, "junk": 1})
        assert code == 200
        assert seen[-1] == ("/docs", {"op": "create", "kind": "xlsx", "name": "N", "rows": rows})
    finally:
        srv.shutdown()


def test_bridge_catalog_open_and_not_installed(tmp_path):
    a = _agent()
    opened = []

    def notify(app_id):
        if app_id == "trilium":
            raise a.AppNotInstalled("Trilium Notes is not installed. Call install_app")
        opened.append(app_id)
    srv, post = _bridge(a, tmp_path, notify=notify)
    try:
        code, body = post("/open", {"id": "docs"})
        assert code == 200 and body["path"] == "/apps/docs/" and opened == ["docs"]
        code, body = post("/open", {"id": "node-red"})
        assert code == 200 and opened[-1] == "node-red"
        code, body = post("/open", {"id": "trilium"})
        assert code == 409 and body["error"] == "not_installed" and "install_app" in body["message"]
    finally:
        srv.shutdown()


def test_xlsx_numbers_1_to_10_column_a(tmp_path):
    d = _docs(tmp_path)
    rel = d.agent_create("xlsx", "Numbers", rows=[[i] for i in range(1, 11)])
    assert rel == "Numbers.xlsx"
    assert d.agent_create("xlsx", "Numbers", rows=[[1]]) == "Numbers (2).xlsx"
    data = (tmp_path / "vault" / "Documents" / rel).read_bytes()
    sheet = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    for i in range(1, 11):
        assert f'<c r="A{i}"><v>{i}</v></c>' in sheet
    try:
        import openpyxl
    except ImportError:
        return
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    assert [c.value for c in ws["A"]] == list(range(1, 11))


def test_xlsx_escapes_and_docx(tmp_path):
    d = _docs(tmp_path)
    data = d.build_xlsx([["<b>&", "=SUM(1,2)", None, True, 2.5]])
    sheet = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    assert "&lt;b&gt;&amp;" in sheet and "<f>SUM(1,2)</f>" in sheet and 'r="E1"' in sheet
    rel = d.agent_create("docx", "../../etc/x", text="a\nb", title="T")
    assert "/" not in rel and rel.endswith(".docx")
    try:
        d.build_xlsx("nope")
        raise AssertionError
    except d.DocsError:
        pass
    (tmp_path / "mounts").write_text("", encoding="utf-8")
    try:
        d.agent_create("xlsx", "x", rows=[[1]])
        raise AssertionError
    except d.DocsError as exc:
        assert exc.status == 423


def test_gateway_wiring():
    assert '"/api/ui/install-request"' in GW and '"/api/ui/docs-agent"' in GW
    assert "def _agent_install_request" in GW and "def _agent_docs" in GW
    assert 'kind == "install_confirm"' in GW and 'payload["doc"] = event["doc"]' in GW
    assert '"error": "not_installed"' in GW
    # The agent endpoints never install anything themselves.
    body = GW.split("def _agent_install_request", 1)[1].split("def _agent_docs", 1)[0]
    assert "_apps_mutate" not in body and "_addon_mutate" not in body and "_docs_mutate" not in body
    assert body.count("_open_app_control_ok") == 0
    assert GW.count("self._open_app_control_ok()") >= 4


def test_ui_confirm_dialog_and_doc_open():
    assert 'id="agentInstall"' in HTML and 'id="aiYes"' in HTML
    assert 'addEventListener("install_confirm"' in APP
    assert 'fetch("/api/apps/install"' in APP
    assert "/^[a-z][a-z-]{0,23}$/" in APP
    assert 'docsOpenHref' in APP and '"/apps/docs/?open=" + encodeURIComponent' in APP


def test_tool_loop_guard_stops_after_two_failures(tmp_path, monkeypatch):
    import asyncio
    import sys
    import types
    a = _agent()
    helpers = types.ModuleType("helpers")
    tool = types.ModuleType("helpers.tool")

    class Response:
        def __init__(self, message, break_loop):
            self.message = message

    class Tool:
        def __init__(self, args):
            self.args = args
    tool.Response, tool.Tool = Response, Tool
    monkeypatch.setitem(sys.modules, "helpers", helpers)
    monkeypatch.setitem(sys.modules, "helpers.tool", tool)
    ns: dict = {}
    exec(compile(a.create_spreadsheet_tool_source(), "create_spreadsheet.py", "exec"), ns)
    tf = tmp_path / "tok"
    tf.write_text("tok", encoding="utf-8")
    ns["_TOKEN_FILE"] = tf
    calls = []

    def boom(req, timeout=0):
        calls.append(json.loads(req.data))
        raise urllib.error.HTTPError(req.full_url, 409, "x", {}, io.BytesIO(b'{"ok":false,"error":"vault_locked"}'))
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    t = ns["CreateSpreadsheet"]({"name": "N", "rows": [[1]]})
    msgs = [asyncio.run(t.execute()).message for _ in range(3)]
    assert len(calls) == 2
    assert calls[0] == {"op": "create", "kind": "xlsx", "name": "N", "rows": [[1]]}
    assert "one retry left" in msgs[0] and "do not retry" in msgs[1]
    assert "already failed twice" in msgs[2]
