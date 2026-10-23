#!/bin/bash
# ────────────────────────────────────────────────────────────────────────────
#  malfunction · double-click to install (first time) and open the app.
#
#  Everything goes into the hidden .runtime folder next to this file:
#  a private Python, its packages, ffmpeg and FFglitch. Nothing else on the
#  computer is installed or changed. To uninstall, delete the malfunction folder.
# ────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
HERE="$PWD"
RT="$HERE/.runtime"
PY="$RT/venv/bin/python"

fail() {
  echo
  echo "✖ $1"
  echo
  echo "If you're stuck, send a screenshot of this window to your teacher."
  read -n1 -r -p "press any key to close"
  exit 1
}

# keep uv (and the Python it downloads) completely inside .runtime
export UV_PYTHON_INSTALL_DIR="$RT/python"
export UV_PYTHON_BIN_DIR="$RT/python-bin"
export UV_CACHE_DIR="$RT/cache"
export UV_TOOL_DIR="$RT/uv-tools"
export UV_NO_CONFIG=1
export UV_NO_MODIFY_PATH=1
export UV_MANAGED_PYTHON=1
# trust the computer's own certificates (school networks often add their own for web filtering)
export UV_NATIVE_TLS=1

# already set up? (checked every launch, so a moved or half-finished install repairs itself)
installed() {
  [ -f "$RT/ready" ] || return 1
  "$PY" -c "import numpy, cv2" >/dev/null 2>&1 || return 1
  [ -x "$RT/ffmpeg/ffmpeg" ] || command -v ffmpeg >/dev/null
}

if ! installed; then
  echo "malfunction · first-time setup"
  echo "This downloads about 600 MB into this folder and takes a few minutes."
  echo "Nothing outside the malfunction folder is changed."
  echo
  mkdir -p "$RT" || fail "can't write in $HERE – move the malfunction folder somewhere you own (Desktop or Documents)"

  # 1 · uv: a small tool that fetches a private copy of Python
  if [ ! -x "$RT/uv/uv" ]; then
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64)   UVA=uv-aarch64-apple-darwin ;;
      Darwin-x86_64)  UVA=uv-x86_64-apple-darwin ;;
      Linux-x86_64)   UVA=uv-x86_64-unknown-linux-gnu ;;
      Linux-aarch64)  UVA=uv-aarch64-unknown-linux-gnu ;;
      *) fail "this computer ($(uname -s) $(uname -m)) isn't supported by the installer" ;;
    esac
    echo "[1/4] getting the Python installer (uv)…"
    mkdir -p "$RT/uv"
    curl -fL --retry 4 --progress-bar -o "$RT/uv.tar.gz" \
      "https://github.com/astral-sh/uv/releases/latest/download/$UVA.tar.gz" \
      || fail "couldn't download uv – check the internet connection and try again"
    tar -xzf "$RT/uv.tar.gz" -C "$RT/uv" --strip-components 1 || fail "couldn't unpack uv"
    rm -f "$RT/uv.tar.gz"
  fi
  UV="$RT/uv/uv"

  # 2 · a private Python + its own environment (rebuilt if the folder was moved)
  echo "[2/4] setting up a private Python…"
  if ! "$PY" -c "import sys" >/dev/null 2>&1; then
    rm -rf "$RT/venv"
    "$UV" venv --python 3.12 "$RT/venv" || fail "couldn't set up Python"
  fi

  # 3 · the Python packages (numpy, OpenCV), into that environment only
  echo "[3/4] installing the Python packages…"
  "$UV" pip install --python "$PY" -r "$HERE/requirements.txt" || fail "couldn't install the Python packages"
  "$UV" cache clean >/dev/null 2>&1

  # 4 · ffmpeg + FFglitch, into .runtime
  echo "[4/4] getting ffmpeg and FFglitch…"
  "$PY" "$HERE/tools/setup_runtime.py" || fail "setup didn't finish – run it again (it continues where it stopped)"

  # macOS flags downloaded files (the zip this folder came from) and blocks double-clicking
  # unsigned scripts. Remove the flag from this folder only, so next time a double-click just works.
  [ "$(uname -s)" = "Darwin" ] && xattr -dr com.apple.quarantine "$HERE" 2>/dev/null
  date > "$RT/ready"
  echo
  echo "✔ setup complete – opening malfunction"
  echo
fi

[ -n "$MALFUNCTION_SETUP_ONLY" ] && { echo "setup only – not opening the app"; exit 0; }

# stop any older malfunction window that is still holding the port
pkill -f "malfunction_ui.py" 2>/dev/null && sleep 1

"$PY" "$HERE/malfunction_ui.py" || fail "malfunction exited with an error (see above)"
