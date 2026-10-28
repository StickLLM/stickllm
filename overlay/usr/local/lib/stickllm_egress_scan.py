"""StickLLM Agent Zero pre-execution egress scan (v0.5.3).

Standard library only. The same text is copied into the Agent Zero plugin
(tool_execute_before) and is imported by the host for tests and logging.
It is a tripwire that shows a warning; the nftables rules and the egress
proxy on the host are what actually stop traffic.
"""
from __future__ import annotations

import ipaddress
import re

# Always blocked, whatever the settings say.
ALWAYS_BLOCK_HOSTS = (
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
    "instance-data.ec2.internal",
    "routify-file-proxy-sg.oss-ap-southeast-1.aliyuncs.com",
    "sanmaohe.oss-cn-beijing.aliyuncs.com",
)
ALWAYS_BLOCK_IPS = ("169.254.169.254", "100.100.100.200", "fd00:ec2::254", "169.254.170.2")
# Cloud metadata and link-local ranges.
ALWAYS_BLOCK_NETS = ("169.254.0.0/16", "100.100.100.200/32", "fd00:ec2::254/128", "fe80::/10")
# Blocked by default: Alibaba Cloud OSS/ECS endpoints (used in the Cohere report).
DEFAULT_BLOCK_SUFFIXES = ("aliyuncs.com", "aliyun.com", "alicdn.com")

# The container may always talk to these (llama relay, apps, control bridge, itself).
LOCAL_HOSTS = (
    "172.30.0.1",
    "llama",
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
)

NET_TOOLS = (
    "curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "ssh", "scp", "sftp",
    "rsync", "ftp", "tftp", "aria2c", "http", "https", "httpie", "xh", "lynx", "links", "w3m",
    "ossutil", "ossutil64", "aliyun", "aws", "gsutil", "gcloud", "az", "rclone", "s3cmd",
    "nmap", "dig", "nslookup", "host", "ping", "traceroute", "git", "pip", "pip3", "npm",
    "openssl",
)
NS_TOOLS = ("unshare", "nsenter")

_URL_RE = re.compile(
    r"\b(?P<scheme>https?|ftps?|wss?|sftp|scp|tftp|gopher|dict|telnet|ldaps?|smb|rsync|s3|oss|gs)://"
    r"(?P<netloc>[^\s/'\"`<>?#\\)]+)",
    re.I,
)
_IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_DOMAIN_RE = re.compile(r"(?<![\w.@-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(?![\w-])", re.I)
_SEGMENT_SPLIT = re.compile(r"(?:\|\||&&|[;|&\n]|\$\(|`)")
_TOOL_RE = re.compile(
    r"(?:^|[\s(\"'=/])(?P<tool>" + "|".join(re.escape(t) for t in sorted(NET_TOOLS, key=len, reverse=True)) + r")(?=\s|$)",
    re.I,
)
_NS_RE = re.compile(r"(?:^|[\s;|&(\"'/])(unshare|nsenter)(?=\s|$)|CLONE_NEWUSER|\bsetns\s*\(|os\.unshare\s*\(", re.I)
_UPLOAD_RE = re.compile(
    r"(?:\s-T\s|\s--upload-file[\s=]|\s-X\s*(?:PUT|POST|PATCH)\b|\s--request[\s=](?:PUT|POST|PATCH)\b"
    r"|\s--data(?:-binary|-raw|-urlencode)?[\s=]@|\s-d\s*@|\s-F\s|\s--form[\s=]|\s--method=(?:PUT|POST)"
    r"|\s--post-file[\s=]|\s--body-file[\s=]|\bput\s|\bcp\s+\S+\s+(?:oss|s3|gs)://)",
    re.I,
)
# File extensions that look like domains in shell code (report.md, data.json).
_NOT_TLDS = {
    "py", "sh", "md", "txt", "json", "yaml", "yml", "csv", "log", "js", "ts", "html", "htm",
    "css", "xml", "toml", "ini", "cfg", "conf", "pdf", "png", "jpg", "jpeg", "gif", "zip",
    "tar", "gz", "tgz", "bz2", "xz", "whl", "lock", "pem", "key", "crt", "db", "sqlite",
    "env", "pid", "sock", "service", "so", "bin", "out", "tmp", "bak", "old", "new", "doc",
    "docx", "xlsx", "pptx", "odt", "ods", "mp3", "mp4", "wav", "webm", "svg", "ico", "ipynb",
    "local", "internal_ok", "rs", "go", "c", "h", "cpp", "java", "rb", "pl", "php", "lua",
}

SHELL_TOOLS = ("code_execution_tool", "code_execution", "input", "terminal")
URL_TOOLS = ("document_query", "browser_agent", "browser", "browser_open", "browser_do")


def norm_host(raw: str) -> str:
    host = str(raw or "").strip().lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def _ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def always_blocked(host: str) -> str:
    """Reason when ``host`` is always blocked, else ''."""
    h = norm_host(host)
    if not h:
        return ""
    if h in ALWAYS_BLOCK_HOSTS:
        return "metadata or known exfiltration host"
    ip = _ip(h)
    if ip is not None:
        if str(ip) in ALWAYS_BLOCK_IPS:
            return "cloud metadata address"
        for net in ALWAYS_BLOCK_NETS:
            n = ipaddress.ip_network(net)
            if ip.version == n.version and ip in n:
                return "cloud metadata or link-local address"
    return ""


