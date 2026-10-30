"""StickLLM window helper for the stock Debian ``sway`` compositor (MIT).

The kiosk runs the unmodified Debian sway package with our own config file
(/etc/stickllm/sway/config). This module is our own separate code: it talks to
sway only over sway's documented IPC socket (the i3-ipc wire format: the
6-byte magic "i3-ipc", payload length, message type, JSON payload). It does
not link against, import or copy any compositor code.

What it does for the desktop:
  * place a floating window (move + resize) where the desktop asked,
  * minimise (sway scratchpad), restore, maximise to the work area
    (screen minus the desktop taskbar), focus, close,
  * report every window's state for the desktop taskbar,
  * keep the full-screen desktop Chromium tiled at the bottom ("watch").

The previous rectangle of a minimised/maximised window is kept as a sway mark
on the window itself (``stickllm_rect_<x>_<y>_<w>_<h>``), so the compositor is
the single source of truth and the root control service and the kiosk user's
keyboard shortcuts see the same state.
"""
from __future__ import annotations

import glob
import json
import os
import re
import socket
import struct
import time

MAGIC = b"i3-ipc"
HEADER = struct.Struct("=II")  # payload length, message type (host byte order)
RUN_COMMAND, GET_WORKSPACES, SUBSCRIBE, GET_OUTPUTS, GET_TREE = 0, 1, 2, 3, 4
EVENT_BIT = 0x80000000
MAX_PAYLOAD = 64 * 1024 * 1024

DESKTOP_APP_ID = "stickllm-desktop"
BROWSER_PREFIX = "stickllm-browser-"
DESKTOP_MARK = "stickllm_desktop"
BID_MARK = "stickllm_bid_"
RECT_MARK = "stickllm_rect_"
SCRATCH = "__i3_scratch"
TASKBAR_PX = 48
MIN_W, MIN_H = 320, 200
_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class WMError(Exception):
    pass


# ---- wire format ---------------------------------------------------------
def pack(msg_type: int, payload: str | bytes = b"") -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return MAGIC + HEADER.pack(len(payload), msg_type) + payload


def unpack_header(head: bytes) -> tuple[int, int]:
    if len(head) != len(MAGIC) + HEADER.size or head[: len(MAGIC)] != MAGIC:
        raise WMError("bad ipc header")
    length, msg_type = HEADER.unpack(head[len(MAGIC):])
    if length > MAX_PAYLOAD:
        raise WMError("ipc payload too large")
    return length, msg_type


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise WMError("ipc socket closed")
        buf += chunk
    return bytes(buf)


def find_socket(runtime_dirs: list[str] | None = None) -> str:
    """SWAYSOCK, else the newest sway-ipc.*.sock in the given runtime dirs."""
    env = os.environ.get("SWAYSOCK", "")
    if env and os.path.exists(env):
        return env
    dirs = runtime_dirs or [os.environ.get("XDG_RUNTIME_DIR", "")]
    found = []
    for d in dirs:
        if not d:
            continue
        for p in glob.glob(os.path.join(d, "sway-ipc.*.sock")):
            try:
                found.append((os.stat(p).st_mtime, p))
            except OSError:
                pass
    if not found:
        raise WMError("sway is not running")
    return sorted(found)[-1][1]


class SwayIPC:
    def __init__(self, path: str, timeout: float = 3.0):
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(path)
        except OSError as e:
            self.sock.close()
            raise WMError(f"cannot reach sway: {e}") from e

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def request(self, msg_type: int, payload: str = ""):
        self.sock.sendall(pack(msg_type, payload))
        return self.read()[1]

    def read(self):
        length, msg_type = unpack_header(_recv_exact(self.sock, len(MAGIC) + HEADER.size))
        body = _recv_exact(self.sock, length) if length else b""
        try:
            return msg_type, json.loads(body.decode("utf-8") or "null")
        except ValueError as e:
            raise WMError("bad ipc json") from e

    def command(self, cmd: str) -> list:
        res = self.request(RUN_COMMAND, cmd)
        return res if isinstance(res, list) else [res]

    def tree(self) -> dict:
        return self.request(GET_TREE)

    def outputs(self) -> list:
        return self.request(GET_OUTPUTS)


def command_ok(results: list) -> bool:
    return bool(results) and all(isinstance(r, dict) and r.get("success") for r in results)


# ---- tree helpers ----------------------------------------------------------
def iter_windows(tree: dict):
    """Yield every application window with workspace / scratchpad info added."""
    def walk(node, ws):
        if node.get("type") == "workspace":
            ws = node.get("name")
        if node.get("type") in ("con", "floating_con") and (node.get("pid") or node.get("app_id")) \
                and not node.get("nodes") and not node.get("floating_nodes"):
            yield dict(node, workspace=ws, minimised=(ws == SCRATCH),
                       floating=(node.get("type") == "floating_con"))
        for child in list(node.get("nodes") or []) + list(node.get("floating_nodes") or []):
            yield from walk(child, ws)
    yield from walk(tree or {}, None)


