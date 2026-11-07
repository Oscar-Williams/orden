from __future__ import annotations

import argparse
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
import urllib.parse
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

drive = importlib.import_module("web-tab-drive")

PAGES = {
    "plain": "<!doctype html><title>plain</title><p>plain",
    "alert": "<!doctype html><title>alert</title><script>setTimeout(() => alert('hello'), 200)</script><p>alert",
    "confirm": "<!doctype html><title>confirm</title><script>setTimeout(() => confirm('sure?'), 200)</script><p>confirm",
    "leave": "<!doctype html><title>leave</title><script>addEventListener('beforeunload', (e) => { e.preventDefault(); e.returnValue = '' })</script><input autofocus value=typed><p>leave",
    "inner": "<!doctype html><title>inner</title><script>setTimeout(() => alert('inner'), 150)</script>",
    "frames": "<!doctype html><title>frames</title><script>setTimeout(() => alert('top'), 300)</script>" + "".join(f"<iframe src='/inner?{i}'></iframe>" for i in range(3)),
    "twice": "<!doctype html><title>twice</title><script>setTimeout(() => alert('one'), 200); setTimeout(() => alert('two'), 210)</script>",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 - the standard library's name
        name = urllib.parse.urlparse(self.path).path.strip("/") or "plain"
        body = PAGES.get(name, PAGES["plain"]).encode()
        try:
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass


SCENES = [
    ("alert then close", "alert", "close"),
    ("alert then go", "alert", "go"),
    ("alert then reload", "alert", "reload"),
    ("confirm then close", "confirm", "close"),
    ("frames then close", "frames", "close"),
    ("frames then go", "frames", "go"),
    ("twice then close", "twice", "close"),
    ("leave then close", "leave", "close"),
    ("leave then go", "leave", "go"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--rounds", type=int, default=8)
    args = parser.parse_args()

    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{site.server_address[1]}"
    config = drive.config_of(args.identifier)
    shutil.rmtree(config, ignore_errors=True)
    config.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    (config / "automation.json").write_text(json.dumps({"port": 0, "secret": secret, "eval": True}), encoding="utf-8")
    spaces = pathlib.Path(tempfile.mkdtemp(prefix="nib-dialog-spaces-"))
    process = subprocess.Popen([str(args.exe)], env={**os.environ, "NIB_SPACES_DIR": str(spaces)}, cwd=str(args.exe.parent))
    reports = config / "web" / "EBWebView" / "Crashpad" / "reports"
    log = pathlib.Path(os.environ.get("LOCALAPPDATA") or ".").joinpath(args.identifier)

    def crashes() -> int:
        count = 0
        for one in log.glob("**/nib.log"):
            count += one.read_text(encoding="utf-8", errors="replace").count("exit 0xc0000005")
        return count

    def dumps() -> int:
        return len(list(reports.glob("*.dmp")))

    found: dict[str, list[int]] = {}
    try:
        app = drive.endpoint(config, process.pid, secret)
        until = time.monotonic() + 90
        while time.monotonic() < until and app.eval("!!nib.workspace").get("value") is not True:
            time.sleep(1)
        time.sleep(2)
        app.eval("nib.workspace.openBlank('One', '# One'); return true", 20)
        for name, page, then in SCENES:
            before = (crashes(), dumps())
            for round in range(args.rounds):
                url = json.dumps(f"{origin}/{page}?{name.replace(' ', '-')}-{round}")
                tab = app.eval(f"return nib.workspace.openPage({url}, 'front')", 20).get("value")
                time.sleep(1.2)
                t = json.dumps(tab)
                if then == "close":
                    app.eval(f"nib.workspace.close({t}); return true", 20)
                elif then == "go":
                    app.eval(f"nib.pages.go({t}, {json.dumps(origin + '/plain?after')}); return true", 20)
                    time.sleep(1)
                    app.eval(f"nib.workspace.close({t}); return true", 20)
                else:
                    app.eval(f"nib.pages.step({t}, 'reload'); return true", 20)
                    time.sleep(1)
                    app.eval(f"nib.workspace.close({t}); return true", 20)
                time.sleep(0.8)
                if process.poll() is not None:
                    print(f"the app exited with {process.returncode & 0xFFFFFFFF:#x} in {name}", flush=True)
                    return 1
            time.sleep(2)
            after = (crashes(), dumps())
            found[name] = [after[0] - before[0], after[1] - before[1]]
            print(f"scene| {name}: browser crashes {after[0] - before[0]}, engine dumps {after[1] - before[1]}", flush=True)
    finally:
        process.kill()
        process.wait(20)
        site.shutdown()
        shutil.rmtree(spaces, ignore_errors=True)
    print(f"found {found}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
