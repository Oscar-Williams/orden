from __future__ import annotations

import argparse
import http.server
import importlib
import json
import pathlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

fuzz = importlib.import_module("freeze-fuzz")
drive = fuzz.drive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--first", default="busy")
    parser.add_argument("--then", type=int, default=12)
    parser.add_argument("--args", default="")
    args = parser.parse_args()
    fuzz.args_exe = args.exe

    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), fuzz.Handler)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{site.server_address[1]}"

    config = drive.config_of(args.identifier)
    shutil.rmtree(config, ignore_errors=True)
    config.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    (config / "automation.json").write_text(json.dumps({"port": 0, "secret": secret, "eval": True}), encoding="utf-8")
    spaces = pathlib.Path(tempfile.mkdtemp(prefix="nib-busy-spaces-"))
    env = {**drive.os.environ, "NIB_SPACES_DIR": str(spaces)}
    if args.args:
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = args.args
    process = subprocess.Popen([str(args.exe)], env=env, cwd=str(args.exe.parent))
    wrong: list[str] = []
    try:
        app = drive.endpoint(config, process.pid, secret)
        until = time.monotonic() + 90
        while time.monotonic() < until and app.eval("!!nib.workspace").get("value") is not True:
            time.sleep(1)
        time.sleep(2)
        app.eval("nib.workspace.openBlank('One', '# One\\n\\nSome words.'); return true", 20)
        drive.forward(process.pid)
        for name in args.first.split(","):
            app.eval(f"nib.workspace.openPage({json.dumps(f'{origin}/{name}?first')}, 'front'); return true", 20)
            time.sleep(3)
        print(f"after {args.first}: {fuzz.census(process.pid)}", flush=True)
        for count in range(1, args.then + 1):
            asked = time.monotonic()
            said = app.eval(f"nib.workspace.openPage({json.dumps(f'{origin}/plain?{count}')}, 'front'); return true", 15)
            if "error" in said:
                wrong.append(f"page {count}: the endpoint did not answer the opening in 15 s: {said['error']}")
                break
            while time.monotonic() - asked < 15:
                said = app.eval("return nib.pages.each().filter(([, page]) => page.live).length", 15)
                if "error" in said:
                    wrong.append(f"page {count}: the endpoint stopped answering: {said['error']}")
                    break
                if why := drive.window_answers(process.pid):
                    wrong.append(f"page {count}: {why}")
                    break
                if said.get("value", 0) >= count + len(args.first.split(",")):
                    break
                time.sleep(0.25)
            if wrong:
                break
            took = time.monotonic() - asked
            print(f"page {count}: answered {took:.1f} s; {fuzz.census(process.pid)}", flush=True)
        if wrong:
            fuzz.stacks(process.pid, "~0kc 60")
            fuzz.engine_stacks(process.pid)
            time.sleep(5)
            late = app.eval("return nib.workspace.tabs.length", 15)
            wrong.append(f"later: endpoint {late}, window {drive.window_answers(process.pid) or 'answers'}")
    finally:
        process.kill()
        process.wait(20)
        site.shutdown()
        for line in drive.stalls(args.identifier):
            print(line, flush=True)
        shutil.rmtree(spaces, ignore_errors=True)

    for one in wrong:
        print(f"::error::{one}", flush=True)
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