def window_by(tree: dict, *, con_id: int | None = None, app_id: str | None = None, pid: int | None = None):
    for w in iter_windows(tree):
        if con_id is not None and w.get("id") == con_id:
            return w
        if app_id is not None and w.get("app_id") == app_id:
            return w
        if pid is not None and w.get("pid") == pid:
            return w
    return None


def browser_app_id(bid: str) -> str:
    if not _ID_RE.match(str(bid or "")):
        raise WMError("bad window id")
    return BROWSER_PREFIX + bid


def bid_mark(bid: str) -> str:
    browser_app_id(bid)  # validates
    return BID_MARK + bid


def bid_of(w: dict) -> str | None:
    """Our browser id for a window: its stickllm_bid_ mark, else its --class app_id."""
    for m in w.get("marks") or []:
        if m.startswith(BID_MARK) and _ID_RE.match(m[len(BID_MARK):]):
            return m[len(BID_MARK):]
    a = str(w.get("app_id") or "")
    if a.startswith(BROWSER_PREFIX) and _ID_RE.match(a[len(BROWSER_PREFIX):]):
        return a[len(BROWSER_PREFIX):]
    return None


def window_for(tree: dict, bid: str, owns=None):
    """Find browser window `bid`: by mark, then app_id, then (Chromium --app
    windows ignore --class on Wayland) by owning process via owns(pid)."""
    browser_app_id(bid)
    loose = None
    for w in iter_windows(tree):
        if bid_of(w) == bid:
            return w
        if loose is None and owns is not None and not is_desktop(w) and w.get("pid") \
                and bid_of(w) is None and owns(int(w["pid"])):
            loose = w
    return loose


def adopt_cmd(w: dict, bid: str) -> str:
    """Mark a window with its browser id so later lookups never guess."""
    return f"[con_id={int(w['id'])}] mark --add {bid_mark(bid)}"


def is_desktop(w: dict) -> bool:
    return DESKTOP_MARK in (w.get("marks") or []) or (
        w.get("app_id") == DESKTOP_APP_ID and not w.get("floating") and not w.get("minimised"))


def work_area(outputs: list, taskbar_px: int = TASKBAR_PX) -> dict:
    """Screen of the first active output minus the desktop taskbar at the bottom."""
    act = [o for o in (outputs or []) if o.get("active")]
    o = (act or outputs or [{}])[0]
    r = o.get("rect") or {"x": 0, "y": 0, "width": 1280, "height": 800}
    scale = float(o.get("scale") or 1.0) or 1.0
    bar = int(round(max(0, int(taskbar_px)) / scale))
    return {"x": int(r["x"]), "y": int(r["y"]), "w": int(r["width"]), "h": max(MIN_H, int(r["height"]) - bar),
            "scale": scale}


def clamp_to_work(geo: dict, work: dict) -> dict:
    """Keep a window inside the work area so its title bar stays reachable."""
    w = max(MIN_W, min(int(geo["w"]), work["w"]))
    h = max(MIN_H, min(int(geo["h"]), work["h"]))
    x = max(work["x"], min(int(geo["x"]), work["x"] + work["w"] - w))
    y = max(work["y"], min(int(geo["y"]), work["y"] + work["h"] - h))
    return {"x": x, "y": y, "w": w, "h": h}


def rect_of(w: dict) -> dict:
    """Outer rectangle (title bar included) of a window, in sway layout coords."""
    r = w.get("rect") or {}
    d = w.get("deco_rect") or {}
    dh = int(d.get("height") or 0)
    return {"x": int(r.get("x", 0)), "y": int(r.get("y", 0)) - dh,
            "w": int(r.get("width", 0)), "h": int(r.get("height", 0)) + dh}


def rect_mark(geo: dict) -> str:
    return f"{RECT_MARK}{int(geo['x'])}_{int(geo['y'])}_{int(geo['w'])}_{int(geo['h'])}".replace("-", "m")


def saved_rect(w: dict) -> dict | None:
    for m in w.get("marks") or []:
        if m.startswith(RECT_MARK):
            try:
                x, y, ww, hh = (int(v.replace("m", "-")) for v in m[len(RECT_MARK):].split("_"))
                return {"x": x, "y": y, "w": ww, "h": hh}
            except ValueError:
                return None
    return None


