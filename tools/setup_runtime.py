#!/usr/bin/env python3
"""
malfunction · set up the private tools (run by the installers, with the private Python).

Downloads, into .runtime/ only:
  · ffmpeg, ffprobe, ffplay   – static builds (martin-riedl.de for Mac/Linux, gyan.dev for Windows)
  · FFglitch                  – for motion-vector hacking (ffglitch.org)

Nothing is installed system-wide, no PATH or settings are changed. Delete .runtime/ to undo.
Safe to run again: anything already present and working is skipped.
"""

import glob
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import malfunction as mf  # noqa: E402  (shares download() and the FFglitch installer)

RT = mf.RUNTIME
BIN = os.path.join(RT, "ffmpeg")
WINDOWS = os.name == "nt"
EXE = ".exe" if WINDOWS else ""


def say(msg):
    print(msg, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def tool_works(name):
    p = os.path.join(BIN, name + EXE)
    if not os.path.isfile(p):
        return False
    try:
        r = subprocess.run([p, "-hide_banner", "-version"], capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ffmpeg_sources():
    """(kind, urls) for this computer. kind 'single' = one zip per tool, 'bundle' = one zip with bin/."""
    sysname, mach = platform.system(), platform.machine().lower()
    if sysname == "Darwin":
        arch = "arm64" if mach in ("arm64", "aarch64") else "amd64"
        base = f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release"
        return "single", {t: f"{base}/{t}.zip" for t in ("ffmpeg", "ffprobe", "ffplay")}
    if sysname == "Linux" and mach in ("x86_64", "amd64"):
        base = "https://ffmpeg.martin-riedl.de/redirect/latest/linux/amd64/release"
        return "single", {t: f"{base}/{t}.zip" for t in ("ffmpeg", "ffprobe", "ffplay")}
    if sysname == "Windows":
        return "bundle", {"zip": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"}
    return None, {}


def install_ffmpeg():
    if all(tool_works(t) for t in ("ffmpeg", "ffprobe")):
        say("  ffmpeg           already set up")
        return True
    kind, urls = ffmpeg_sources()
    if kind is None:
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            say("  ffmpeg           no private build for this computer – using the one already installed")
            return True
        say("  ✖ no ffmpeg download for this computer – install ffmpeg yourself (e.g. your package manager)")
        return False
    os.makedirs(BIN, exist_ok=True)
    tmp = os.path.join(RT, "download")
    os.makedirs(tmp, exist_ok=True)
    try:
        if kind == "single":
            for tool, url in urls.items():
                say(f"  downloading {tool}…")
                z = mf.download(url, os.path.join(tmp, tool + ".zip"))
                with zipfile.ZipFile(z) as zf:
                    member = next(n for n in zf.namelist() if os.path.basename(n) == tool)
                    with zf.open(member) as src, open(os.path.join(BIN, tool), "wb") as dst:
                        shutil.copyfileobj(src, dst)
                os.chmod(os.path.join(BIN, tool), 0o755)
                os.remove(z)
        else:
            url = urls["zip"]
            say("  downloading ffmpeg for Windows (about 110 MB)…")
            z = mf.download(url, os.path.join(tmp, "ffmpeg.zip"))
            # gyan.dev publishes a checksum next to every build
            try:
                want = mf.download(url + ".sha256", os.path.join(tmp, "ffmpeg.sha256"))
                want = open(want).read().split()[0].strip().lower()
                if want and sha256(z) != want:
                    say("  ✖ the ffmpeg download is damaged (checksum mismatch) – run the installer again")
                    return False
            except Exception:
                say("  (couldn't fetch the checksum – continuing)")
            with zipfile.ZipFile(z) as zf:
                for n in zf.namelist():
                    base = os.path.basename(n)
                    if n.replace("\\", "/").split("/")[-2:-1] == ["bin"] and base.endswith(".exe"):
                        with zf.open(n) as src, open(os.path.join(BIN, base), "wb") as dst:
                            shutil.copyfileobj(src, dst)
            os.remove(z)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if sys.platform == "darwin":
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", BIN], stderr=subprocess.DEVNULL)
    ok = all(tool_works(t) for t in ("ffmpeg", "ffprobe"))
    say("  ffmpeg           ✔ ready" if ok else "  ✖ ffmpeg didn't start after downloading")
    return ok


def install_ffglitch():
    if mf.find_ffglitch("ffedit") and mf.find_ffglitch("ffgac"):
        say("  FFglitch         already set up")
        return True
    say("  downloading FFglitch (motion-vector hacking)…")
    try:
        ok = mf.install_ffglitch(dest=os.path.join(RT, "ffglitch"))
    except SystemExit:
        ok = False
    except Exception as e:
        say(f"  ✖ FFglitch: {e}")
        ok = False
    if not ok:
        say("  ⚠ FFglitch isn't available – everything works except motion hacking on xvid/native")
    return ok


def check_python_packages():
    try:
        import numpy  # noqa: F401
        import cv2  # noqa: F401
        say("  numpy + OpenCV   ✔ ready")
        return True
    except ImportError as e:
        say(f"  ✖ Python packages missing ({e})")
        return False


def main():
    os.makedirs(RT, exist_ok=True)
    say("setting up malfunction's private tools in " + RT)
    ok_py = check_python_packages()
    ok_ff = install_ffmpeg()
    install_ffglitch()                    # optional: never blocks the install
    if not (ok_py and ok_ff):
        sys.exit(1)
    say("done.")


if __name__ == "__main__":
    main()
