"""0.6.4: thin same-origin /agent-zero/ embed — HTML/CSS prefix, JS passthrough."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay/usr/local/bin/stickllm-gateway"


def _load_gateway():
    loader = importlib.machinery.SourceFileLoader("stickllm_gateway_embed", str(GATEWAY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_gateway_has_thin_embed_markers():
    text = GATEWAY.read_text(encoding="utf-8")
    assert 'AGENT_EMBED_PREFIX = "/agent-zero"' in text
    assert "def rewrite_agent_embed_payload" in text
    assert "def _agent_embed_proxy" in text
    assert "_prefix_splash_boot_paths" in text
    assert "_prefix_html_style" not in text or "_prefix_css_urls" in text
    # Must not revive the broad JS body rewriter that corrupted /g flags.
    assert "agent-zero/api/agent-zero" not in text


def test_ui_chat_uses_same_origin_embed():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert 'return "/agent-zero/"' in app
    assert "opts.embed === false" in app
    assert "agentUrlIsLoopback" in app
    assert "detectLocalHost()" in app
    assert "http://127.0.0.1:5099/" not in app or "never open raw" in app.lower() or "Never open raw" in app
    # Kiosk must not be sent to raw :5099 (Chromium connection-refused page).
    assert "can't connect to 127.0.0.1" in app
    assert "deskAppUrl(id, opts)" in app or "deskAppUrl(id,opts)" in app
    assert "urlFor(id, opts)" in desk or "urlFor(id,opts)" in desk
    assert 'embed: false' in desk
    assert 'href="/agent-zero/"' in html
    assert "https://127.0.0.1:5443/" not in html
    # No UI default to loopback Agent ports.
    assert "http://127.0.0.1:5099/" not in html


def test_rewrite_html_css_not_js():
    mod = _load_gateway()
    html = b"""<!doctype html><head>
<link rel="icon" href="/public/favicon.svg">
<script type="module" src="/js/icons.js"></script>
<script>var fence = /```/g; const APP_DOCUMENT_PATH = "/ui/index";</script>
<style>@font-face{src:url(/vendor/google/google-icons.woff2)}</style>
</head>"""
    out = mod.rewrite_agent_embed_payload(html, "text/html; charset=utf-8").decode()
    assert 'href="/agent-zero/public/favicon.svg">' in out
    assert 'favicon.svg""' not in out
    assert 'src="/agent-zero/js/icons.js"' in out
    assert "var fence = /```/g;" in out
    assert 'APP_DOCUMENT_PATH = "/agent-zero/ui/index"' in out
    assert "url(/agent-zero/vendor/google/google-icons.woff2)" in out
    assert "importmap" in out
    assert "data-stickllm-a0-embed" in out

    splash = b'<head><link rel="icon" href="/public/favicon.svg"><script>const APP_DOCUMENT_PATH = "/ui/index"; fetch("/ui/asset-bundle"</script></head>'
    splash_out = mod.rewrite_agent_embed_payload(splash, "text/html").decode()
    assert 'APP_DOCUMENT_PATH = "/agent-zero/ui/index"' in splash_out
    assert 'fetch("/agent-zero/ui/asset-bundle"' in splash_out
    assert "importmap" not in splash_out

    css = b"body{background:url(/public/a.svg)} i{background:url(./rel.woff2)}"
    css_out = mod.rewrite_agent_embed_payload(css, "text/css").decode()
    assert "url(/agent-zero/public/a.svg)" in css_out
    assert "url(./rel.woff2)" in css_out

    js = b'import "/js/sleep.js";\nconst re = /```/g;\n'
    assert mod.rewrite_agent_embed_payload(js, "text/javascript") == js
    assert mod.rewrite_agent_embed_payload(js, "application/javascript") == js


def test_rewrite_idempotent_on_already_injected_html():
    mod = _load_gateway()
    first = mod.rewrite_agent_embed_payload(
        b'<head><script type="module" src="/js/a.js"></script></head>',
        "text/html",
    )
    second = mod.rewrite_agent_embed_payload(first, "text/html")
    assert second == first
    assert first.decode().count("data-stickllm-a0-embed") >= 1
    assert first.decode().count("/agent-zero/agent-zero") == 0


def test_embed_shim_warns_insecure_microphone():
    text = GATEWAY.read_text(encoding="utf-8")
    assert "isSecureContext" in text
    assert "stickllm-mic-https" not in text
    assert "#7a1f1f" not in text
    assert "Microphone needs HTTPS" in text
    assert "_redirect_remote_http_to_https" in text
    assert 'microphone=*' in text
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "function secureMicMessage()" in app
    assert "function httpsStickUrl()" in app
    assert "trust the stick certificate" in app
    assert "stickllm.micHttpsHint" in app
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    assert 'allow", "microphone' in desk or "allow\",\"microphone" in desk or 'allow", "microphone;' in desk
