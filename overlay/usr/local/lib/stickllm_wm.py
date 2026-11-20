"""StickLLM window helper for the Xfce desktop on Xorg (MIT, (c) Nink Inc.).

0.5.7: the on-stick desktop is Xfce only (sway, cage and weston are gone).
This module moves, sizes, minimises, restores, maximises and focuses the
Browser windows that stickllm-control starts, using the stock X11 command
line tools wmctrl, xdotool and xprop (Debian packages, unmodified, run as
separate programs). Windows are found by their WM_CLASS
(--class=stickllm-browser-<id>) or by the owning process.

Same interface as the 0.5.6 sway helper: X11(), wait_for, apply, states.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

TASKBAR_PX = 48
OPS = ("place", "minimise", "restore", "maximise", "focus", "toggle", "close", "state")


class WMError(Exception):
    pass


def _drop_to(user: str) -> list:
    """0.5.9: argv prefix that runs a command as `user`. Absolute paths: the
    0.5.8 X11 helper ran with PATH=/usr/local/bin:/usr/bin:/bin, so a bare
    "runuser" (/usr/sbin) raised "[Errno 2] No such file or directory".
    Falls back to setpriv (util-linux, /usr/bin)."""
    for p in ("/usr/sbin/runuser", "/sbin/runuser"):
        if os.access(p, os.X_OK):
            return [p, "-u", user, "--"]
    for p in ("/usr/bin/setpriv", "/bin/setpriv"):
        if os.access(p, os.X_OK):
            try:
                import pwd
                pw = pwd.getpwnam(user)
            except KeyError:
                break
            return [p, f"--reuid={pw.pw_uid}", f"--regid={pw.pw_gid}", "--init-groups", "--"]
    raise OSError(2, "no runuser/setpriv to drop privileges")


class X11:
    """Runs the X11 tools against the kiosk display (DISPLAY=:0)."""

    def __init__(self, display: str = ":0", user: str | None = None):
        if not os.path.exists("/tmp/.X11-unix/X" + display.lstrip(":")):
            raise WMError("the desktop (Xorg) is not running")
        self.display = display
        self.user = user

    def run(self, *args: str, timeout: float = 5.0) -> str:
        cmd = list(args)
        if self.user and os.geteuid() == 0 and self.user != "root":
            try:
                cmd = _drop_to(self.user) + cmd
            except OSError as e:
                raise WMError(str(e)) from e
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "DISPLAY": self.display}
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise WMError(str(e)) from e
        return r.stdout if r.returncode == 0 else ""

    def close(self) -> None:
        pass


def find_socket(_dirs=None):  # 0.5.6 interface; X11 has no socket to find
    return ":0"


def windows(x: X11) -> list[dict]:
    """[{id, pid, cls, title, x, y, w, h}] from wmctrl -lpGx."""
    out = []
    for line in x.run("wmctrl", "-lpGx").splitlines():
        p = line.split(None, 8)
        if len(p) < 8:
            continue
        try:
            out.append({"id": int(p[0], 16), "pid": int(p[2]), "x": int(p[3]), "y": int(p[4]),
                        "w": int(p[5]), "h": int(p[6]), "cls": p[7].lower(),
                        "title": p[8].split(None, 1)[1] if len(p) > 8 and " " in p[8] else ""})
        except ValueError:
            continue
    return out


def screen(x: X11) -> tuple[int, int]:
    m = re.match(r"\s*(\d+)\s+(\d+)", x.run("xdotool", "getdisplaygeometry"))
    return (int(m.group(1)), int(m.group(2))) if m else (1920, 1080)


def work_area(x: X11, taskbar_px: int = TASKBAR_PX) -> dict:
    sw, sh_ = screen(x)
    return {"x": 0, "y": 0, "w": sw, "h": max(200, sh_ - int(taskbar_px))}


def net_state(x: X11, wid: int) -> str:
    return x.run("xprop", "-id", hex(wid), "_NET_WM_STATE")


def active(x: X11) -> int:
    m = re.search(r"0x[0-9a-fA-F]+", x.run("xprop", "-root", "_NET_ACTIVE_WINDOW"))
    return int(m.group(0), 16) if m else 0


def bid_of(w: dict) -> str:
    m = re.search(r"stickllm-browser-([0-9a-f]{12})", w.get("cls", ""))
    return m.group(1) if m else ""


def window_state(x: X11, w: dict, work: dict, act: int | None = None) -> dict:
    st = net_state(x, w["id"])
    mini = "_NET_WM_STATE_HIDDEN" in st
    rect = {"x": w["x"], "y": w["y"], "w": w["w"], "h": w["h"]}
    maxed = (not mini) and abs(w["w"] - work["w"]) <= 24 and abs(w["h"] - work["h"]) <= 48 and w["x"] <= 8
    act = active(x) if act is None else act
    return {"title": w.get("title", ""), "minimised": mini, "focused": (not mini) and act == w["id"],
            "maximised": maxed, "rect": rect}


def wait_for(x: X11, bid: str, owns=None, timeout: float = 20.0) -> dict | None:
    end = time.monotonic() + timeout
    while True:
        for w in windows(x):
            if bid_of(w) == bid or (owns is not None and w["pid"] and owns(w["pid"])):
                return w
        if time.monotonic() >= end:
            return None
        time.sleep(0.25)


def _clamp(g: dict, work: dict) -> dict:
    w = max(320, min(int(g["w"]), work["w"]))
    h = max(200, min(int(g["h"]), work["h"]))
    return {"x": max(0, min(int(g["x"]), work["w"] - w)), "y": max(0, min(int(g["y"]), work["h"] - h)), "w": w, "h": h}


def _move(x: X11, wid: int, g: dict) -> None:
    x.run("wmctrl", "-i", "-r", hex(wid), "-b", "remove,maximized_vert,maximized_horz")
    x.run("wmctrl", "-i", "-r", hex(wid), "-e", f"0,{g['x']},{g['y']},{g['w']},{g['h']}")


_SAVED: dict[int, dict] = {}


def apply(x: X11, op: str, *, con_id=None, geo=None, taskbar_px: int = TASKBAR_PX, **_kw) -> dict:
    if op not in OPS:
        raise WMError("bad op")
    w = next((v for v in windows(x) if v["id"] == con_id), None)
    if not w:
        raise WMError("window not found")
    work = work_area(x, taskbar_px)
    st = window_state(x, w, work)
    wid = hex(w["id"])
    if op == "toggle":
        op = "restore" if st["minimised"] else ("minimise" if st["focused"] else "focus")
    if op == "place":
        if not geo:
            raise WMError("geometry required")
        _move(x, w["id"], _clamp(geo, work))
        x.run("wmctrl", "-i", "-a", wid)
    elif op == "minimise":
        if not st["minimised"]:
            x.run("xdotool", "windowminimize", str(w["id"]))
    elif op in ("restore", "focus"):
        x.run("wmctrl", "-i", "-a", wid)
    elif op == "maximise":
        if st["maximised"]:
            g = _SAVED.pop(w["id"], None) or {"x": work["w"] // 8, "y": work["h"] // 8,
                                                "w": work["w"] * 3 // 4, "h": work["h"] * 3 // 4}
            _move(x, w["id"], _clamp(g, work))
        else:
            _SAVED[w["id"]] = st["rect"]
            _move(x, w["id"], work)
        x.run("wmctrl", "-i", "-a", wid)
    elif op == "close":
        x.run("wmctrl", "-i", "-c", wid)
    time.sleep(0.15)
    w2 = next((v for v in windows(x) if v["id"] == w["id"]), w)
    return {"ok": True, "window": window_state(x, w2, work)}


def states(x: X11, taskbar_px: int = TASKBAR_PX) -> dict:
    work = work_area(x, taskbar_px)
    act = active(x)
    out = {}
    for w in windows(x):
        b = bid_of(w)
        if b and b not in out:
            out[b] = window_state(x, w, work, act)
    return out
