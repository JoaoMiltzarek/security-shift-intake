"""Production ASGI entry point.

Importing :mod:`src.api.app` exposes only the application factory and therefore
does not open or migrate the operational database. ASGI servers import this
module when they intentionally want to start the application.
"""

from src.api.app import create_app

app = create_app()
