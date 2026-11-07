from __future__ import annotations

import argparse
import ctypes
import http.server
import json
import pathlib
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import importlib

drive = importlib.import_module("web-tab-drive")
from probe_app import main_window, sized

PAGES = {
    "plain": "<!doctype html><title>plain</title><p>a page",
    "dark": "<!doctype html><title>dark</title><meta name=color-scheme content='light dark'><style>body{background:Canvas;color:CanvasText}</style><p>follows the scheme",
    "big": "<!doctype html><title>big</title><script>for (let i = 0; i < 20000; i++) document.body.append(Object.assign(document.createElement('div'), { textContent: 'row ' + i }))</script>",
    "busy": "<!doctype html><title>busy</title><script>setInterval(() => { const end = Date.now() + 120; while (Date.now() < end) {} }, 200)</script><p>busy",
    "frames": "<!doctype html><title>frames</title>" + "".join(f"<iframe src='/plain?f{i}'></iframe>" for i in range(6)),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        name = self.path.split("?")[0].strip("/") or "plain"
        body = PAGES.get(name, PAGES["plain"]).encode()
        try:
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass


user32 = ctypes.WinDLL("user32", use_last_error=True)

VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "esc": 0x1B, "f11": 0x7A, "comma": 0xBC, "plus": 0xBB, "minus": 0xBD, "0": 0x30, "o": 0x4F, "p": 0x50, "k": 0x4B, "b": 0x42, "t": 0x54, "w": 0x57, "tab": 0x09}


def keys(*names: str) -> None:
    codes = [VK[one] for one in names]
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 2, 0)


PANES = ["general", "editor", "appearance", "markdown", "spelling", "kinds", "shortcuts"]

CLICK = """
const PANES = %s
const SKIP = /sign|delete|remove|reset|quit|restart|install|export|import|clear|forget|leave|uninstall|update|choose|browse|pick|folder|file|open|add|copy|report|send|record|download|connect|pair|check|learn|help|web|site|privacy|terms|github|feedback/i
const pane = PANES[Math.floor(Math.random() * PANES.length)]
if (!nib.settings.open || Math.random() < 0.2) nib.settings.show(pane)
await new Promise((done) => setTimeout(done, 20))
const sheet = document.querySelector('[role=dialog][aria-modal=true]') ?? document.body
const list = [...document.querySelectorAll('[role=listbox], [role=menu]')].find((one) => one.checkVisibility())
const scope = list ?? sheet
const all = [...scope.querySelectorAll('button, [role=switch], [role=radio], [role=option], [role=menuitem], [role=menuitemradio], input[type=checkbox], input[type=range]')]
  .filter((one) => one.checkVisibility() && !one.disabled && !one.closest('a[href]') && !SKIP.test(`${one.textContent ?? ''} ${one.getAttribute('aria-label') ?? ''} ${one.title ?? ''}`))
const one = all[Math.floor(Math.random() * all.length)]
if (!one) return `${pane}: nothing`
const said = (one.getAttribute('aria-label') || one.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40)
if (one.type === 'range') {
  const low = Number(one.min || 0), high = Number(one.max || 100)
  one.value = String(low + Math.random() * (high - low))
  one.dispatchEvent(new Event('input', { bubbles: true }))
  one.dispatchEvent(new Event('change', { bubbles: true }))
} else one.click()
return `${pane}: ${said}`
""" % json.dumps(PANES)

