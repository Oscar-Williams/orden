from __future__ import annotations

import argparse
import ctypes
import http.server
import importlib
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

drive = importlib.import_module("web-tab-drive")
probe = importlib.import_module("probe_app")

user32 = ctypes.WinDLL("user32", use_last_error=True)
GW_OWNER = 4
GWL_STYLE = -16
GWL_EXSTYLE = -20
user32.GetWindowLongW.restype = ctypes.c_long


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 - the standard library's name
        body = f"<!doctype html><title>{self.path}</title><p>{self.path}".encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


started = time.perf_counter()
mark = ["launch", started]
seen: dict[int, str] = {}
told: list[str] = []


dwm = ctypes.WinDLL("dwmapi")
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.c_size_t
user32.GetAncestor.restype = ctypes.c_size_t
user32.GetAncestor.argtypes = [ctypes.c_size_t, ctypes.c_uint]
baseline: list[Any] = []


def differs(box: tuple[int, int, int, int]) -> str:
    try:
        from PIL import ImageChops, ImageGrab
    except ImportError:
        return "no PIL"
    if not baseline:
        return "no baseline"
    left, top, right, bottom = box
    if right <= 0 or bottom <= 0 or left < 0 or top < 0:
        return "off screen"
    now = ImageGrab.grab(bbox=box, all_screens=True)
    was = baseline[0].crop(box)
    diff = ImageChops.difference(now.convert("RGB"), was.convert("RGB")).getbbox()
    return f"{diff}"


def watch(pid: int, stop: threading.Event) -> None:
    probe.in_physical_pixels()
    family = {pid}
    asked = 0.0
    while not stop.is_set():
        now = time.perf_counter()
        if now - asked > 0.5:
            family = probe.descendants(pid, probe.parents(), probe.born) | {pid}
            asked = now
        here: set[int] = set()
        for one in probe.look(family).windows:
            if not one.visible:
                continue
            style = user32.GetWindowLongW(one.hwnd, GWL_STYLE) & 0xFFFFFFFF
            if style & 0x40000000:
                continue
            here.add(one.hwnd)
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(one.hwnd, title, 256)
            ex = user32.GetWindowLongW(one.hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
            owner = user32.GetWindow(one.hwnd, GW_OWNER) or 0
            what = f"0x{one.hwnd:X} {one.kind} {title.value!r} {one.box} style {style:#x} ex {ex:#x} owner 0x{owner:X} {probe.image_of(one.pid)}"
            if seen.get(one.hwnd, "").split(" | ")[0] == what:
                continue
            if "msedgewebview2" in what.lower():
                x, y = (one.box[0] + one.box[2]) // 2, (one.box[1] + one.box[3]) // 2
                hit = user32.WindowFromPoint(wintypes.POINT(x, y)) or 0
                root = user32.GetAncestor(hit, 2) if hit else 0
                cloaked = ctypes.c_int(0)
                dwm.DwmGetWindowAttribute(wintypes.HWND(one.hwnd), 14, ctypes.byref(cloaked), 4)
                key, alpha, flags = wintypes.DWORD(), ctypes.c_ubyte(), wintypes.DWORD()
                layered = user32.GetLayeredWindowAttributes(wintypes.HWND(one.hwnd), ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags))
                drawn = differs(one.box)
                what += f" | point ({x},{y}) hits 0x{hit:X} root 0x{root:X} {'ITSELF' if root == one.hwnd or hit == one.hwnd else 'not it'}, cloaked {cloaked.value}, layered attrs {bool(layered)} alpha {alpha.value} flags {flags.value}, pixels changed {drawn}"
            if True:
                seen[one.hwnd] = what
                line = f"{(now - mark[1]) * 1000:7.0f} ms after {mark[0]}: shown {what}"
                told.append(line)
                print(f"win| {line}", flush=True)
        for gone in [one for one in seen if one not in here]:
            line = f"{(now - mark[1]) * 1000:7.0f} ms after {mark[0]}: hidden {seen.pop(gone)}"
            told.append(line)
            print(f"win| {line}", flush=True)
        time.sleep(0.02)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--off", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args()

    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{site.server_address[1]}"

    config = drive.config_of(args.identifier)
    shutil.rmtree(config, ignore_errors=True)
    config.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    (config / "automation.json").write_text(json.dumps({"port": 0, "secret": secret, "eval": True}), encoding="utf-8")
    spaces = pathlib.Path(tempfile.mkdtemp(prefix="nib-stray-spaces-"))
    env = {**os.environ, "NIB_SPACES_DIR": str(spaces)}
    if args.off:
        env["NIB_OFF_SCREEN"] = "1"
    if args.windowed:
        env["NIB_PAGES_WINDOWED"] = "1"
    process = subprocess.Popen([str(args.exe)], env=env, cwd=str(args.exe.parent))
    stop = threading.Event()
    threading.Thread(target=watch, args=(process.pid, stop), daemon=True).start()

    def act(name: str, run: Any) -> None:
        mark[0], mark[1] = name, time.perf_counter()
        print(f"act| {name} at {(mark[1] - started) * 1000:.0f} ms", flush=True)
        run()
        time.sleep(6)

    def hand(url: str) -> None:
        second = subprocess.Popen([str(args.exe), "--url", url], env=env, cwd=str(args.exe.parent))
        second.wait(30)

    try:
        app = drive.endpoint(config, process.pid, secret)
        until = time.monotonic() + 90
        while time.monotonic() < until and app.eval("!!nib.workspace").get("value") is not True:
            time.sleep(1)
        time.sleep(4)
        try:
            from PIL import ImageGrab
            baseline.append(ImageGrab.grab(all_screens=True))
        except ImportError:
            pass
        act("a note", lambda: app.eval("nib.workspace.openBlank('One', '# One\\n\\nSome words.'); return true", 20))
        act("--url first", lambda: hand(f"{origin}/first"))
        act("openPage second", lambda: app.eval(f"nib.workspace.openPage({json.dumps(origin + '/second')}, 'front'); return true", 20))
        act("--url third", lambda: hand(f"{origin}/third"))
        act("--url with a path", lambda: hand(f"{origin}/fourth C:\\Idea.md"))
        act("activate the note", lambda: app.eval("const t = nib.workspace.tabs.find((t) => t.kind !== 'web'); if (t) nib.workspace.activate(t.id); return true", 20))
        act("close every web tab", lambda: app.eval("for (const t of nib.workspace.tabs.filter((t) => t.kind === 'web')) nib.workspace.close(t.id); return true", 20))
        act("--url after none", lambda: hand(f"{origin}/fifth"))
        said = app.eval("return nib.workspace.tabs.map((t) => t.kind + ':' + (t.address ?? t.name))", 20)
        print(f"tabs| {said.get('value')}", flush=True)
    finally:
        stop.set()
        process.kill()
        process.wait(20)
        site.shutdown()
        for log in pathlib.Path(os.environ.get("LOCALAPPDATA") or ".").joinpath(args.identifier).glob("**/nib.log"):
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]:
                print(f"log| {line}", flush=True)
        shutil.rmtree(spaces, ignore_errors=True)

    stray = [one for one in told if "msedgewebview2" in one.lower() and " shown " in one]
    print(f"stray windows: {len(stray)}", flush=True)
    for one in stray:
        print(f"::warning::{one}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
