"""Allow ``python -m yumi.core.api`` to start the server."""

import logging

from yumi.core.platform.env_load import load_yumi_dotenv

load_yumi_dotenv()

import uvicorn
from yumi.core.api.app_factory import app

logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False, log_level="warning")
