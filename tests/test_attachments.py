"""Attachment conversion: text for any model, images stay on the vision path."""
from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import unittest
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-convert"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_convert():
    loader = importlib.machinery.SourceFileLoader("stickllm_convert", str(SCRIPT))
    spec = importlib.util.spec_from_loader("stickllm_convert", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


CV = load_convert()


def _pdf_objects(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    xref = [0]
    for i, body in enumerate(objects, 1):
        xref.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in xref[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()
    return bytes(out)


def _pdf(text: str | None) -> bytes:
    stream = b""
    if text:
        stream = f"BT /F1 12 Tf 50 250 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    return _pdf_objects(objects)


def _pdf_with_binary(text: str) -> bytes:
    """A short text page plus a large image stream full of parentheses."""
    content = (
        f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET\n"
        "(" + ("Z" * 8000) + ")\n"
    ).encode()
    packed = zlib.compress(content)
    blob = b"(" + (b"Q" * 180000) + b")BINBLOB"
    return _pdf_objects([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /XObject << /Im0 5 0 R >> /Font << /F1 6 0 R >> >> >>",
        b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(packed) + packed + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length %d >>\nstream\n" % len(blob) + blob + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])


def _docx(text: str, macro: bool = False) -> bytes:
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
        if macro:
            zf.writestr("word/vbaProject.bin", b"\x00MACRO-BYTES")
    return buf.getvalue()


def _pptx(text: str) -> bytes:
    xml = (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f"<p:spTree><a:t>{text}</a:t></p:spTree></p:sld>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", xml)
    return buf.getvalue()


def _xlsx(headers: list[str], rows: list[list[str]]) -> bytes:
    def col(i: int) -> str:
        return chr(65 + i)

    lines = []
    for r, row in enumerate([headers, *rows], 1):
        cells = []
        for c, val in enumerate(row):
            cells.append(f'<c r="{col(c)}{r}" t="inlineStr"><is><t>{val}</t></is></c>')
        lines.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(lines)}</sheetData></worksheet>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _write_fixtures() -> dict[str, bytes]:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    rows = [[f"r{i}", str(i)] for i in range(1, 1001)]
    files = {
        "text.pdf": _pdf("Hello PDF"),
        "scanned.pdf": _pdf(None),
        "broken.pdf": b"%PDF-1.7\n<<broken>>",
        "note.docx": _docx("Hello Word"),
        "macro.docm": _docx("Hello Macro", macro=True),
        "slides.pptx": _pptx("Hello Slide"),
        "rows-1000.xlsx": _xlsx(["name", "n"], rows),
        "tiny.csv": b"name,n\nalpha,1\nbeta,2\n",
        "sample.json": b'{"title":"Stick","n":3}\n',
        "bundle.zip": b"",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "SECRET-BODY")
    files["bundle.zip"] = buf.getvalue()
    for name, data in files.items():
        (FIXTURES / name).write_bytes(data)
    return files


FILES = _write_fixtures()


def test_text_pdf_and_scan_and_broken():
    ok = CV.convert_bytes(FILES["text.pdf"], "text.pdf", vision=False)
    assert ok["ok"] and ok["type"] == "pdf"
    assert "Hello PDF" in ok["plain"]
    assert ok["text"].startswith("<attachment ")
    assert 'type="pdf"' in ok["text"]
    assert ok["images"] == []
    seen = CV.convert_bytes(FILES["text.pdf"], "text.pdf", vision=True)
    assert seen["ok"] and seen["images"] == []
    scan = CV.convert_bytes(FILES["scanned.pdf"], "scanned.pdf", vision=False)
    assert scan["ok"]
    assert "scan" in scan["plain"].lower() or "Tesseract" in scan["plain"] or "vision" in scan["plain"].lower()
    vision = CV.convert_bytes(FILES["scanned.pdf"], "scanned.pdf", vision=True)
    assert vision["ok"]
    broken = CV.convert_bytes(FILES["broken.pdf"], "broken.pdf", vision=False)
    assert broken["ok"] is False
    assert "PDF" in broken["error"]


def test_docx_pptx_macro_not_executed():
    doc = CV.convert_bytes(FILES["note.docx"], "note.docx")
    assert doc["ok"] and "Hello Word" in doc["plain"]
    slide = CV.convert_bytes(FILES["slides.pptx"], "slides.pptx")
    assert slide["ok"] and "Hello Slide" in slide["plain"]
    macro = CV.convert_bytes(FILES["macro.docm"], "macro.docm")
    assert macro["ok"] and macro["macros_stripped"]
    assert "Hello Macro" in macro["plain"]
    assert "MACRO-BYTES" not in macro["plain"]
    assert "not run" in macro["plain"].lower()


def test_xlsx_truncates_and_csv_json():
    sheet = CV.convert_bytes(FILES["rows-1000.xlsx"], "rows-1000.xlsx")
    assert sheet["ok"] and sheet["truncated"]
    assert "1000" in sheet["plain"]
    assert "first 50" in sheet["plain"].lower()
    assert 'truncated="true"' in sheet["text"]
    assert sheet["plain"].count("\n| r") <= 50
    csv_doc = CV.convert_bytes(FILES["tiny.csv"], "tiny.csv")
    assert csv_doc["ok"] and "alpha" in csv_doc["plain"] and csv_doc["truncated"] is False
    js = CV.convert_bytes(FILES["sample.json"], "sample.json")
    assert js["ok"] and "```json" in js["plain"]
    assert "Stick" in js["plain"]


_ODS_MIME = "application/vnd.oasis.opendocument.spreadsheet"
_ODT_MIME = "application/vnd.oasis.opendocument.text"
_ODP_MIME = "application/vnd.oasis.opendocument.presentation"
_MACRO_BODY = "PLANTED-MACRO-BODY"


def _odf_package(mime: str, content: str, extras: list[tuple[str, bytes]] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, mime.encode("ascii"))
        zf.writestr("content.xml", content.encode("utf-8"))
        for name, blob in extras or []:
            zf.writestr(name, blob)
    return buf.getvalue()


def _ods_xml(headers: list[str], rows: list[list[str]], *, macro: bool = False) -> str:
    def cell(val: str) -> str:
        safe = str(val).replace("&", "&amp;").replace("<", "&lt;")
        return (
            '<table:table-cell office:value-type="string">'
            f"<text:p>{safe}</text:p></table:table-cell>"
        )

    def row(vals: list[str]) -> str:
        return "<table:table-row>" + "".join(cell(v) for v in vals) + "</table:table-row>"

    script = f"<text:script>{_MACRO_BODY}</text:script>" if macro else ""
    pad = (
        '<table:table-row table:number-rows-repeated="100000">'
        '<table:table-cell table:number-columns-repeated="20"/>'
        "</table:table-row>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content'
        ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:spreadsheet>"
        '<table:table table:name="Budget">'
        + row(headers)
        + "".join(row(r) for r in rows)
        + pad
        + "</table:table>"
        + script
        + "</office:spreadsheet></office:body></office:document-content>"
    )


def test_opendocument_formats():
    macros = [
        ("Scripts/python/evil.py", _MACRO_BODY.encode()),
        ("Basic/Standard/script-lb.xml", _MACRO_BODY.encode()),
        ("Scripts/javascript/evil.js", _MACRO_BODY.encode()),
    ]
    small = _odf_package(
        _ODS_MIME,
        _ods_xml(["Name", "Qty"], [["Apple", "2"], ["Pear", "3"]], macro=True),
        macros,
    )
    sheet = CV.convert_bytes(small, "budget.bin")
    assert sheet["ok"], sheet
    assert sheet["type"] == "ods"
    assert sheet["truncated"] is False
    assert 'type="ods"' in sheet["text"]
    assert "Apple" in sheet["plain"] and "Pear" in sheet["plain"] and "Qty" in sheet["plain"]
    assert _MACRO_BODY not in sheet["plain"]
    assert "evil.py" not in sheet["plain"]
    assert sheet["macros_stripped"]
    assert "not run" in sheet["plain"].lower()
    rows = [[f"r{i}", str(i)] for i in range(1, 1001)]
    big = CV.convert_bytes(_odf_package(_ODS_MIME, _ods_xml(["name", "n"], rows)), "rows.dat")
    assert big["ok"] and big["type"] == "ods" and big["truncated"], big
    assert "Rows: 1000" in big["plain"]
    assert "first 50" in big["plain"].lower()
    assert 'truncated="true"' in big["text"]
    assert big["plain"].count("\n| r") <= 50
    assert "r1" in big["plain"] and "r1000" not in big["plain"]
    odt_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content'
        ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:text>"
        '<text:h text:outline-level="1">Garden Notes</text:h>'
        "<text:p>Tomatoes need water</text:p>"
        f"<text:script>{_MACRO_BODY}</text:script>"
        "</office:text></office:body></office:document-content>"
    )
    doc = CV.convert_bytes(_odf_package(_ODT_MIME, odt_xml, macros), "notes.dat")
    assert doc["ok"] and doc["type"] == "odt", doc
    assert 'type="odt"' in doc["text"]
    assert "Garden Notes" in doc["plain"] and "Tomatoes need water" in doc["plain"]
    assert doc["plain"].startswith("# ") or "\n# " in "\n" + doc["plain"]
    assert _MACRO_BODY not in doc["plain"]
    assert doc["macros_stripped"]
    odp_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content'
        ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:presentation>"
        '<draw:page draw:name="Intro"><draw:frame><draw:text-box>'
        "<text:p>Welcome aboard</text:p></draw:text-box></draw:frame></draw:page>"
        '<draw:page draw:name="End"><text:p>Thanks everyone</text:p></draw:page>'
        "</office:presentation></office:body></office:document-content>"
    )
    slides = CV.convert_bytes(_odf_package(_ODP_MIME, odp_xml), "deck.bin")
    assert slides["ok"] and slides["type"] == "odp", slides
    assert 'type="odp"' in slides["text"]
    assert "## Intro" in slides["plain"] and "## End" in slides["plain"]
    assert "Welcome aboard" in slides["plain"] and "Thanks everyone" in slides["plain"]
    assert slides["pages"] == 2
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, b"application/zip")
        zf.writestr("content.xml", b"<text:p>NOT-A-SHEET</text:p>")
        zf.writestr("readme.txt", b"hello")
    listed = CV.convert_bytes(plain_zip.getvalue(), "budget.ods")
    assert listed["ok"] and listed["type"] == "zip", listed
    assert "content.xml" in listed["plain"]
    assert "NOT-A-SHEET" not in listed["plain"]
    broken = CV.convert_bytes(_odf_package(_ODT_MIME, "<not xml"), "bad.odt")
    assert broken["ok"] is False
    assert "could not be read" in broken["error"].lower()
    assert "not xml" not in broken["error"]
    assert _MACRO_BODY not in json.dumps(broken)
    missing_buf = io.BytesIO()
    with zipfile.ZipFile(missing_buf, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, _ODS_MIME.encode("ascii"))
        zf.writestr("meta.xml", b"<ok/>")
    missing = CV.convert_bytes(missing_buf.getvalue(), "gone.ods")
    assert missing["ok"] is False
    assert "could not be read" in missing["error"].lower()
    assert missing.get("plain", "") == ""


def test_zip_lists_only_and_unknown_rejected():
    listing = CV.convert_bytes(FILES["bundle.zip"], "bundle.zip")
    assert listing["ok"] and listing["type"] == "zip"
    assert "readme.txt" in listing["plain"]
    assert "SECRET-BODY" not in listing["plain"]
    bad = CV.convert_bytes(b"\x00\x01\x02\x03binary", "thing.bin")
    assert bad["ok"] is False
    assert "supported" in bad["error"].lower()


def test_size_limit_and_policy_and_budget():
    huge = b"x" * (CV.MAX_BYTES + 1)
    over = CV.convert_bytes(huge, "big.txt")
    assert over["ok"] is False and "50" in over["error"]
    assert CV.MAX_FILES == 10
    assert CV.CONVERT_TIMEOUT_SECS == 60
    blocks = []
    for name in ("text.pdf", "note.docx", "slides.pptx", "tiny.csv", "sample.json"):
        result = CV.convert_bytes(FILES[name], name, vision=False)
        assert result["ok"], result
        assert result["text"].startswith("<attachment ")
        blocks.append(result["text"])
    question = "\n\n".join(blocks) + "\n\nWhat do these files say?"
    fitted, meta = CV.budget_messages([{"role": "user", "content": question}], 8192)
    assert "<attachment " in fitted[0]["content"]
    assert meta["used"] is True
    packed = "word " * 8000
    wrapped = CV.wrap_attachment("fat.txt", "txt", packed, truncated=False)
    _out, meta2 = CV.budget_messages(
        [{"role": "user", "content": wrapped + "\n\nSummarize the file."}],
        400,
    )
    assert meta2["truncated"] is True
    assert 'truncated="true"' in _out[0]["content"]
    policied = CV.ensure_policy(_out)
    assert CV.POLICY in policied[0]["content"]
    argv = CV.sandbox_argv(str(SCRIPT))
    assert str(SCRIPT) in " ".join(argv) or SCRIPT.name in " ".join(argv)


def _without_fitz(fn):
    import builtins

    real = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "fitz" or str(name).startswith("fitz."):
            raise ImportError("fitz blocked")
        return real(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded
    try:
        return fn()
    finally:
        builtins.__import__ = real


def test_small_pdf_ignores_binary_stream():
    blob = _pdf_with_binary("Hello from four pages of notes about the garden.")
    def run():
        return CV.convert_bytes(blob, "notes.pdf", vision=False)
    result = _without_fitz(run)
    assert result["ok"], result
    assert result["text"].count("<attachment ") == 1
    assert "Hello from four pages" in result["plain"]
    assert "BINBLOB" not in result["plain"]
    assert "QQQQ" not in result["plain"]
    assert "ZZZZ" not in result["plain"]
    assert CV.rough_tokens(result["text"]) < 4000
    direct = _without_fitz(lambda: CV._pdf_text_streams(blob))
    assert "Hello from four pages" in direct
    assert CV.rough_tokens(direct) < 4000
    junk = b"%PDF-1.4\n" + b"(".join([b"Q" * 2000 for _ in range(40)])
    bad = _without_fitz(lambda: CV.convert_bytes(junk, "junk.pdf", vision=False))
    assert bad["ok"] is False
    assert "PDF" in bad["error"]
    assert CV.rough_tokens(str(bad.get("plain") or bad.get("text") or "")) < 4000
    cmap = b"beginbfchar\n5\n<01> <0048>\n<02> <0065>\n<03> <006C>\n<04> <006F>\n<05> <0020>\nendbfchar\n"
    coded = b"BT <0102030304> Tj ET"
    coded_pdf = _pdf_objects([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(coded) + coded + b"\nendstream",
        b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream",
    ])
    mapped = _without_fitz(lambda: CV.convert_bytes(coded_pdf, "coded.pdf", vision=False))
    assert mapped["ok"], mapped
    assert "Hello" in mapped["plain"]


def test_rough_tokens_within_3x_and_budget_refuses():
    raw = bytes(i % 256 for i in range(3000))
    text = raw.decode("latin-1")
    assert CV.rough_tokens(text) * 3 >= len(text.encode("utf-8"))
    prose = "hello " * 200
    assert CV.rough_tokens(prose) < 2000
    wrapped = CV.wrap_attachment("notes.pdf", "pdf", "hello garden " * 40)
    messages = [{"role": "user", "content": wrapped}]

    def boom(_text):
        raise RuntimeError("tokenize failed")

    try:
        CV.budget_for_chat(messages, 128000, boom)
        raise AssertionError("unbudgeted attachment was returned")
    except CV.AttachmentBudgetError as exc:
        assert "context" in str(exc).lower()
    plain, _meta = CV.budget_for_chat([{"role": "user", "content": "hi"}], 8192, boom)
    assert plain[0]["content"] == "hi"
    url = "data:image/jpeg;base64," + ("A" * 300000)
    packed = [{
        "role": "user",
        "content": [
            {"type": "text", "text": CV.wrap_attachment("s.pdf", "pdf", "A short scan note.")},
            {"type": "image_url", "image_url": {"url": url}},
        ],
    }]
    fitted, meta = CV.budget_messages(packed, 8192)
    assert "A" * 1000 not in json.dumps(fitted)
    assert meta["truncated"] is True
    assert "scan note" in json.dumps(fitted)


def test_gateway_budget_failure_drops_attachment():
    gateway = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
    loader = importlib.machinery.SourceFileLoader("stickllm_gateway_test", str(gateway))
    spec = importlib.util.spec_from_loader("stickllm_gateway_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    wrapped = CV.wrap_attachment("notes.pdf", "pdf", "hello garden " * 40)
    messages = [{"role": "user", "content": wrapped + "\n\nSummarize"}]

    def boom(_text):
        raise RuntimeError("tokenize failed")

    fitted, _meta, err = mod.fit_chat_messages(messages, 128000, boom)
    assert fitted is None
    assert "context" in err.lower()
    assert wrapped not in err


def test_cli_roundtrip():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=FILES["tiny.csv"],
        capture_output=True,
        env={
            "STICKLLM_ATTACH_NAME": "tiny.csv",
            "STICKLLM_ATTACH_VISION": "0",
            "PATH": "",
        },
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout.decode())
    assert doc["ok"] and "alpha" in doc["plain"]


def _tiny_jpeg(w: int = 8, h: int = 8) -> bytes:
    sof = bytes([
        0xFF, 0xC0, 0x00, 0x0B, 0x08,
        (h >> 8) & 0xFF, h & 0xFF,
        (w >> 8) & 0xFF, w & 0xFF,
        0x01, 0x01, 0x11, 0x00,
    ])
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + sof
        + b"\xff\xd9"
    )


def _blank_pdf(n: int) -> bytes:
    kids = " ".join(f"{3 + i} 0 R" for i in range(n))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
    ]
    for _ in range(n):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>"
        )
    return _pdf_objects(objects)


