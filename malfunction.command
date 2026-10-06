#!/bin/bash
# double-click in Finder to launch the malfunction UI.
# the first launch checks the extras (numpy + OpenCV, FFglitch) and installs what's missing;
# once everything is in place it writes .installed and later launches skip straight to the UI.
# delete .installed to make it check again.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

fail() { echo; echo "✖ $1"; echo; read -n1 -p "press any key to close"; exit 1; }

command -v ffmpeg  >/dev/null || fail "ffmpeg not found – install it with:  brew install ffmpeg"
command -v python3 >/dev/null || fail "python3 not found – run:  xcode-select --install"

if [ ! -f .installed ]; then
  echo "first launch: checking extras…"

  # optical-flow engine: numpy + OpenCV
  if python3 -c "import numpy, cv2" 2>/dev/null; then
    echo "  numpy + OpenCV   ok"
  else
    echo "  installing numpy + OpenCV…"
    python3 -m pip install --user -r requirements.txt >/dev/null 2>&1 \
      || python3 -m pip install --user --break-system-packages -r requirements.txt \
      || echo "  ⚠ couldn't install numpy/OpenCV – the flow engine will be unavailable"
  fi

  # motion-vector hacking: FFglitch
  has_ffglitch() {
    python3 -c "import malfunction as m, sys; sys.exit(0 if m.find_ffglitch('ffedit') and m.find_ffglitch('ffgac') else 1)" 2>/dev/null
  }
  if has_ffglitch; then
    echo "  FFglitch         ok"
  else
    echo "  installing FFglitch…"
    python3 malfunction.py --install-ffglitch || echo "  ⚠ couldn't install FFglitch – --mv on xvid/native will be unavailable"
  fi

  if python3 -c "import numpy, cv2" 2>/dev/null && has_ffglitch; then
    date > .installed
    echo "  all set – future launches skip these checks"
  fi
fi

# stop any older malfunction UI that is still holding the port
pkill -f "malfunction_ui.py" 2>/dev/null && sleep 1

python3 malfunction_ui.py || fail "the UI exited with an error (see above)"
