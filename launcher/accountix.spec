# PyInstaller spec for the Accountix standalone bundle (Sprint 09).
#
# Build (Linux):   scripts/build_linux.sh
# Build (Windows): scripts\build_windows.bat   (written, untested on Linux)
#
# Layout produced (onedir):
#   dist/accountix/accountix[.exe]   <- the launcher
#   dist/accountix/_internal/backend/{templates,static,locale,...}
#
# The launcher runs Django in-process when frozen; templates/static/locale
# must therefore be present as real files, and Django's apps/config/serve
# modules must be importable from the bundle (pathex + hidden imports).

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO_ROOT = os.path.dirname(SPEC_DIR)
BACKEND = os.path.join(REPO_ROOT, "backend")

# collect_submodules() resolves against the *build* interpreter's sys.path,
# which does not include pathex — without this, apps.* and config.settings.*
# (loaded by Django via string names, invisible to static analysis) are
# silently missing from the bundle.
sys.path.insert(0, BACKEND)

hiddenimports = (
    collect_submodules("apps")
    + collect_submodules("config")
    # django-axes (Sprint 16) is referenced from settings only by string
    # (axes.middleware.AxesMiddleware, axes.backends.AxesStandaloneBackend)
    # and its migrations are loaded by Django by name — static analysis
    # follows none of that, so without this the frozen bundle ships axes
    # without its middleware, backend or migrations (found by the Sprint 23
    # rebuild census of the PYZ archive).
    + collect_submodules("axes")
    + ["config.settings.standalone", "config.settings.base"]
    + [
        "serve",
        "whitenoise",
        "whitenoise.middleware",
        "whitenoise.storage",
        "waitress",
        "rest_framework",
    ]
)

# Destinations intentionally drop the "backend/" prefix: in the bundle the
# config package sits at the _internal root, so Django's BASE_DIR (parents[2]
# of config/settings/base.py) resolves to _internal/ and its template/static/
# locale dirs must live directly under it.
datas = [
    (os.path.join(BACKEND, "templates"), "templates"),
    (os.path.join(BACKEND, "static"), "static"),
    (os.path.join(BACKEND, "locale"), "locale"),
    (os.path.join(BACKEND, "manage.py"), "."),
]

a = Analysis(
    [os.path.join(SPEC_DIR, "accountix_launcher.py")],
    pathex=[BACKEND],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="accountix",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="accountix",
)