def place_cmd(con_id: int, geo: dict) -> str:
    return (f"[con_id={int(con_id)}] floating enable, border normal 2, "
            f"resize set width {int(geo['w'])} px height {int(geo['h'])} px, "
            f"move absolute position {int(geo['x'])} px {int(geo['y'])} px")


def save_rect_cmds(w: dict, geo: dict) -> list[str]:
    cid = int(w["id"])
    cmds = [f"[con_id={cid}] unmark {m}" for m in (w.get("marks") or []) if m.startswith(RECT_MARK)]
    cmds.append(f"[con_id={cid}] mark --add {rect_mark(geo)}")
    return cmds


def is_maximised(w: dict, work: dict) -> bool:
    r = rect_of(w)
    return abs(r["w"] - work["w"]) <= 8 and abs(r["h"] - work["h"]) <= 8 and abs(r["x"] - work["x"]) <= 8 \
        and abs(r["y"] - work["y"]) <= 8


def window_state(w: dict, work: dict) -> dict:
    return {"con_id": w.get("id"), "app_id": w.get("app_id"), "title": w.get("name") or "",
            "minimised": bool(w.get("minimised")), "focused": bool(w.get("focused")),
            "maximised": (not w.get("minimised")) and is_maximised(w, work), "rect": rect_of(w)}


# ---- operations ------------------------------------------------------------
OPS = ("place", "minimise", "restore", "maximise", "focus", "toggle", "close", "state")


