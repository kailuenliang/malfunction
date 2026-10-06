#!/usr/bin/env python3
"""
malfunction_ui – a small local web UI for malfunction.py

    ./malfunction_ui.py            → opens http://127.0.0.1:8765 in your browser

Standard library only. The server listens on localhost only.
"""

import argparse
import glob
import json
import mimetypes
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import malfunction as mf  # noqa: E402

ENGINE = os.path.join(HERE, "malfunction.py")
DEFAULT_OUT = os.path.join(HERE, "renders")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".m4v", ".avi", ".vob", ".mpg", ".mpeg", ".webm", ".ts")


# ────────────────────────────────────────────────────────────────────────────
#  job state (one rip at a time)
# ────────────────────────────────────────────────────────────────────────────

class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.state = "idle"        # idle | running | stopping | discarding | done | discarded | error
        self.discard = False
        self.start_info = {}
        self.progress = {}
        self.result = {}
        self.stderr = deque(maxlen=80)
        self.snapshot = os.path.join(tempfile.gettempdir(), f"malfunction_snap_{os.getpid()}.jpg")
        self.last_good_jpeg = b""
        self.cmd = []

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, params):
        if self.running():
            raise RuntimeError("a rip is already running")
        cmd = [sys.executable, "-u", ENGINE, "--ui", "--snapshot", self.snapshot] + build_args(params)
        try:
            os.remove(self.snapshot)
        except OSError:
            pass
        with self.lock:
            self.state, self.progress, self.result, self.start_info = "running", {}, {}, {}
            self.discard = False
            self.stderr.clear()
            self.last_good_jpeg = b""
            self.cmd = cmd
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, env=env, cwd=HERE)
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_out(self):
        p = self.proc
        for line in p.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                t = msg.get("type")
                if t == "start":
                    self.start_info = msg
                elif t == "progress":
                    self.progress = msg
                elif t == "done":
                    self.result = msg
        p.wait()
        if self.discard:
            folder = self.start_info.get("folder") or self.result.get("folder")
            if folder:
                delete_render_folder(folder)
            with self.lock:
                self.state, self.result = "discarded", {}
            return
        with self.lock:
            if self.result.get("ok"):
                self.state = "done"
            else:
                self.state = "error"

    def _read_err(self):
        for line in self.proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            # drop the terminal-art banner and ANSI codes
            clean = mf.re.sub(r"\x1b\[[0-9;]*m", "", line)
            if any(ch in clean for ch in "▓▒░█▄▀") and len(clean) > 60:
                continue
            self.stderr.append(clean)

    def stop(self):
        if self.running():
            with self.lock:
                self.state = "stopping"
            self.proc.send_signal(signal.SIGINT)

    def jump(self):
        """Tell a running looper to move to a new random position now."""
        if self.running() and hasattr(signal, "SIGUSR1"):
            self.proc.send_signal(signal.SIGUSR1)
            return True
        return False

    def discard_run(self):
        """Stop the rip and delete everything it wrote."""
        if self.running():
            with self.lock:
                self.discard = True
                self.state = "discarding"
            self.proc.send_signal(signal.SIGINT)

    def status(self):
        with self.lock:
            return dict(state=self.state, start=self.start_info, progress=self.progress,
                        result=self.result, log=list(self.stderr)[-14:],
                        cmd=" ".join(self.cmd[3:]) if self.cmd else "")

    def frame(self):
        try:
            with open(self.snapshot, "rb") as f:
                b = f.read()
            if b[:2] == b"\xff\xd8" and b[-2:] == b"\xff\xd9":
                self.last_good_jpeg = b
        except OSError:
            pass
        return self.last_good_jpeg


JOB = Job()


def build_args(p):
    """Translate the form into malfunction.py flags (whitelisted)."""
    a = []
    src = (p.get("source") or "").strip()
    if src:
        a += ["--source", os.path.expanduser(src)]
    if p.get("title"):
        a += ["--title", str(int(p["title"]))]
    a += ["--preset", p.get("preset", "melt")]
    a += ["-o", os.path.expanduser(p.get("out") or DEFAULT_OUT)]
    numeric = {
        "engine": str, "drop_i": float, "refresh": float, "bloom_every": float,
        "bloom_len": int, "bend": float, "bend_amount": float, "q": int, "gop": int,
        "seed": int, "start": float, "duration": float, "crf": int,
        "i_mode": str, "bloom_mode": str, "audio": str, "name": str, "scale": str, "smooth": int,
        "mv": str, "mv_amount": float, "mv_delay": int, "flow_leak": float,
        "bleed": str, "bleed_amount": float, "grain": float,
        "loop_frames": int, "loop_hold": float, "audio_fx_amount": float, "audio_decay": float, "audio_fx": str, "loop_speed": float, "loop_slow": str, "loop_slow_audio": str,
    }
    for k, cast in numeric.items():
        v = p.get(k)
        if v in (None, "", "auto"):
            continue
        a += ["--" + k.replace("_", "-"), str(cast(v))]
    if "mv" in p and not p.get("mv"):
        a += ["--mv", "none"]           # chips all off: override the preset's motion hacks
    if "bleed" in p and not p.get("bleed"):
        a += ["--bleed", "none"]
    if "audio_fx" in p and not p.get("audio_fx"):
        a += ["--audio-fx", "none"]
    if "loop" in p:
        a.append("--loop" if p.get("loop") else "--no-loop")
    if "loop_fresh" in p:
        a.append("--loop-fresh" if p.get("loop_fresh") else "--no-loop-fresh")
    for flag in ("keep_clean", "no_raw", "bend_i", "preview"):
        if p.get(flag):
            a.append("--" + flag.replace("_", "-"))
    return a


