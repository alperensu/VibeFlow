@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SOURCE=https://github.com/alperensu/VibeFlow"

if not "%~1"=="" (
  set "SOURCE=%~1"
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1" -Source "%SOURCE%"

endlocal
