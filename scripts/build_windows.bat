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

REM --- Release packaging (Sprint 29, ADR-054) --------------------------
REM NOT VERIFIED: this packaging block was written on Linux alongside
REM scripts\package_release.sh and has never run on a Windows machine.
REM It mirrors the Linux naming: release\accountix-<VERSION>-windows.zip
REM with a single top folder accountix-<VERSION>-windows\ holding the
REM bundle plus the operator docs. <VERSION> is read from
REM backend\config\version.py (the one source of truth, ADR-052) and
REM is never hardcoded here.
set "VERSION="
for /f "tokens=3 delims= " %%v in ('findstr /b /c:"__version__" backend\config\version.py') do set "VERSION=%%~v"
if "%VERSION%"=="" (
    echo Could not read the version from backend\config\version.py - skipping release packaging.
    goto :packaged
)
set "PKG_NAME=accountix-%VERSION%-windows"
if exist "build\%PKG_NAME%" rmdir /s /q "build\%PKG_NAME%"
mkdir "build\%PKG_NAME%"
xcopy /e /i /q "dist\accountix" "build\%PKG_NAME%" >nul
copy /y "docs\deployment\LOCAL.md" "build\%PKG_NAME%\" >nul
copy /y "docs\deployment\UPGRADE.md" "build\%PKG_NAME%\" >nul
if not exist release mkdir release
powershell -NoProfile -Command "Compress-Archive -Path 'build\%PKG_NAME%' -DestinationPath 'release\%PKG_NAME%.zip' -Force"
echo Release artifact: %CD%\release\%PKG_NAME%.zip
:packaged
endlocal