# ────────────────────────────────────────────────────────────────────────────
#  sources
# ────────────────────────────────────────────────────────────────────────────

def scan_sources(extra_dirs=()):
    discs = []
    for vts in mf.find_video_ts_dirs():
        try:
            titles = mf.list_titles(vts)
        except OSError:
            titles = []
        vol = os.path.dirname(vts)
        discs.append(dict(path=vol, name=os.path.basename(vol) or vol,
                          titles=[dict(n=t["n"], gb=round(t["size"] / 1e9, 2)) for t in titles],
                          encrypted=bool(titles and mf.check_scrambled(titles[0]["files"][0]))))
    files = []
    dirs = [HERE, os.path.expanduser("~/Movies"), os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads")] + list(extra_dirs)
    seen = set()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        pats = [os.path.join(d, "*"), os.path.join(d, "*", "*")] if d == HERE else [os.path.join(d, "*")]
        for pat in pats:
            for f in glob.glob(pat):
                if not f.lower().endswith(VIDEO_EXT) or f in seen:
                    continue
                if os.path.abspath(f).startswith(DEFAULT_OUT + os.sep):
                    continue
                seen.add(f)
                try:
                    st = os.stat(f)
                except OSError:
                    continue
                files.append(dict(path=f, name=os.path.basename(f),
                                  dir=os.path.dirname(f).replace(os.path.expanduser("~"), "~"),
                                  mb=round(st.st_size / 1e6, 1), mtime=st.st_mtime))
    files.sort(key=lambda x: -x["mtime"])
    return dict(discs=discs, files=files[:60])


def _inside_out_dir(path):
    path = os.path.abspath(path)
    return any(path.startswith(d + os.sep) for d in ALLOWED_MEDIA_DIRS)


def delete_render_folder(folder):
    """Remove one rip's folder – only if it sits directly inside an output dir."""
    folder = os.path.abspath(folder)
    if os.path.isdir(folder) and os.path.dirname(folder) in ALLOWED_MEDIA_DIRS:
        shutil.rmtree(folder, ignore_errors=True)
        return True
    return False


def delete_render(path):
    path = os.path.abspath(path)
    if not _inside_out_dir(path):
        return False
    folder = os.path.dirname(path)
    if folder in ALLOWED_MEDIA_DIRS:
        # an older, un-foldered render: remove just its own files
        stem = os.path.splitext(os.path.basename(path))[0]
        for f in glob.glob(os.path.join(folder, glob.escape(stem) + ".*")):
            os.remove(f)
        return True
    return delete_render_folder(folder)


def list_renders(out_dir):
    out = []
    files = glob.glob(os.path.join(out_dir, "*", "*.mp4")) + glob.glob(os.path.join(out_dir, "*.mp4"))
    for f in files:
        if f.endswith(".tmp.mp4"):
            continue
        st = os.stat(f)
        folder = os.path.dirname(f)
        logs = glob.glob(os.path.join(folder, glob.escape(os.path.splitext(os.path.basename(f))[0]) + ".log"))
        out.append(dict(path=f, name=os.path.basename(f), mb=round(st.st_size / 1e6, 1), mtime=st.st_mtime,
                        folder=folder, log=logs[0] if logs else None))
    out.sort(key=lambda x: -x["mtime"])
    return out[:30]


# ── optional dependencies: FFglitch (motion vectors) and numpy+OpenCV (flow)

DEPS = {"installing": None, "message": ""}


def deps_status():
    flow_ok = subprocess.run([sys.executable, "-c", "import numpy, cv2"],
                             capture_output=True).returncode == 0
    return dict(ffglitch=bool(mf.find_ffglitch("ffedit") and mf.find_ffglitch("ffgac")),
                flow=flow_ok, installing=DEPS["installing"], message=DEPS["message"],
                mv_modes=mf.MV_MODES, bleed_modes=mf.BLEED_MODES, audio_fx_modes=mf.AUDIO_FX_MODES)


def install_dep(what):
    if DEPS["installing"]:
        return
    DEPS["installing"], DEPS["message"] = what, f"installing {what}…"

    def run():
        try:
            if what == "ffglitch":
                r = subprocess.run([sys.executable, ENGINE, "--install-ffglitch"], capture_output=True, text=True)
            else:
                base = [sys.executable, "-m", "pip", "install", "--user", "numpy", "opencv-python"]
                r = subprocess.run(base, capture_output=True, text=True)
                if r.returncode != 0 and "externally-managed" in (r.stderr + r.stdout):
                    r = subprocess.run(base + ["--break-system-packages"], capture_output=True, text=True)
            tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
            DEPS["message"] = f"✔ {what} installed" if r.returncode == 0 else f"✖ {what}: {tail[0][:200]}"
        except Exception as e:
            DEPS["message"] = f"✖ {what}: {e}"
        finally:
            DEPS["installing"] = None

    threading.Thread(target=run, daemon=True).start()


def mac_pick_file():
    if sys.platform != "darwin":
        return None
    script = ('POSIX path of (choose file with prompt "Pick a video, VOB, or VIDEO_TS file" '
              'default location (path to movies folder))')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
        return r.stdout.strip() or None
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────────────
#  http
# ────────────────────────────────────────────────────────────────────────────

ALLOWED_MEDIA_DIRS = {os.path.abspath(DEFAULT_OUT)}


class H(BaseHTTPRequestHandler):
    server_version = "malfunction"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/presets":
            return self._send(200, dict(presets=mf.PRESETS, out=DEFAULT_OUT))
        if u.path == "/api/sources":
            return self._send(200, scan_sources())
        if u.path == "/api/deps":
            return self._send(200, deps_status())
        if u.path == "/api/status":
            return self._send(200, JOB.status())
        if u.path == "/api/renders":
            d = os.path.expanduser(q.get("out", [DEFAULT_OUT])[0])
            ALLOWED_MEDIA_DIRS.add(os.path.abspath(d))
            return self._send(200, list_renders(d))
        if u.path == "/api/frame":
            b = JOB.frame()
            return self._send(200 if b else 204, b, "image/jpeg")
        if u.path == "/media":
            return self._media(q.get("path", [""])[0])
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/run":
            p = self._body()
            if p.get("out"):
                ALLOWED_MEDIA_DIRS.add(os.path.abspath(os.path.expanduser(p["out"])))
            try:
                JOB.start(p)
            except (RuntimeError, ValueError) as e:
                return self._send(409, {"error": str(e)})
            return self._send(200, {"ok": True})
        if u.path == "/api/stop":
            JOB.stop()
            return self._send(200, {"ok": True})
        if u.path == "/api/jump":
            return self._send(200, {"ok": JOB.jump()})
        if u.path == "/api/discard":
            JOB.discard_run()
            return self._send(200, {"ok": True})
        if u.path == "/api/delete":
            ok = delete_render(self._body().get("path", ""))
            return self._send(200 if ok else 403, {"ok": ok})
        if u.path == "/api/install":
            what = self._body().get("what")
            if what in ("ffglitch", "flow"):
                install_dep(what)
            return self._send(200, {"ok": True})
        if u.path == "/api/pick":
            return self._send(200, {"path": mac_pick_file()})
        if u.path == "/api/reveal":
            path = self._body().get("path", "")
            if sys.platform == "darwin" and os.path.exists(path):
                subprocess.Popen(["open", "-R", path])
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

    def _media(self, path):
        path = os.path.abspath(path)
        if not any(path.startswith(d + os.sep) for d in ALLOWED_MEDIA_DIRS) or not os.path.isfile(path):
            return self._send(403, {"error": "forbidden"})
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            if s:
                start = int(s)
                end = int(e) if e else size - 1
            else:
                start = size - int(e)
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        length = end - start + 1
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


# ────────────────────────────────────────────────────────────────────────────
#  page
# ────────────────────────────────────────────────────────────────────────────

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>malfunction</title>
<style>
:root{
  --bg:#07070a; --panel:#0f0f14; --line:#23232c; --text:#d8d8e0; --dim:#6c6c7a;
  --r:#ff2e4d; --g:#2effa1; --b:#2e8bff; --m:#ff2ee6; --y:#ffd12e;
  --mono: ui-monospace, "SF Mono", Menlo, "JetBrains Mono", monospace;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font:13px/1.45 var(--mono)}
body::after{content:"";position:fixed;inset:0;pointer-events:none;
  background:repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0 1px,transparent 1px 3px);mix-blend-mode:screen}