LANGUAGE = """
nib.settings.show('general')
await new Promise((done) => setTimeout(done, 60))
const sheet = document.querySelector('[role=dialog][aria-modal=true]')
const pickers = [...(sheet ?? document).querySelectorAll('button[aria-haspopup], select')].filter((one) => one.checkVisibility())
const picker = pickers.find((one) => /English|Deutsch|Español|Français|日本語|العربية|Language|Sprache|Match the system/i.test(`${one.textContent} ${one.getAttribute('aria-label') ?? ''} ${one.closest('label, .row, [data-row]')?.textContent ?? ''}`))
if (!picker) return 'no language picker'
if (picker.tagName === 'SELECT') {
  const options = [...picker.options]
  picker.value = options[Math.floor(Math.random() * options.length)].value
  picker.dispatchEvent(new Event('change', { bubbles: true }))
  return `select ${picker.value}`
}
picker.click()
await new Promise((done) => setTimeout(done, 60))
const options = [...document.querySelectorAll('[role=option]')].filter((one) => one.checkVisibility())
const wanted = Math.random() < 0.35 ? options.find((one) => /English/.test(one.textContent)) : options[Math.floor(Math.random() * options.length)]
if (!wanted) return 'no options'
wanted.click()
return `language ${wanted.textContent.trim().slice(0, 30)}`
"""


def acts(origin: str) -> list[tuple[str, Any]]:
    def ev(code: str):
        return lambda app, hwnd, rng: app.eval(code, 15)

    def click(app, hwnd, rng):
        return app.eval(CLICK, 15)

    def language(app, hwnd, rng):
        return app.eval(LANGUAGE, 15)

    def burst(app, hwnd, rng):
        out = None
        for _ in range(rng.choice([5, 15, 30])):
            out = app.eval(CLICK, 15)
            if "error" in out:
                return out
        return out

    def size(app, hwnd, rng):
        sized(hwnd, rng.choice([360, 420, 460, 520, 700, 1000, 1400, 1800]), rng.choice([400, 600, 900, 1050]))
        return {}

    def show(app, hwnd, rng):
        state = rng.choice([3, 9, 6, 9])
        user32.ShowWindow(hwnd, state)
        if state == 6:
            time.sleep(rng.choice([0.05, 0.4]))
            user32.ShowWindow(hwnd, 9)
        return {}

    def press(*names: str):
        def go(app, hwnd, rng):
            drive.forward(app_pid[0])
            keys(*names)
            return {}

        return go

    page = lambda name: json.dumps(f"{origin}/{name}?{random.random()}")
    return [
        ("settings click", click),
        ("settings click", click),
        ("settings click", click),
        ("settings burst", burst),
        ("language", language),
        ("settings open", ev("nib.settings.show(%s); return true" % json.dumps(random.choice(PANES)))),
        ("settings shut", ev("nib.settings.open = false; return true")),
        ("panel", ev("nib.workspace.showPanel(['tree', 'outline', 'search', 'tasks', 'links'][Math.floor(Math.random() * 5)]); return true")),
        ("panel shut", ev("nib.workspace.closePanel(Math.random() < 0.5 ? 'left' : 'right'); return true")),
        ("web page", ev("nib.workspace.openPage(%s, Math.random() < 0.5 ? 'front' : 'behind'); return true" % page(random.choice(list(PAGES))))),
        ("activate", ev("const ts = nib.workspace.tabs; const t = ts[Math.floor(Math.random() * ts.length)]; if (t) nib.workspace.activate(t.id); return true")),
        ("split", ev("if (nib.workspace.panes.all.length < 3) nib.workspace.split(Math.random() < 0.5 ? 'row' : 'column'); return true")),
        ("close pane", ev("if (nib.workspace.panes.all.length > 1) nib.workspace.closePane(); return true")),
        ("size", size),
        ("show", show),
        ("escape", press("esc")),
        ("palette", press("ctrl", "shift", "p")),
        ("settings key", press("ctrl", "comma")),
        ("zoom in", press("ctrl", "plus")),
        ("zoom out", press("ctrl", "minus")),
        ("zoom reset", press("ctrl", "0")),
        ("full screen", press("f11")),
        ("overview", press("alt")),
        ("sidebar key", press("ctrl", "b")),
    ]


app_pid = [0]


