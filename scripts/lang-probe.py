from __future__ import annotations

import argparse
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

WATCH = """
if (!window.__reads) {
  window.__reads = []
  const real = window.getComputedStyle
  window.getComputedStyle = function (node, ...rest) {
    const at = performance.now()
    const style = real.call(this, node, ...rest)
    void style.transform
    const took = performance.now() - at
    if (took > 15) window.__reads.push({ took: Math.round(took), node: (node.outerHTML || '').slice(0, 160), stack: (new Error().stack || '').split('\\n').slice(2, 9).join(' | ') })
    return style
  }
  const realRect = Element.prototype.getBoundingClientRect
  Element.prototype.getBoundingClientRect = function () {
    const at = performance.now()
    const rect = realRect.call(this)
    const took = performance.now() - at
    if (took > 15) window.__reads.push({ took: Math.round(took), rect: true, node: (this.outerHTML || '').slice(0, 160), stack: (new Error().stack || '').split('\\n').slice(2, 9).join(' | ') })
    return rect
  }
  window.__frames = []
  new PerformanceObserver((list) => {
    for (const one of list.getEntries()) window.__frames.push({ took: Math.round(one.duration), block: Math.round(one.blockingDuration), render: Math.round(one.renderStart ? one.startTime + one.duration - one.renderStart : 0), style: Math.round(one.styleAndLayoutStart ? one.startTime + one.duration - one.styleAndLayoutStart : 0), scripts: one.scripts.map((s) => `${s.invoker} ${Math.round(s.duration)}ms forced ${Math.round(s.forcedStyleAndLayoutDuration)}ms ${s.sourceFunctionName} ${s.sourceURL.split('/').pop()}:${s.sourceCharPosition}`) })
  }).observe({ type: 'long-animation-frame', buffered: false })
}
window.__reads.length = 0
window.__frames.length = 0
return true
"""

PICK = """
nib.settings.show('general')
await new Promise((done) => setTimeout(done, 300))
const sheet = document.querySelector('[role=dialog][aria-modal=true]')
const picker = [...(sheet ?? document).querySelectorAll('button[aria-haspopup], select')].find((one) => /English|Deutsch|Language|Sprache|Match the system|Systemsprache/i.test(`${one.textContent} ${one.getAttribute('aria-label') ?? ''} ${one.closest('label, .row, [data-row]')?.textContent ?? ''}`))
if (!picker) return 'no picker'
picker.click()
await new Promise((done) => setTimeout(done, 300))
const want = [...document.querySelectorAll('[role=option]')].find((one) => new RegExp(WANT).test(one.textContent))
if (!want) return 'no option'
const at = performance.now()
want.click()
return performance.now() - at
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=pathlib.Path)
    parser.add_argument("--identifier", required=True)
    args = parser.parse_args()
    config = drive.config_of(args.identifier)
    shutil.rmtree(config, ignore_errors=True)
    config.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    (config / "automation.json").write_text(json.dumps({"port": 0, "secret": secret, "eval": True}), encoding="utf-8")
    spaces = pathlib.Path(tempfile.mkdtemp(prefix="nib-lang-"))
    (spaces / "Lang").mkdir()
    (spaces / "Lang" / "A note.md").write_text("# A note\n\nWords.\n", encoding="utf-8")
    process = subprocess.Popen([str(args.exe)], env={**os.environ, "NIB_SPACES_DIR": str(spaces)}, cwd=str(args.exe.parent))
    try:
        app = drive.endpoint(config, process.pid, secret)
        until = time.monotonic() + 90
        while time.monotonic() < until and app.eval("!!nib.workspace").get("value") is not True:
            time.sleep(1)
        time.sleep(3)
        drive.forward(process.pid)
        for name, want in (("first German", "^\\s*Deutsch"), ("back to English", "^\\s*English"), ("German again", "^\\s*Deutsch"), ("first Arabic", "العربية"), ("first Japanese", "日本語")):
            app.eval(WATCH, 20)
            asked = time.monotonic()
            said = app.eval(PICK.replace("WANT", json.dumps(want)), 30)
            time.sleep(3)
            seen = app.eval("return { reads: window.__reads, frames: window.__frames }", 20)
            print(f"== {name}: click {said} in {time.monotonic() - asked - 3:.1f} s", flush=True)
            value = seen.get("value") or {}
            for one in value.get("reads", []):
                print(f"  read {json.dumps(one)}", flush=True)
            for one in value.get("frames", []):
                print(f"  frame {json.dumps(one)}", flush=True)
            app.eval("nib.settings.open = false; return true", 20)
            time.sleep(1)
    finally:
        process.kill()
        try:
            process.wait(20)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(spaces, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