def _scan_blob() -> bytes:
    blob = b"(" + (b"Q" * 180000) + b")BINBLOB"
    return _pdf_objects([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /Im0 4 0 R >> >> >>",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length %d >>\nstream\n" % len(blob) + blob + b"\nendstream",
    ])


class _RenderPatch:
    def __init__(self, blobs):
        self.blobs = blobs
        self.calls = 0
        self._real = None

    def __enter__(self):
        self._real = CV._render_scan_jpegs

        def fake(_data):
            self.calls += 1
            return self.blobs

        CV._render_scan_jpegs = fake
        return self

    def __exit__(self, exc_type, exc, tb):
        CV._render_scan_jpegs = self._real
        return False


def test_scan_without_renderer_is_a_short_note():
    blob = _scan_blob()

    def run():
        with _RenderPatch(None):
            return CV.convert_bytes(blob, "scan.pdf", vision=True)

    result = _without_fitz(run)
    assert result["ok"], result
    assert result["images"] == []
    assert result["text"].count("<attachment ") == 1
    assert CV.rough_tokens(result["text"]) < 4000
    assert len(result["plain"]) < 2000
    assert "poppler-utils" in result["plain"]
    assert "pdftoppm" in result["plain"]
    assert "QQQQ" not in result["plain"]
    assert "BINBLOB" not in result["plain"]
    off = _without_fitz(lambda: CV.convert_bytes(blob, "scan.pdf", vision=False))
    assert off["ok"] and off["images"] == []
    assert "scan" in off["plain"].lower()
    assert "vision" in off["plain"].lower() or "Tesseract" in off["plain"]
    assert CV.rough_tokens(off["text"]) < 4000
    assert "QQQQ" not in off["plain"]
    real_tool = CV._tool
    CV._tool = lambda _name: ""
    try:
        assert CV._render_scan_jpegs(FILES["scanned.pdf"]) is None
    finally:
        CV._tool = real_tool


