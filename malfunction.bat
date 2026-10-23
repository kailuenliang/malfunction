@echo off
rem -------------------------------------------------------------------------
rem  malfunction - double-click to install (first time) and open the app.
rem
rem  Everything goes into the hidden .runtime folder next to this file:
rem  a private Python, its packages, ffmpeg and FFglitch. Nothing else on the
rem  computer is installed or changed. To uninstall, delete the malfunction folder.
rem -------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

rem Double-clicking inside a zip runs from a temporary folder that disappears.
set "HERE_DIR=%~dp0"
if /i not "%HERE_DIR:\AppData\Local\Temp\=%"=="%HERE_DIR%" (
  echo.
  echo It looks like malfunction is still inside the zip file.
  echo Right-click the zip, choose "Extract All...", then open malfunction.bat
  echo from the extracted folder.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo If you're stuck, send a screenshot of this window to your teacher.
  pause
  exit /b 1
)
endlocal
