#!/usr/bin/env python
"""Production-capable local server entrypoint for the standalone app.

Runs the Django application under Waitress, bound to 127.0.0.1 only.
Django's development server is never used as the application server
(master prompt section 4).

This module only *serves*. Database migrations, backups and static
collection are the launcher's job (launcher/accountix_launcher.py), so a
failed migration can never leave a half-upgraded app serving traffic.

Environment:
    DJANGO_SETTINGS_MODULE  defaults to config.settings.standalone
    ACCOUNTIX_PORT          port to bind (default 8765, see config.paths)
    ACCOUNTIX_THREADS       Waitress worker threads (default 8)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.standalone")
    from config.paths import configured_port
    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    port = configured_port()
    threads = int(os.environ.get("ACCOUNTIX_THREADS", "8"))
    application = get_wsgi_application()
    print(f"Accountix serving on http://127.0.0.1:{port} (Waitress, {threads} threads)")
    serve(application, host="127.0.0.1", port=port, threads=threads)


if __name__ == "__main__":
    main()
