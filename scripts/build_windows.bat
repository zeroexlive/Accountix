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

REM Compile the gettext catalogs so the bundle ships .mo files next to
REM the committed .po sources (Sprint 19, ADR-045). Requires the
REM gettext tools (msgfmt) on the BUILD machine.
pushd backend
set DJANGO_SETTINGS_MODULE=config.settings.local
..\.venv-build\Scripts\python manage.py compilemessages
if errorlevel 1 exit /b 1
popd

.venv-build\Scripts\pyinstaller launcher\accountix.spec --noconfirm --distpath dist --workpath build\pyinstaller

echo Built: %CD%\dist\accountix\accountix.exe
endlocal
