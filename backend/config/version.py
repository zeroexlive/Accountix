"""The Accountix product version — the ONE source of truth (Sprint 27,
ADR-052).

Both source runs and the frozen PyInstaller bundle import this module
(it ships inside the application package tree), so the version shown
in the shell and on the login page is identical in both. The
``[project] version`` in pyproject.toml mirrors this value for
packaging metadata only; this module is what the running app reads.
"""

__version__ = "1.1.0"
VERSION = __version__
