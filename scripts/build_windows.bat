@echo off
REM Build the Accountix standalone bundle for Windows (Sprint 09).
REM Produces dist\accountix\accountix.exe (onedir). See docs\deployment\WINDOWS.md.
REM NOTE: written on Linux; not yet exercised on a Windows machine.
setlocal
cd /d "%~dp0\.."

if not defined PYTHON set PYTHON=py -3.12
%PYTHON% -m venv .venv-build
.venv-build\Scripts\pip install --upgrade pip
.venv-build\Scripts\pip install -e ".[dev]"

.venv-build\Scripts\pyinstaller launcher\accountix.spec --noconfirm --distpath dist --workpath build\pyinstaller

echo Built: %CD%\dist\accountix\accountix.exe
endlocal