def test_scan_page_images_are_bounded():
    assert CV.MAX_PAGE_IMAGES == 8
    tiny = _tiny_jpeg(32, 24)
    assert CV._jpeg_size(tiny) == (32, 24)
    assert CV._jpeg_bounded(tiny)
    assert not CV._jpeg_bounded(_tiny_jpeg(2000, 10))
    fat = _tiny_jpeg(8, 8)[:-2] + (b"\x00" * (CV.PAGE_IMAGE_BYTES + 20)) + b"\xff\xd9"
    assert not CV._jpeg_bounded(CV._trim_jpeg(fat))
    four = _blank_pdf(4)

    def run4():
        with _RenderPatch([tiny] * 4) as patch:
            return CV.convert_bytes(four, "scan.pdf", vision=True), patch.calls

    doc, calls = _without_fitz(run4)
    assert calls == 1
    assert doc["ok"] and doc["pages"] == 4, doc
    assert len(doc["images"]) == 4
    assert doc["text"].count("<attachment ") == 1
    assert "Read the attached page images." in doc["plain"]
    assert CV.rough_tokens(doc["text"]) < 4000
    assert "QQQQ" not in doc["plain"]
    for im in doc["images"]:
        raw = base64.b64decode(im["data_base64"])
        assert raw.startswith(b"\xff\xd8")
        assert len(raw) <= CV.PAGE_IMAGE_BYTES
        width, height = CV._jpeg_size(raw)
        assert 1 <= max(width, height) <= CV.PAGE_IMAGE_EDGE
        assert im["mime"] == "image/jpeg"

    def run9():
        with _RenderPatch([tiny] * 9):
            return CV.convert_bytes(_blank_pdf(9), "scan.pdf", vision=True)

    capped = _without_fitz(run9)
    assert len(capped["images"]) == 8
    assert "first 8 of 9" in capped["plain"]

    def run_bad():
        with _RenderPatch([fat, _tiny_jpeg(2000, 10)]):
            return CV.convert_bytes(four, "scan.pdf", vision=True)

    bad = _without_fitz(run_bad)
    assert bad["ok"] and bad["images"] == []
    assert "usable page images" in bad["plain"]
    assert CV.rough_tokens(bad["text"]) < 4000
    assert "QQQQ" not in bad["plain"]

    def run_text():
        with _RenderPatch([tiny]) as patch:
            return CV.convert_bytes(FILES["text.pdf"], "text.pdf", vision=True), patch.calls

    text, text_calls = _without_fitz(run_text)
    assert text_calls == 0
    assert text["images"] == []
    assert "Hello PDF" in text["plain"]
    assert text["text"].count("<attachment ") == 1

    def run_off():
        with _RenderPatch([tiny]) as patch:
            return CV.convert_bytes(four, "scan.pdf", vision=False), patch.calls

    off, off_calls = _without_fitz(run_off)
    assert off_calls == 0
    assert off["images"] == []
    assert "scan" in off["plain"].lower()
    url = "data:image/jpeg;base64," + base64.b64encode(tiny).decode()
    packed = [{
        "role": "user",
        "content": [
            {"type": "text", "text": CV.wrap_attachment("scan.pdf", "pdf", doc["plain"])},
            *[{"type": "image_url", "image_url": {"url": url}} for _ in range(4)],
        ],
    }]
    fitted, meta = CV.budget_messages(packed, 8192)
    kept = [
        p for p in fitted[0]["content"]
        if isinstance(p, dict) and p.get("type") == "image_url"
    ]
    assert len(kept) == 4
    assert meta["truncated"] is False