def dialogs(pid: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    kind = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    front = user32.GetForegroundWindow()

    def each(hwnd: int, _: int) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value != pid:
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), name, 64)
        if name.value != "#32770":
            return True
        box = (ctypes.c_long * 4)()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), box)
        found.append({"hwnd": hwnd, "visible": bool(user32.IsWindowVisible(ctypes.c_void_p(hwnd))), "front": hwnd == front, "box": list(box)})
        return True

    user32.EnumWindows(kind(each), 0)
    return found


def shut_dialogs(pid: int) -> list[dict[str, Any]]:
    up = dialogs(pid)
    for one in up:
        user32.PostMessageW(ctypes.c_void_p(one["hwnd"]), 0x0010, 0, 0)
    if up:
        time.sleep(1.5)
    return up


def page_stack() -> None:
    try:
        from devtools import Session, targets
        found = targets(9333)
    except Exception as error:  # noqa: BLE001
        print(f"cdp| no targets: {error}", flush=True)
        return
    for one in found:
        print(f"cdp| target {one.get('type')} {one.get('url', '')[:120]}", flush=True)
    for one in found:
        if one.get("type") != "page" or "tauri.localhost" not in one.get("url", ""):
            continue
        try:
            page = Session(one)
            print(f"cdp| evaluate: {page.call('Runtime.evaluate', {'expression': '1 + 1', 'returnByValue': True}, 4)}", flush=True)
            print(f"cdp| enable: {str(page.call('Debugger.enable', {}, 6))[:200]}", flush=True)
            print(f"cdp| pause: {page.call('Debugger.pause', {}, 6)}", flush=True)
            page.listen(6)
            for event in page.events:
                if event.get("method") != "Debugger.paused":
                    continue
                for frame in event["params"].get("callFrames", [])[:40]:
                    at = frame.get("location", {})
                    print(f"cdp| at {frame.get('functionName') or '(anon)'} {frame.get('url', '').split('/')[-1]}:{at.get('lineNumber', 0) + 1}:{at.get('columnNumber', 0) + 1}", flush=True)
                for frame in event["params"].get("asyncStackTrace", {}).get("callFrames", [])[:20]:
                    print(f"cdp| async {frame.get('functionName') or '(anon)'} {frame.get('url', '').split('/')[-1]}:{frame.get('lineNumber', 0) + 1}:{frame.get('columnNumber', 0) + 1}", flush=True)
            print(f"cdp| events {[one.get('method') for one in page.events][:30]}", flush=True)
            page.call("Debugger.resume", {}, 4)
        except Exception as error:  # noqa: BLE001
            print(f"cdp| failed: {error}", flush=True)


