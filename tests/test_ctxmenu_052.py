"""0.5.2: StickLLM's own right-click menu (native one is invisible on the kiosk)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_context_menu_present_and_themed():
    js = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    css = (ROOT / "ui/style.css").read_text(encoding="utf-8")
    assert 'document.addEventListener("contextmenu"' in js
    assert "e.shiftKey" in js  # Shift+right-click keeps the native menu
    for act in ("cut", "copy", "paste", "selectall", "openlink", "copylink", "reload"):
        assert f'"{act}"' in js
    block = css[css.index(".ctxMenu{"):]
    assert "background:var(--panel)" in block and "color:var(--ink)" in block
    assert ".ctxMenu button{" in block and "color:var(--ink)" in block[block.index(".ctxMenu button{"):]


def test_kiosk_clipboard_policy():
    pol = json.loads((ROOT / "overlay/etc/chromium/policies/managed/stickllm-tabs.json").read_text())
    assert "http://127.0.0.1" in pol["ClipboardAllowedForUrls"]
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text()
    assert '"ClipboardAllowedForUrls":["http://127.0.0.1","http://localhost"]' in kiosk


def test_kiosk_media_capture_auto_grant_policy():
    """Stick-owned Chromium auto-grants mic/camera; remotes still prompt."""
    pol = json.loads(
        (ROOT / "overlay/etc/chromium/policies/managed/stickllm-media.json").read_text(
            encoding="utf-8"
        )
    )
    for key in ("AudioCaptureAllowedUrls", "VideoCaptureAllowedUrls"):
        assert "http://127.0.0.1:*" in pol[key]
        assert "http://localhost:*" in pol[key]
        assert "https://127.0.0.1:*" in pol[key]
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert "stickllm-media.json" in kiosk
    assert "AudioCaptureAllowedUrls" in kiosk
    assert "stick_media_capture_urls_json" in kiosk
    # Prefer enterprise allow-list over fake-ui (would grant every site).
    for line in kiosk.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "--use-fake-ui-for-media-stream" not in line
    hotfix = (ROOT / "overlay/usr/local/bin/stickllm-hotfix").read_text(encoding="utf-8")
    assert "etc/chromium/policies/managed" in hotfix
    assert "stickllm-*.json" in hotfix
