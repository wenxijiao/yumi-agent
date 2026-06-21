"""Allow ``python -m yumi.core.api`` to start the server.

This is the real entry point for `yumi --server` and Docker. It delegates to
``app_factory.run_app_from_env()`` so the bind address comes from YUMI_HOST /
YUMI_PORT (loopback by default) — do NOT hardcode the host here.
"""

import logging

from yumi.core.platform.env_load import load_yumi_dotenv

load_yumi_dotenv()

from yumi.core.api.app_factory import run_app_from_env

logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

run_app_from_env()
