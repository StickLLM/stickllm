"""StickLLM: block outbound / metadata / unshare in Agent Zero tool calls."""
from __future__ import annotations

import importlib.util
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from helpers.errors import RepairableException
from helpers.extension import Extension

_SCAN = Path(__file__).resolve().parents[3] / "helpers" / "egress_scan.py"
_TOKEN = Path("/stickllm-open-app.token")
_EVENT_URL = "http://172.30.0.1:8082/egress-event"
_LOG = Path("/a0/usr/logs/egress-blocks.jsonl")


def _load_scan():
    spec = importlib.util.spec_from_file_location("stickllm_egress_scan", _SCAN)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _web_fetch() -> bool:
    for p in (
        Path("/a0/usr/egress.json"),
        Path("/stickllm-egress.json"),
    ):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and "web_fetch" in doc:
                return bool(doc["web_fetch"])
        except (OSError, ValueError, TypeError):
            continue
    return True


def _report(tool_name: str, findings: list) -> None:
    payload = {
        "tool": tool_name,
        "findings": findings[:8],
        "ts": int(time.time()),
    }
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    try:
        token = _TOKEN.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not token:
        return
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _EVENT_URL,
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception:
        return


class StickllmEgressGuard(Extension):
    async def execute(self, tool_name: str = "", tool_args=None, **kwargs):
        if not self.agent:
            return
        scan = _load_scan()
        findings = scan.scan_tool_call(
            tool_name, tool_args or {}, web_fetch=_web_fetch()
        )
        if not findings:
            return
        detail = scan.describe(findings)
        _report(tool_name, findings)
        try:
            self.agent.context.log.log(
                type="warning",
                heading="StickLLM blocked an outbound action",
                content=(
                    "The agent tried something StickLLM does not allow "
                    f"({detail}). Metadata, Alibaba Cloud storage, uploads, "
                    "and user namespaces are blocked. Tell the user; do not "
                    "retry with a workaround."
                ),
            )
        except Exception:
            pass
        raise RepairableException(
            "Blocked by StickLLM egress guard: "
            + detail
            + ". Do not retry with a different tool or encoding."
        )
