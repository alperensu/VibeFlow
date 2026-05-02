@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%cd%"

if not "%~1"=="" (
  set "PROJECT_ROOT=%~1"
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%vibeflow.ps1" -ProjectRoot "%PROJECT_ROOT%"

endlocal