def test_gateway_keeps_four_scan_pages():
    gateway = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
    loader = importlib.machinery.SourceFileLoader("stickllm_gateway_pages", str(gateway))
    spec = importlib.util.spec_from_loader("stickllm_gateway_pages", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    url = "data:image/jpeg;base64," + base64.b64encode(_tiny_jpeg()).decode()

    def parts(n):
        content = [{"type": "text", "text": CV.wrap_attachment("scan.pdf", "pdf", "Read the attached page images.")}]
        content += [{"type": "image_url", "image_url": {"url": url}} for _ in range(n)]
        return [{"role": "user", "content": content}]

    out = mod.sanitize_chat_messages(parts(4))
    kept = [p for p in out[0]["content"] if p.get("type") == "image_url"]
    assert len(kept) == 4
    out_many = mod.sanitize_chat_messages(parts(12))
    kept_many = [p for p in out_many[0]["content"] if p.get("type") == "image_url"]
    assert len(kept_many) == 3 + CV.MAX_PAGE_IMAGES


class AttachmentTests(unittest.TestCase):
    def test_text_pdf_and_scan_and_broken(self):
        test_text_pdf_and_scan_and_broken()

    def test_docx_pptx_macro_not_executed(self):
        test_docx_pptx_macro_not_executed()

    def test_xlsx_truncates_and_csv_json(self):
        test_xlsx_truncates_and_csv_json()

    def test_opendocument_formats(self):
        test_opendocument_formats()

    def test_zip_lists_only_and_unknown_rejected(self):
        test_zip_lists_only_and_unknown_rejected()

    def test_size_limit_and_policy_and_budget(self):
        test_size_limit_and_policy_and_budget()

    def test_small_pdf_ignores_binary_stream(self):
        test_small_pdf_ignores_binary_stream()

    def test_rough_tokens_within_3x_and_budget_refuses(self):
        test_rough_tokens_within_3x_and_budget_refuses()

    def test_gateway_budget_failure_drops_attachment(self):
        test_gateway_budget_failure_drops_attachment()

    def test_cli_roundtrip(self):
        test_cli_roundtrip()

    def test_scan_without_renderer_is_a_short_note(self):
        test_scan_without_renderer_is_a_short_note()

    def test_scan_page_images_are_bounded(self):
        test_scan_page_images_are_bounded()

    def test_gateway_keeps_four_scan_pages(self):
        test_gateway_keeps_four_scan_pages()


if __name__ == "__main__":
    unittest.main()