def stacks(exe: pathlib.Path, pid: int) -> None:
    kits = pathlib.Path(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe")
    if not kits.exists():
        print("no cdb to read the stacks with", flush=True)
        return
    symbols = f"srv*{tempfile.gettempdir()}\\sym*https://msdl.microsoft.com/download/symbols;{exe.parent}"
    told = subprocess.run([str(kits), "-pv", "-p", str(pid), "-y", symbols, "-c", ".reload; ~*kc 40; qd"], capture_output=True, text=True, timeout=600, check=False)
    for line in told.stdout.splitlines():
        if line.strip() and not line.startswith(("Symbol search", "Microsoft (R)", "Copyright", "CommandLine")):
            print(f"stack| {line}", flush=True)


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if "probe" not in args.identifier:
        raise SystemExit(f"{args.identifier} is not a probe identifier")

    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{site.server_address[1]}"

    config = drive.config_of(args.identifier)
    for _ in range(20):
        shutil.rmtree(config, ignore_errors=True)
        if not config.exists():
            break
        time.sleep(1)
    config.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    (config / "automation.json").write_text(json.dumps({"port": 0, "secret": secret, "eval": True}), encoding="utf-8")
    spaces = pathlib.Path(tempfile.mkdtemp(prefix="nib-ui-freeze-"))
    (spaces / "UI fuzz").mkdir()
    (spaces / "UI fuzz" / "A note.md").write_text("# A note\n\nSome words, a [[link]] and a #tag.\n", encoding="utf-8")
    process = subprocess.Popen([str(args.exe)], env={**drive.os.environ, "NIB_SPACES_DIR": str(spaces)}, cwd=str(args.exe.parent))
    app_pid[0] = process.pid
    rng = random.Random(args.seed)
    random.seed(args.seed)
    trail: list[str] = []
    wrong: list[str] = []
    slow: list[str] = []
    try:
        app = drive.endpoint(config, process.pid, secret)
        until = time.monotonic() + 90
        while time.monotonic() < until and app.eval("!!nib.workspace").get("value") is not True:
            time.sleep(1)
        time.sleep(2)
        hwnd = main_window(process.pid)
        app.eval("nib.workspace.openBlank('One', '# One\\n\\nSome words.'); return true", 20)
        for name in ("plain", "dark", "busy"):
            app.eval(f"nib.workspace.openPage({json.dumps(origin + '/' + name)}, 'behind'); return true", 20)
        drive.forward(process.pid)
        table = acts(origin)
        ends = time.monotonic() + args.minutes * 60
        step = 0
        while time.monotonic() < ends:
            step += 1
            name, act = rng.choice(table)
            asked = time.monotonic()
            said = act(app, hwnd, rng) or {}
            took = time.monotonic() - asked
            trail.append(f"{step} {name} {str(said.get('value', said.get('error', '')))[:50]}")
            if "error" in said and "timed out" in str(said["error"]).lower() and (up := shut_dialogs(process.pid)):
                print(f"step {step} {name}: a native dialog was up: {up}", flush=True)
                if not all(one["visible"] and one["front"] for one in up):
                    wrong.append(f"step {step} ({name}): a native dialog was up but not in front: {up}")
                said = app.eval("return 1", 15)
            if "error" in said and ("timed out" in str(said["error"]).lower() or "refused" in str(said["error"]).lower()):
                wrong.append(f"step {step} ({name}): the endpoint did not answer: {said['error']}")
            elif took > 3:
                slow.append(f"step {step} {name} took {took:.1f} s")
                print(f"slow: step {step} {name} took {took:.1f} s", flush=True)
            if why := drive.window_answers(process.pid):
                wrong.append(f"step {step} ({name}): {why}")
            if not wrong and step % 5 == 0:
                began = time.monotonic()
                said = app.eval("return nib.workspace.tabs.length", 15)
                if "error" in said:
                    wrong.append(f"step {step}: the app stopped answering a plain question: {said['error']}")
                elif time.monotonic() - began > 3:
                    slow.append(f"step {step}: a plain question took {time.monotonic() - began:.1f} s")
            if wrong:
                page_stack()
                stacks(args.exe, process.pid)
                time.sleep(20)
                late = app.eval("return nib.workspace.tabs.length", 15)
                answers = drive.window_answers(process.pid)
                wrong.append(f"20 s later: endpoint {late}, window {answers or 'answers'}")
                break
            if process.poll() is not None:
                wrong.append(f"step {step} ({name}): the app exited with {process.returncode}")
                break
            time.sleep(rng.choice([0, 0, 0.05, 0.3]))
        print(f"{step} steps, {len(slow)} slow", flush=True)
    finally:
        try:
            process.kill()
            process.wait(20)
        except Exception:  # noqa: BLE001
            pass
        subprocess.run(["taskkill", "/F", "/T", "/IM", "msedgewebview2.exe"], capture_output=True, check=False)
        time.sleep(3)
        if wrong:
            print("last steps: " + " | ".join(trail[-80:]), flush=True)
        site.shutdown()
        for line in drive.stalls(args.identifier):
            print(line, flush=True)
        shutil.rmtree(spaces, ignore_errors=True)

    for one in wrong:
        print(f"::error::{one}", flush=True)
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
