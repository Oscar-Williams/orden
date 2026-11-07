from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

drive = importlib.import_module("web-tab-drive")
alt = importlib.import_module("alt-alone-drive")
from probe_app import main_window

ALT = 0x12
SPACE = 0x20
ESCAPE = 0x1B
KEY_UP = 0x0002


def press(user32, *keys: int) -> None:
    for key in keys:
        user32.keybd_event(key, 0, 0, 0)
    for key in reversed(keys):
        user32.keybd_event(key, 0, KEY_UP, 0)


def log_dir(identifier: str) -> pathlib.Path:
    return pathlib.Path(os.environ["LOCALAPPDATA"]) / identifier / "logs"


def stall_lines(identifier: str) -> list[str]:
    lines: list[str] = []
    for log in log_dir(identifier).glob("*.log"):
        lines += [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if "stall" in line]
    return lines


def started(exe: pathlib.Path, config: pathlib.Path, spaces: pathlib.Path, secret: str):
    (config / "automation.json").write_text(json.dumps({"port": 0, "secret": secret, "eval": True}), encoding="utf-8")
    process = subprocess.Popen([str(exe)], env={**os.environ, "NIB_SPACES_DIR": str(spaces)}, cwd=str(exe.parent))
    app = drive.endpoint(config, process.pid, secret)
    until = time.monotonic() + 90
    while time.monotonic() < until and app.eval("!!nib.workspace").get("value") is not True:
        time.sleep(1)
    time.sleep(3)
    return process, app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--identifier", required=True)
    args = parser.parse_args()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    config = drive.config_of(args.identifier)
    shutil.rmtree(config, ignore_errors=True)
    shutil.rmtree(log_dir(args.identifier), ignore_errors=True)
    config.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    spaces = pathlib.Path(tempfile.mkdtemp(prefix="nib-stall-"))
    (spaces / "Stall").mkdir()
    (spaces / "Stall" / "A note.md").write_text("# A note\n\nWords.\n", encoding="utf-8")
    wrong: list[str] = []
    process, app = started(args.exe, config, spaces, secret)
    try:
        hwnd = main_window(process.pid)
        before = len(stall_lines(args.identifier))

        drive.forward(process.pid)
        time.sleep(0.5)
        press(user32, ALT, SPACE)
        time.sleep(3.0)
        shown = alt.in_menu(user32, hwnd)
        press(user32, ESCAPE)
        time.sleep(1.5)
        if alt.in_menu(user32, hwnd):
            press(user32, ESCAPE)
            time.sleep(1.0)
        held = stall_lines(args.identifier)[before:]
        print(f"window menu shown 3 s (menu mode {shown}): stall lines {held}", flush=True)
        if held:
            wrong.append(f"a window menu on screen was logged as a stall: {held}")

        before = len(stall_lines(args.identifier))
        drive.forward(process.pid)
        time.sleep(0.5)
        press(user32, ALT)
        time.sleep(3.0)
        hidden = alt.in_menu(user32, hwnd)
        press(user32, ESCAPE)
        time.sleep(2.0)
        said = app.eval("return 1 + 1", 8)
        seen = stall_lines(args.identifier)[before:]
        print(f"hidden menu loop 3 s (menu mode {hidden}), page after {said}: stall lines {seen}", flush=True)
        if not hidden:
            wrong.append("a tap of Alt opened no menu loop in this build, so nothing was tested")
        if not any("has not answered for 1 s" in line for line in seen):
            wrong.append("a hidden menu loop of 3 s logged no stall")
        if not any("answered after" in line for line in seen):
            wrong.append("the end of a hidden menu loop was not logged")

        drive.forward(process.pid)
        time.sleep(0.5)
        press(user32, ALT)
        time.sleep(8.0)
        marker = log_dir(args.identifier) / "not-responding.json"
        kept = marker.read_text(encoding="utf-8") if marker.exists() else None
        print(f"hidden menu loop 8 s: marker {kept}", flush=True)
        if kept is None:
            wrong.append("a hidden menu loop of 8 s left no not-responding.json")
    finally:
        process.kill()
        try:
            process.wait(20)
        except subprocess.TimeoutExpired:
            pass

    before = len(stall_lines(args.identifier))
    process, app = started(args.exe, config, spaces, secret)
    try:
        time.sleep(2)
        told = stall_lines(args.identifier)[before:]
        print(f"next start: stall lines {told}", flush=True)
        if not any("was not responding for" in line for line in told):
            wrong.append("the next start did not tell of the window that was ended not responding")
    finally:
        process.kill()
        try:
            process.wait(20)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(spaces, ignore_errors=True)

    print("all stall lines:", flush=True)
    for line in stall_lines(args.identifier):
        print(f"  {line}", flush=True)
    for one in wrong:
        print(f"::error::{one}", flush=True)
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