def default_blocked(host: str) -> str:
    h = norm_host(host)
    for suf in DEFAULT_BLOCK_SUFFIXES:
        if h == suf or h.endswith("." + suf):
            return "Alibaba Cloud storage/endpoint (blocked by default)"
    return ""


def is_local(host: str) -> bool:
    h = norm_host(host)
    if h in LOCAL_HOSTS:
        return True
    ip = _ip(h)
    if ip is not None and ip.version == 4 and ip in ipaddress.ip_network("172.30.0.0/24"):
        return True
    return ip is not None and ip.is_loopback


def host_verdict(host: str, web_fetch: bool = False) -> str:
    """'' when the agent may name this host, else the reason."""
    h = norm_host(host)
    if not h:
        return ""
    reason = always_blocked(h)
    if reason:
        return reason
    if is_local(h):
        return ""
    reason = default_blocked(h)
    if reason:
        return reason
    if web_fetch:
        ip = _ip(h)
        if ip is not None and not ip.is_global:
            return "private or reserved address"
        return ""
    return "outbound internet is off for the agent"


def _hosts_in(text: str) -> list[str]:
    hosts: list[str] = []

    def add(h: str) -> None:
        h = norm_host(h)
        if h and h not in hosts:
            hosts.append(h)

    for m in _URL_RE.finditer(text):
        add(m.group("netloc"))
    for m in _IPV4_RE.finditer(text):
        parts = m.group(1).split(".")
        if all(0 <= int(p) <= 255 for p in parts):
            add(m.group(1))
    for m in _DOMAIN_RE.finditer(text):
        dom = m.group(1)
        tld = dom.rsplit(".", 1)[-1].lower()
        if tld in _NOT_TLDS:
            continue
        add(dom)
    for tok in re.findall(r"\[?[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}\]?", text, re.I):
        if _ip(tok.strip("[]")) is not None:
            add(tok.strip("[]"))
    return hosts


def scan_text(code: str, *, shell: bool = True, web_fetch: bool = False) -> list[dict]:
    """Findings for one tool call. Empty list = allowed."""
    text = str(code or "")
    if not text.strip():
        return []
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def flag(kind: str, target: str, reason: str) -> None:
        key = (kind, target)
        if key in seen:
            return
        seen.add(key)
        findings.append({"kind": kind, "target": target[:200], "reason": reason})

    low = text.lower()
    # Always-blocked names and addresses anywhere in the call (strings, Python, base URLs).
    for host in ALWAYS_BLOCK_HOSTS:
        if host != "metadata" and host != "instance-data" and host in low:
            flag("blocked_host", host, "metadata or known exfiltration host")
    for h in _hosts_in(text):
        reason = always_blocked(h)
        if reason:
            flag("blocked_host", h, reason)
        elif default_blocked(h):
            flag("blocked_host", h, default_blocked(h))
    # URLs anywhere (Python requests, urllib, fetch, ...).
    for m in _URL_RE.finditer(text):
        h = norm_host(m.group("netloc"))
        reason = host_verdict(h, web_fetch=web_fetch)
        if reason:
            flag("outbound_url", m.group(0), reason)
    if shell:
        for seg in _SEGMENT_SPLIT.split(text):
            if _NS_RE.search(seg):
                flag("namespace", seg.strip()[:120], "user/mount namespaces are disabled for the agent")
            tm = _TOOL_RE.search(seg)
            if not tm:
                continue
            tool = tm.group("tool").lower()
            rest = seg[tm.end():]
            targets = [h for h in _hosts_in(rest) if not is_local(h)]
            for h in targets:
                reason = host_verdict(h, web_fetch=web_fetch)
                if reason:
                    flag("network_tool", f"{tool} {h}", reason)
            if targets and _UPLOAD_RE.search(" " + rest + " "):
                flag("upload", f"{tool} {targets[0]}", "uploads from the agent to outside hosts are blocked")
    else:
        if _NS_RE.search(text):
            flag("namespace", "unshare/setns", "user/mount namespaces are disabled for the agent")
    return findings


def scan_tool_call(tool_name: str, tool_args, *, web_fetch: bool = False) -> list[dict]:
    name = str(tool_name or "").strip().lower()
    if not isinstance(tool_args, dict):
        return []
    if name in SHELL_TOOLS:
        shell = True
    elif name in URL_TOOLS:
        shell = False
    else:
        return []
    out: list[dict] = []
    for value in tool_args.values():
        if isinstance(value, str):
            out.extend(scan_text(value, shell=shell, web_fetch=web_fetch))
    return out


def describe(findings: list[dict]) -> str:
    bits = []
    for f in findings[:6]:
        bits.append(f"{f.get('target')} ({f.get('reason')})")
    return "; ".join(bits)
