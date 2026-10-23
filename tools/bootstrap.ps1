# ----------------------------------------------------------------------------
#  malfunction - Windows installer + launcher (run by malfunction.bat)
#
#  Everything goes into the hidden .runtime folder inside the malfunction folder:
#  a private Python, its packages, ffmpeg and FFglitch. No admin rights, nothing
#  installed system-wide, no PATH or registry changes. Delete the folder to uninstall.
# ----------------------------------------------------------------------------
# "Continue": Windows PowerShell 5.1 turns anything a program prints to stderr (uv's progress,
# Python warnings) into a fatal error under "Stop". Native commands are checked via $LASTEXITCODE,
# and the cmdlets that matter use -ErrorAction Stop explicitly.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"          # makes downloads much faster in Windows PowerShell
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Here = Split-Path -Parent $PSScriptRoot
$RT   = Join-Path $Here ".runtime"
$Py   = Join-Path $RT "venv\Scripts\python.exe"
$UV   = Join-Path $RT "uv\uv.exe"

function Fail($msg) {
    Write-Host ""
    Write-Host "X  $msg" -ForegroundColor Red
    exit 1
}

# keep uv (and the Python it downloads) completely inside .runtime
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RT "python"
$env:UV_PYTHON_BIN_DIR     = Join-Path $RT "python-bin"
$env:UV_CACHE_DIR          = Join-Path $RT "cache"
$env:UV_TOOL_DIR           = Join-Path $RT "uv-tools"
$env:UV_NO_CONFIG          = "1"
$env:UV_NO_MODIFY_PATH     = "1"
$env:UV_MANAGED_PYTHON     = "1"
$env:UV_PYTHON_NO_REGISTRY = "1"                   # don't register the private Python in the Windows registry
$env:UV_NATIVE_TLS         = "1"                   # trust Windows' certificates (school web filters add their own)
$env:PYTHONUTF8            = "1"

function Test-Installed {
    if (-not (Test-Path (Join-Path $RT "ready"))) { return $false }
    if (-not (Test-Path $Py)) { return $false }
    & $Py -c "import numpy, cv2" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return $false }
    return (Test-Path (Join-Path $RT "ffmpeg\ffmpeg.exe"))
}

if (-not (Test-Installed)) {
    Write-Host "malfunction - first-time setup"
    Write-Host "This downloads about 600 MB into this folder and takes a few minutes."
    Write-Host "Nothing outside the malfunction folder is changed."
    Write-Host ""
    try { New-Item -ItemType Directory -Force -Path $RT -ErrorAction Stop | Out-Null }
    catch { Fail "can't write in $Here - move the malfunction folder somewhere you own (Desktop or Documents)" }
    # hide the runtime folder like on a Mac
    try { (Get-Item $RT -Force).Attributes += "Hidden" } catch {}

    # 1 - uv: a small tool that fetches a private copy of Python
    if (-not (Test-Path $UV)) {
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
        Write-Host "[1/4] getting the Python installer (uv)..."
        $zip = Join-Path $RT "uv.zip"
        $url = "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip"
        $ok = $false
        foreach ($i in 1..4) {
            try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -ErrorAction Stop; $ok = $true; break }
            catch { Start-Sleep -Seconds (2 * $i) }
        }
        if (-not $ok) { Fail "couldn't download uv - check the internet connection and try again" }
        try { Expand-Archive -Path $zip -DestinationPath (Join-Path $RT "uv") -Force -ErrorAction Stop }
        catch { Fail "couldn't unpack uv" }
        Remove-Item $zip -Force
    }

    # 2 - a private Python + its own environment (rebuilt if the folder was moved)
    Write-Host "[2/4] setting up a private Python..."
    $pyOk = $false
    if (Test-Path $Py) { & $Py -c "import sys" 2>$null | Out-Null; $pyOk = ($LASTEXITCODE -eq 0) }
    if (-not $pyOk) {
        if (Test-Path (Join-Path $RT "venv")) { Remove-Item (Join-Path $RT "venv") -Recurse -Force -ErrorAction SilentlyContinue }
        & $UV venv --python 3.12 (Join-Path $RT "venv")
        if ($LASTEXITCODE -ne 0) { Fail "couldn't set up Python" }
    }

    # 3 - the Python packages (numpy, OpenCV), into that environment only
    Write-Host "[3/4] installing the Python packages..."
    & $UV pip install --python $Py -r (Join-Path $Here "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "couldn't install the Python packages" }
    & $UV cache clean 2>$null | Out-Null

    # 4 - ffmpeg + FFglitch, into .runtime
    Write-Host "[4/4] getting ffmpeg and FFglitch..."
    & $Py (Join-Path $Here "tools\setup_runtime.py")
    if ($LASTEXITCODE -ne 0) { Fail "setup didn't finish - run malfunction.bat again (it continues where it stopped)" }

    # Windows flags downloaded files ("Mark of the Web") and asks before running them.
    # Remove the flag from this folder only, so next time a double-click just works.
    Get-ChildItem -LiteralPath $Here -Recurse -File -ErrorAction SilentlyContinue |
        Unblock-File -ErrorAction SilentlyContinue

    Get-Date | Out-File (Join-Path $RT "ready")
    Write-Host ""
    Write-Host "setup complete - opening malfunction" -ForegroundColor Green
    Write-Host ""
}

if ($env:MALFUNCTION_SETUP_ONLY) { Write-Host "setup only - not opening the app"; exit 0 }

& $Py (Join-Path $Here "malfunction_ui.py")
if ($LASTEXITCODE -ne 0) { Fail "malfunction exited with an error (see above)" }