def plan(op: str, w: dict, work: dict, geo: dict | None = None) -> list[str]:
    """sway commands for one operation on window ``w`` (pure, for tests)."""
    if op not in OPS:
        raise WMError("bad op")
    if is_desktop(w):
        raise WMError("the desktop window cannot be changed")
    cid = int(w["id"])
    sel = f"[con_id={cid}]"
    if op == "toggle":
        op = "restore" if w.get("minimised") else ("minimise" if w.get("focused") else "focus")
    if op == "state":
        return []
    if op == "place":
        if not geo:
            raise WMError("geometry required")
        # The desktop sends physical pixels; sway lays out in logical pixels.
        k = float(work.get("scale") or 1.0) or 1.0
        g = clamp_to_work({key: round(float(geo[key]) / k) for key in ("x", "y", "w", "h")}, work)
        cmds = [f"{sel} scratchpad show"] if w.get("minimised") else []
        return cmds + [place_cmd(cid, g), f"{sel} focus"]
    if op == "minimise":
        if w.get("minimised"):
            return []
        return save_rect_cmds(w, rect_of(w)) + [f"{sel} move scratchpad"]
    if op == "restore" or (op == "focus" and w.get("minimised")):
        g = saved_rect(w)
        cmds = [f"{sel} scratchpad show"] if w.get("minimised") else []
        if g:
            cmds.append(place_cmd(cid, clamp_to_work(g, work)))
        return cmds + [f"{sel} focus"]
    if op == "focus":
        return [f"{sel} focus"]
    if op == "maximise":
        if not w.get("minimised") and is_maximised(w, work):
            g = saved_rect(w) or {"x": work["x"] + work["w"] // 8, "y": work["y"] + work["h"] // 8,
                                  "w": work["w"] * 3 // 4, "h": work["h"] * 3 // 4}
            return [place_cmd(cid, clamp_to_work(g, work)), f"{sel} focus"]
        cmds = [f"{sel} scratchpad show"] if w.get("minimised") else save_rect_cmds(w, rect_of(w))
        return cmds + [place_cmd(cid, work), f"{sel} focus"]
    if op == "close":
        return [f"{sel} kill"]
    raise WMError("bad op")


def run_plan(ipc: SwayIPC, cmds: list[str]) -> bool:
    ok = True
    for c in cmds:
        ok = command_ok(ipc.command(c)) and ok
    return ok


def apply(ipc: SwayIPC, op: str, *, con_id=None, app_id=None, pid=None, geo=None,
          taskbar_px: int = TASKBAR_PX) -> dict:
    tree = ipc.tree()
    w = window_by(tree, con_id=con_id, app_id=app_id, pid=pid)
    if not w:
        raise WMError("window not found")
    work = work_area(ipc.outputs(), taskbar_px)
    ok = run_plan(ipc, plan(op, w, work, geo))
    w2 = window_by(ipc.tree(), con_id=w["id"]) or w
    return {"ok": ok, "window": window_state(w2, work)}


def wait_window(ipc: SwayIPC, *, app_id=None, pid=None, timeout: float = 20.0) -> dict | None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        w = window_by(ipc.tree(), app_id=app_id, pid=pid)
        if w:
            return w
        time.sleep(0.25)
    return None


def states(ipc: SwayIPC, taskbar_px: int = TASKBAR_PX) -> dict:
    """{browser id: state} for our browser windows (marked or --class app_id)."""
    work = work_area(ipc.outputs(), taskbar_px)
    out = {}
    for w in iter_windows(ipc.tree()):
        b = bid_of(w)
        if b and b not in out:
            out[b] = window_state(w, work)
    return out


def wait_for(ipc: SwayIPC, bid: str, owns=None, timeout: float = 20.0) -> dict | None:
    """Wait for browser window `bid` to map, then mark it with its id."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        w = window_for(ipc.tree(), bid, owns)
        if w:
            if bid_mark(bid) not in (w.get("marks") or []):
                command_ok(ipc.command(adopt_cmd(w, bid)))
            return w
        time.sleep(0.25)
    return None


def focused(tree: dict):
    for w in iter_windows(tree):
        if w.get("focused"):
            return w
    return None


# ---- desktop guard (run from the sway session) --------------------------------
def descends(pid, root) -> bool:
    """True if process `pid` is `root` or one of its descendants (walks /proc ppid links)."""
    try:
        pid, root = int(pid), int(root)
    except (TypeError, ValueError):
        return False
    for _ in range(64):
        if pid == root:
            return True
        if pid <= 1:
            return False
        try:
            with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return False
    return False


def desktop_pid_file() -> str:
    """Where stickllm-sway-session records the desktop Chromium pid."""
    return os.environ.get("STICKLLM_DESKTOP_PIDFILE") or os.path.join(
        os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "stickllm-desktop.pid")


def read_desktop_pid(path: str | None = None):
    try:
        with open(path or desktop_pid_file(), encoding="ascii") as f:
            v = int(f.read().strip())
        return v if v > 1 else None
    except (OSError, ValueError):
        return None


def desktop_rules(tree: dict, desktop_pid=None, is_child=descends) -> list[str]:
    """Keep exactly one tiled, borderless desktop window; float any extra ones.

    The desktop is a Chromium --app window, whose Wayland app_id comes from the
    URL (it ignores --class), so it is recognised by its process: the pid that
    stickllm-sway-session launched (or a child of it). The legacy
    stickllm-desktop app_id is still accepted.
    """
    cmds = []
    have = [w for w in iter_windows(tree) if DESKTOP_MARK in (w.get("marks") or [])]
    for w in iter_windows(tree):
        if DESKTOP_MARK in (w.get("marks") or []):
            continue
        mine = w.get("app_id") == DESKTOP_APP_ID or (
            desktop_pid is not None and w.get("pid") and is_child(w.get("pid"), desktop_pid))
        if not mine:
            continue
        if not have and not w.get("minimised"):
            cmds.append(f"[con_id={int(w['id'])}] floating disable, border none, mark --add {DESKTOP_MARK}")
            have.append(w)
        else:
            cmds.append(f"[con_id={int(w['id'])}] floating enable, border normal 2")
    return cmds


def watch(sock_path: str) -> None:
    """Block on window events and apply desktop_rules after each one."""
    with SwayIPC(sock_path) as ipc:
        run_plan(ipc, desktop_rules(ipc.tree(), read_desktop_pid()))
        ev = SwayIPC(sock_path, timeout=None)
        try:
            ev.sock.sendall(pack(SUBSCRIBE, json.dumps(["window"])))
            ev.read()
            while True:
                msg_type, body = ev.read()
                if msg_type & EVENT_BIT and isinstance(body, dict) and body.get("change") in ("new", "move", "floating", "title"):
                    run_plan(ipc, desktop_rules(ipc.tree(), read_desktop_pid()))
        finally:
            ev.close()


def main(argv: list[str]) -> int:
    """CLI for sway keybindings and the session: minimise|maximise|close-focused, watch, exit."""
    if len(argv) < 2:
        print("usage: stickllm-wm minimise-focused|maximise-focused|close-focused|watch|exit|state")
        return 2
    try:
        path = find_socket()
        if argv[1] == "watch":
            watch(path)
            return 0
        with SwayIPC(path) as ipc:
            if argv[1] == "exit":
                return 0 if command_ok(ipc.command("exit")) else 1
            if argv[1] == "state":
                work = work_area(ipc.outputs())
                print(json.dumps([dict(window_state(w, work), bid=bid_of(w), desktop=is_desktop(w))
                                  for w in iter_windows(ipc.tree())], indent=1))
                return 0
            op = {"minimise-focused": "minimise", "maximise-focused": "maximise",
                  "close-focused": "close"}.get(argv[1])
            if not op:
                return 2
            w = focused(ipc.tree())
            if not w or is_desktop(w):
                return 0  # shortcuts never touch the desktop itself
            apply(ipc, op, con_id=w["id"])
            return 0
    except (WMError, OSError) as e:
        print(f"stickllm-wm: {e}")
        return 1