header{display:flex;align-items:baseline;gap:18px;padding:18px 22px 10px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:12px;font-weight:400;letter-spacing:0;color:var(--text)}
header .sub{color:var(--dim)}
main{display:grid;grid-template-columns:minmax(300px,380px) 1fr;gap:0;min-height:calc(100vh - 60px)}
aside{border-right:1px solid var(--line);padding:14px 18px 40px;overflow:auto;max-height:calc(100vh - 60px)}
section.stage{padding:18px 22px;display:flex;flex-direction:column;gap:14px;min-width:0}
h2{font-size:11px;letter-spacing:.25em;color:var(--dim);font-weight:500;margin:18px 0 8px;text-transform:uppercase}
h2:first-child{margin-top:0}
label{display:block;margin:8px 0 3px;color:var(--dim);font-size:11px}
input[type=text],input[type=number],select{width:100%;background:var(--panel);color:var(--text);border:1px solid var(--line);
  padding:7px 8px;font:inherit;border-radius:2px}
input:focus,select:focus{outline:1px solid var(--m);border-color:var(--m)}
.row{display:flex;gap:8px}.row>*{flex:1}
.slider{display:grid;grid-template-columns:1fr 54px;gap:8px;align-items:center}
.slider output{text-align:right;color:var(--g)}
input[type=range]{width:100%;accent-color:var(--m)}
.check{display:flex;align-items:center;gap:8px;margin:6px 0;color:var(--text);font-size:12px}
.check input{accent-color:var(--m)}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--panel);color:var(--text);padding:7px 10px;border-radius:2px}
button:hover{border-color:var(--m)}
button.go{width:100%;padding:13px;margin-top:16px;font-size:15px;letter-spacing:.3em;font-weight:700;
  background:var(--m);color:#000;border:none;text-shadow:1px 0 var(--b)}
button.go:hover{filter:brightness(1.15)}
button.stop{background:var(--r);color:#000;border:none}
button:disabled{opacity:.4;cursor:default}
.srclist{max-height:170px;overflow:auto;border:1px solid var(--line);background:var(--panel)}
.src{padding:6px 8px;cursor:pointer;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:8px}
.src:hover{background:#1a1a22}.src.sel{background:#2a0f28;color:#fff}
.src small{color:var(--dim);white-space:nowrap}
.src .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.disc{color:var(--y)}
details{margin-top:4px}summary{cursor:pointer;color:var(--dim);font-size:11px;letter-spacing:.2em;text-transform:uppercase;margin:16px 0 6px}
.screen{position:relative;background:#000;border:1px solid var(--line);aspect-ratio:16/9;display:grid;place-items:center;overflow:hidden}
.screen img,.screen video{width:100%;height:100%;object-fit:contain;display:block}
.screen .idle{color:var(--dim);text-align:center;letter-spacing:.3em}
.screen .tag{position:absolute;top:8px;left:10px;background:#000a;padding:2px 6px;font-size:11px;letter-spacing:.2em}
.tag.live{color:var(--r)}.tag.live::before{content:"● "}
.bar{height:6px;background:var(--panel);border:1px solid var(--line);position:relative;overflow:hidden}
.bar i{position:absolute;inset:0 auto 0 0;background:linear-gradient(90deg,var(--b),var(--m),var(--r));width:0}
.stats{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--dim)}
.stats b{color:var(--text);font-weight:500}
.strip{font-size:14px;letter-spacing:1px;line-height:1.2;word-break:break-all;min-height:3.6em;
  background:var(--panel);border:1px solid var(--line);padding:8px 10px}
.strip .P{color:#2ec8ff}.strip .I{color:var(--g)}.strip .X{color:var(--r)}.strip .B{color:var(--m)}.strip .D{color:var(--y)}.strip .p{color:#3a3a46}
.legend{color:var(--dim);font-size:11px;display:flex;gap:14px;flex-wrap:wrap}
.log{background:var(--panel);border:1px solid var(--line);padding:8px 10px;color:var(--dim);font-size:11px;white-space:pre-wrap;max-height:140px;overflow:auto}
.log.err{color:var(--r)}
.renders{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}
.render{border:1px solid var(--line);background:var(--panel);padding:8px;cursor:pointer}
.render:hover{border-color:var(--m)}.render .n{word-break:break-all}.render small{color:var(--dim)}
.muted{color:var(--dim)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.chip{border:1px solid var(--line);background:var(--panel);padding:3px 7px;cursor:pointer;font-size:11px;border-radius:2px;user-select:none}
.chip.on{background:var(--m);color:#000;border-color:var(--m)}
.dep{font-size:11px;color:var(--dim);margin-top:6px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.dep b{color:var(--g);font-weight:500}.dep b.no{color:var(--r)}
.dep button{padding:3px 8px;font-size:11px}
@media (max-width:820px){main{grid-template-columns:1fr}aside{border-right:none;border-bottom:1px solid var(--line);max-height:none}}
</style></head>
<body>
<header><h1 id="logo">malfunction</h1><span class="sub">a dvd ripper that datamoshes while it reads</span></header>
<main>
<aside>
  <h2>source</h2>
  <div class="srclist" id="srclist"><div class="src muted">scanning…</div></div>
  <div class="row" style="margin-top:6px">
    <button id="pick">choose file…</button><button id="rescan">rescan</button>
  </div>
  <label>path (disc volume, VIDEO_TS, .VOB, or any video)</label>
  <input type="text" id="source" placeholder="/Volumes/MY_DVD  or  ~/Movies/clip.mp4">
  <div class="row">
    <div><label>title</label><input type="number" id="title" min="1" placeholder="auto"></div>
    <div><label>start (s)</label><input type="number" id="start" min="0" step="1" placeholder="0"></div>
    <div><label>length (s)</label><input type="number" id="duration" min="1" step="1" placeholder="all"></div>
  </div>

  <h2>mosh</h2>
  <label>preset</label>
  <select id="preset"></select>
  <label>engine</label>
  <select id="engine"><option value="flow">flow – optical flow, per-pixel, no blocks</option><option value="h264">h264 – smooth, liquid (small blocks)</option><option value="xvid">xvid – classic blocky melt</option><option value="native">native – corrupt the disc's MPEG-2</option></select>
  <div class="row">
    <div><label>resolution</label><select id="scale"><option value="source">source (480)</option><option value="720">720p</option><option value="1080">1080p</option><option value="1440">1440p</option></select></div>
    <div><label>smoothing</label><select id="smooth"><option value="0">off</option><option value="1">light</option><option value="2">medium</option><option value="3">heavy</option></select></div>
  </div>

  <label>film grain (%, 0 = off)</label><div class="slider"><input type="range" id="grain" min="0" max="10" step="0.5" value="3"><output></output></div>
  <label>keyframe removal</label><div class="slider"><input type="range" id="drop_i" min="0" max="1" step="0.05"><output></output></div>
  <label>refresh every (s, 0 = never)</label><div class="slider"><input type="range" id="refresh" min="0" max="120" step="1"><output></output></div>
  <label>bloom every (s, 0 = off)</label><div class="slider"><input type="range" id="bloom_every" min="0" max="60" step="1"><output></output></div>
  <label>bloom length (frames)</label><div class="slider"><input type="range" id="bloom_len" min="2" max="240" step="1"><output></output></div>
  <label>databend chance / frame</label><div class="slider"><input type="range" id="bend" min="0" max="1" step="0.01"><output></output></div>
  <label>databend amount (‰ bytes)</label><div class="slider"><input type="range" id="bend_amount" min="0" max="5" step="0.05"><output></output></div>

  <h2>looper</h2>
  <div class="muted" style="font-size:11px">loop a few frames from a random point, then jump somewhere else · the mosh runs on top of the repetition</div>
  <label class="check"><input type="checkbox" id="loop"> loop random positions</label>
  <label>loop length (frames)</label><div class="slider"><input type="range" id="loop_frames" min="2" max="240" step="1"><output></output></div>
  <label>stay on each position (s)</label><div class="slider"><input type="range" id="loop_hold" min="0.5" max="30" step="0.5"><output></output></div>
  <label class="check"><input type="checkbox" id="loop_fresh"> start each new position clean</label>
  <label>loop speed (1 = normal · 0.1 = ten times slower)</label><div class="slider"><input type="range" id="loop_speed" min="0.02" max="3" step="0.01"><output></output></div>
  <div class="row">
    <div><label>slow motion</label><select id="loop_slow"><option value="interpolate">interpolate (smooth)</option><option value="blend">blend (dissolves)</option><option value="repeat">repeat (stepped)</option></select></div>
    <div><label>slowed sound</label><select id="loop_slow_audio"><option value="tape">tape (pitch drops)</option><option value="stretch">stretch (pitch kept)</option></select></div>
  </div>
  <div class="muted" style="font-size:11px" id="loophint"></div>

  <h2>motion hacking</h2>
  <div class="muted" style="font-size:11px">rewrite where pixels move. xvid / native: codec motion vectors via FFglitch · flow: the optical-flow field · h264 switches to xvid</div>
  <div class="chips" id="mvchips"></div>
  <label>motion amount</label><div class="slider"><input type="range" id="mv_amount" min="0" max="1.5" step="0.05"><output></output></div>
  <label>echo delay (frames)</label><div class="slider"><input type="range" id="mv_delay" min="5" max="300" step="5" value="90"><output></output></div>
  <div class="dep" id="deps"></div>

  <h2>bleed</h2>
  <div class="muted" style="font-size:11px">let the real footage show through the mosh · flow: all modes · native: keeps bands of removed keyframes</div>
  <div class="chips" id="bleedchips"></div>
  <label>bleed amount</label><div class="slider"><input type="range" id="bleed_amount" min="0" max="2" step="0.05"><output></output></div>

  <h2>sound</h2>
  <div class="muted" style="font-size:11px">corrupt the sound along with the picture · every engine · needs numpy</div>
  <div class="chips" id="afxchips"></div>
  <div class="muted" style="font-size:11px;margin-top:4px">stutter: skips on removed keyframes · freeze: holds a grain during blooms · decay: rots without real keyframes · motion: movement drives distortion · bleed: clean sound returns with the real picture</div>
  <label>sound corruption amount</label><div class="slider"><input type="range" id="audio_fx_amount" min="0" max="1.5" step="0.05" value="0.5"><output></output></div>
  <label>decay: seconds until fully rotted</label><div class="slider"><input type="range" id="audio_decay" min="1" max="60" step="1" value="8"><output></output></div>

  <details><summary>more</summary>
    <div class="row">
      <div><label>keyframe</label><select id="i_mode"><option value="hold">hold (reuse P)</option><option value="drop">drop</option></select></div>
      <div><label>bloom</label><select id="bloom_mode"><option value="replace">replace</option><option value="insert">insert</option></select></div>
    </div>
    <div class="row">
      <div><label>xvid quantizer</label><input type="number" id="q" min="2" max="31" value="3"></div>
      <div><label>xvid max gop</label><input type="number" id="gop" min="12" value="600"></div>
    </div>
    <div class="row">
      <div><label>seed</label><input type="number" id="seed" placeholder="random"></div>
      <div><label>audio</label><select id="audio"><option>clean</option><option>crushed</option><option>none</option></select></div>
    </div>
    <label class="check"><input type="checkbox" id="bend_i"> databend kept keyframes too</label>
  </details>

  <h2>output</h2>
  <label>folder</label><input type="text" id="out">
  <label>name (optional)</label><input type="text" id="name" placeholder="auto">
  <label class="check"><input type="checkbox" id="keep_clean"> also save a clean copy</label>
  <label class="check"><input type="checkbox" id="no_raw"> skip raw moshed bitstream</label>
  <label class="check"><input type="checkbox" id="preview"> also open ffplay window</label>

  <button class="go" id="go">RIP + MOSH</button>
</aside>

<section class="stage">
  <div class="screen" id="screen"><div class="idle" id="idle">NO SIGNAL</div><span class="tag" id="tag" hidden></span></div>
  <div class="bar"><i id="bar"></i></div>
  <div class="stats" id="stats"><span class="muted">idle</span></div>
  <div class="row" style="flex:0" id="stoprow" hidden><button class="stop" id="stop">stop + keep</button><button id="discard">stop + discard</button><button id="jump" hidden>jump to a new position</button></div>
  <div class="strip" id="strip"></div>
  <div class="legend">
    <span><span style="color:var(--g)">█</span> keyframe kept</span>
    <span><span style="color:var(--r)">▓</span> keyframe removed</span>
    <span><span style="color:#2ec8ff">▒</span> keyframe partly kept</span>
    <span><span style="color:var(--m)">✺∞</span> bloom</span>
    <span><span style="color:var(--y)">░</span> databent</span>
    <span><span style="color:#555">·</span> delta frame</span>
  </div>
  <div class="log" id="log" hidden></div>
  <h2>renders</h2>
  <div class="renders" id="renders"><span class="muted">none yet</span></div>
</section>
</main>

<script>
const $ = id => document.getElementById(id);
const SLIDERS = ["drop_i","refresh","bloom_every","bloom_len","bend","bend_amount","mv_amount","mv_delay","bleed_amount","loop_frames","loop_hold","loop_speed"];
let MVON = new Set(), BLEEDON = new Set(), AFXON = new Set();
let PRESETS = {}, OUTDIR = "", polling = null, lastState = "idle", frameTimer = null;

async function api(path, body){
  const r = await fetch(path, body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  if (r.status === 204) return null;
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}
function fmtT(s){ s = Math.max(0, s||0); const m = Math.floor(s/60), x = Math.floor(s%60); return m+":"+String(x).padStart(2,"0"); }
function syncOut(el){ el.nextElementSibling.value = el.value; }

function loopHint(){
  // one pass of a loop = frames / 29.97 fps / speed
  const f = +$("loop_frames").value, sp = +$("loop_speed").value, hold = +$("loop_hold").value;
  const pass = f / 29.97 / sp, reps = hold / pass;
  $("loophint").textContent = `one pass ≈ ${pass.toFixed(1)} s · ` +
    (reps >= 1 ? `≈ ${reps.toFixed(1)} passes per position` : `position ends before the loop finishes – raise "stay"`);
}

function applyPreset(name){
  const d = Object.assign({engine:"xvid",drop_i:1,refresh:0,bloom_every:0,bloom_len:30,bend:0,bend_amount:0.5,scale:"1080",smooth:0,
                           mv:"",mv_amount:0.5,mv_delay:90,bleed:"",bleed_amount:0.5,
                           loop:false,loop_frames:30,loop_hold:4,loop_fresh:true,
                           loop_speed:1,loop_slow:"interpolate",loop_slow_audio:"tape"}, PRESETS[name]||{});
  $("loop").checked = !!d.loop; $("loop_fresh").checked = !!d.loop_fresh;
  $("loop_slow").value = d.loop_slow; $("loop_slow_audio").value = d.loop_slow_audio;
  $("engine").value = d.engine; $("scale").value = d.scale; $("smooth").value = String(d.smooth);
  MVON = new Set((d.mv||"").split(",").filter(Boolean));
  BLEEDON = new Set((d.bleed||"").split(",").filter(Boolean));
  document.querySelectorAll("#mvchips .chip").forEach(ch => ch.classList.toggle("on", MVON.has(ch.dataset.m)));
  document.querySelectorAll("#bleedchips .chip").forEach(ch => ch.classList.toggle("on", BLEEDON.has(ch.dataset.m)));
  for (const k of SLIDERS){ $(k).value = d[k]; syncOut($(k)); }
  loopHint();
}

async function init(){
  const p = await api("/api/presets");
  PRESETS = p.presets; OUTDIR = p.out;
  $("out").value = OUTDIR;
  for (const k of Object.keys(PRESETS)){ const o = document.createElement("option"); o.value = o.textContent = k; $("preset").appendChild(o); }
  $("preset").onchange = e => applyPreset(e.target.value);
  for (const k of SLIDERS) $(k).oninput = e => { syncOut(e.target); loopHint(); };
  $("grain").oninput = e => syncOut(e.target); syncOut($("grain"));   // not part of presets: survives preset changes
  const deps = await api("/api/deps");
  for (const m of deps.mv_modes){
    const ch = document.createElement("span"); ch.className = "chip"; ch.textContent = m; ch.dataset.m = m;
    ch.onclick = () => { MVON.has(m) ? MVON.delete(m) : MVON.add(m); ch.classList.toggle("on", MVON.has(m)); };
    $("mvchips").appendChild(ch);
  }
  for (const m of deps.audio_fx_modes){
    const ch = document.createElement("span"); ch.className = "chip"; ch.textContent = m; ch.dataset.m = m;
    ch.onclick = () => { AFXON.has(m) ? AFXON.delete(m) : AFXON.add(m); ch.classList.toggle("on", AFXON.has(m)); };
    $("afxchips").appendChild(ch);
  }
  for (const k of ["audio_fx_amount","audio_decay"]){ $(k).oninput = e => syncOut(e.target); syncOut($(k)); }   // not part of presets
  for (const m of deps.bleed_modes){
    const ch = document.createElement("span"); ch.className = "chip"; ch.textContent = m; ch.dataset.m = m;
    ch.onclick = () => { BLEEDON.has(m) ? BLEEDON.delete(m) : BLEEDON.add(m); ch.classList.toggle("on", BLEEDON.has(m)); };
    $("bleedchips").appendChild(ch);
  }
  $("preset").value = "liquid"; applyPreset("liquid");
  showDeps(deps);
  scan(); loadRenders(); poll();
}

function showDeps(d){
  const el = $("deps");
  el.innerHTML = `<span>FFglitch <b class="${d.ffglitch?"":"no"}">${d.ffglitch?"ready":"missing"}</b></span>` +
                 (d.ffglitch ? "" : `<button data-w="ffglitch">install FFglitch</button>`) +
                 `<span>flow engine <b class="${d.flow?"":"no"}">${d.flow?"ready":"missing"}</b></span>` +
                 (d.flow ? "" : `<button data-w="flow">install numpy + OpenCV</button>`) +
                 (d.message ? `<span>${d.message}</span>` : "");
  el.querySelectorAll("button").forEach(b => { b.disabled = !!d.installing; b.onclick = async () => {
    await api("/api/install", {what: b.dataset.w}); pollDeps(); }; });
}
async function pollDeps(){
  const d = await api("/api/deps"); showDeps(d);
  if (d.installing) setTimeout(pollDeps, 1500);
}

async function scan(){
  const s = await api("/api/sources"), L = $("srclist");
  L.innerHTML = "";
  const add = (label, sub, path, cls) => {
    const d = document.createElement("div"); d.className = "src " + (cls||"");
    d.innerHTML = `<span class="n"></span><small></small>`;
    d.querySelector(".n").textContent = label; d.querySelector("small").textContent = sub;
    d.title = path;
    d.onclick = () => { document.querySelectorAll(".src.sel").forEach(x=>x.classList.remove("sel")); d.classList.add("sel"); $("source").value = path; };
    L.appendChild(d);
  };
  for (const d of s.discs){
    const big = d.titles.reduce((a,t)=>Math.max(a,t.gb),0);
    add("◉ " + d.name, d.encrypted ? "encrypted ✖" : `${d.titles.length} titles · ${big} GB`, d.path, "disc");
  }
  for (const f of s.files) add(f.name, `${f.mb} MB · ${f.dir}`, f.path);
  if (!L.children.length) L.innerHTML = `<div class="src muted">no disc or videos found — choose a file or type a path</div>`;
}

$("rescan").onclick = scan;
$("pick").onclick = async () => {
  const r = await api("/api/pick", {});
  if (r && r.path) $("source").value = r.path;
  else if (!navigator.platform.startsWith("Mac")) alert("File picker needs macOS – type a path instead.");
};

function params(){
  const p = {};
  for (const id of ["source","title","start","duration","preset","engine","scale","smooth","grain","loop_slow","loop_slow_audio","i_mode","bloom_mode","q","gop","seed","audio","out","name", ...SLIDERS])
    p[id] = $(id).value;
  for (const id of ["keep_clean","no_raw","preview","bend_i","loop","loop_fresh"]) p[id] = $(id).checked;
  p.mv = [...MVON].join(",");
  p.bleed = [...BLEEDON].join(",");
  p.audio_fx = [...AFXON].join(",");
  p.audio_fx_amount = $("audio_fx_amount").value; p.audio_decay = $("audio_decay").value;
  return p;
}

$("go").onclick = async () => {
  const r = await fetch("/api/run", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(params())});
  if (!r.ok){ const j = await r.json(); showLog([j.error], true); return; }
  $("strip").innerHTML = ""; $("bar").style.width = "0";
  lastState = "running"; poll();
};
$("stop").onclick = () => api("/api/stop", {});
$("jump").onclick = () => api("/api/jump", {});
$("discard").onclick = () => { if (confirm("Stop and delete this rip? Nothing will be saved.")) api("/api/discard", {}); };

function showLog(lines, err){
  const L = $("log"); L.hidden = !lines.length; L.textContent = lines.join("\n"); L.classList.toggle("err", !!err);
}

function renderStrip(s){
  const map = {"█":"I","▓":"X","╳":"X","▒":"P","✺":"B","∞":"B","░":"D","·":"p"};
  let html = "", cur = null, buf = "";
  for (const ch of s){ const c = map[ch]||"p"; if (c!==cur){ if (buf) html += `<span class="${cur}">${buf}</span>`; cur=c; buf=""; } buf+=ch; }
  if (buf) html += `<span class="${cur}">${buf}</span>`;
  $("strip").innerHTML = html;
}

function setScreenLive(on){
  const scr = $("screen");
  if (on){
    let img = scr.querySelector("img");
    if (!img){ scr.querySelector("video")?.remove(); img = document.createElement("img"); scr.prepend(img); }
    $("idle").hidden = true; $("tag").hidden = false; $("tag").className = "tag live"; $("tag").textContent = "LIVE MOSH";
    if (!frameTimer) frameTimer = setInterval(() => {
      const n = new Image(); n.onload = () => { img.src = n.src; }; n.src = "/api/frame?t=" + Date.now();
    }, 180);
  } else { clearInterval(frameTimer); frameTimer = null; }
}

function play(path, label){
  setScreenLive(false);
  const scr = $("screen"); scr.querySelector("img")?.remove(); scr.querySelector("video")?.remove();
  const v = document.createElement("video"); v.controls = true; v.autoplay = true; v.loop = true;
  v.src = "/media?path=" + encodeURIComponent(path); scr.prepend(v);
  $("idle").hidden = true; $("tag").hidden = false; $("tag").className = "tag"; $("tag").textContent = label || "RENDER";
}

async function loadRenders(){
  const list = await api("/api/renders?out=" + encodeURIComponent($("out").value || OUTDIR)), R = $("renders");
  if (!list.length){ R.innerHTML = `<span class="muted">none yet</span>`; return; }
  R.innerHTML = "";
  for (const f of list){
    const d = document.createElement("div"); d.className = "render";
    d.innerHTML = `<div class="n"></div><small></small><div class="row" style="margin-top:6px"><button>play</button><button>reveal</button><button>delete</button></div>`;
    d.querySelector(".n").textContent = f.name;
    d.querySelector("small").textContent = `${f.mb} MB · ${new Date(f.mtime*1000).toLocaleString()}`;
    const [bp, br, bd] = d.querySelectorAll("button");
    bp.onclick = () => play(f.path, f.name);
    br.onclick = () => api("/api/reveal", {path:f.path});
    bd.onclick = async () => {
      if (!confirm(`Delete ${f.name} and everything in its folder (log, raw stream, clean copy)?`)) return;
      const scr = $("screen"), v = scr.querySelector("video");
      if (v && decodeURIComponent(v.src).includes(f.path)){ v.remove(); $("idle").hidden = false; $("tag").hidden = true; }
      await api("/api/delete", {path:f.path}); loadRenders();
    };
    R.appendChild(d);
  }
}

async function poll(){
  clearTimeout(polling);
  const s = await api("/api/status");
  const running = s.state === "running" || s.state === "stopping" || s.state === "discarding";
  $("go").disabled = running; $("stoprow").hidden = !running;
  $("stop").disabled = $("discard").disabled = s.state !== "running";
  $("jump").hidden = !(running && s.start?.loop); $("jump").disabled = s.state !== "running"; $("logo").classList.toggle("busy", running);
  if (running) setScreenLive(true);
  const pr = s.progress || {}, st = pr.stats || {};
  if (pr.secs !== undefined){
    const pct = pr.total > 0 ? Math.min(100, 100*pr.secs/pr.total) : 0;
    $("bar").style.width = pct + "%";
    $("stats").innerHTML =
      `<span><b>${pct.toFixed(1)}%</b></span><span><b>${fmtT(pr.secs)}</b> / ${fmtT(pr.total)}</span>` +
      `<span>×<b>${(pr.speed||0).toFixed(1)}</b></span>` +
      `<span>keyframes <b style="color:var(--g)">${st.i_kept}</b> kept · <b style="color:var(--r)">${st.i_dropped}</b> removed</span>` +
      `<span>blooms <b style="color:var(--m)">${st.blooms}</b> (${st.bloom_frames} fr)</span>` +
      `<span>bent <b style="color:var(--y)">${st.bent_bytes}</b> B</span>` +
      (pr.loops ? `<span>position <b>${pr.loops}</b> @ ${fmtT(pr.position)}</span>` : "") +
      (s.start?.engine ? `<span>engine <b>${s.start.engine}</b></span>` : "");
    renderStrip(pr.strip || "");
  }
  if (s.state === "error") showLog(s.log.length ? s.log : ["failed"], true);
  else if (running) showLog([], false);
  if (lastState !== s.state && s.state === "discarded"){
    setScreenLive(false);
    const scr = $("screen"); scr.querySelector("img")?.remove(); scr.querySelector("video")?.remove();
    $("idle").hidden = false; $("tag").hidden = true; $("bar").style.width = "0";
    showLog(["discarded – nothing was saved"], false); loadRenders();
  }
  if (lastState !== s.state && (s.state === "done" || s.state === "error")){
    setScreenLive(false);
    if (s.state === "done" && s.result?.final){ play(s.result.final, "DONE · " + s.result.final.split("/").pop()); showLog(s.log.filter(l => /✔|raw|clean|frames/.test(l)), false); }
    loadRenders();
  }
  lastState = s.state;
  polling = setTimeout(poll, running ? 250 : 1500);
}
init();
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="web UI for malfunction")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    os.makedirs(DEFAULT_OUT, exist_ok=True)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    except OSError:
        url = f"http://127.0.0.1:{a.port}"
        print(f"port {a.port} is busy – malfunction UI is probably already running at {url}")
        print("opening it; to restart, close the other Terminal window first (or use --port 8766)")
        webbrowser.open(url)
        sys.exit(1)
    url = f"http://127.0.0.1:{a.port}"
    print(f"malfunction ui → {url}   (ctrl-c to quit)")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    def _quit(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _quit)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if JOB.running():
            print("stopping the current rip and saving what's done…")
            JOB.stop()
            try:
                JOB.proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                JOB.proc.kill()
        srv.server_close()


if __name__ == "__main__":
    main()
