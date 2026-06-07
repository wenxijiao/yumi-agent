"""Allow ``python -m kumi.core.api`` to start the server."""

import logging

from kumi.core.env_load import load_kumi_dotenv

load_kumi_dotenv()

import uvicorn
from kumi.core.api.app_factory import app

logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False, log_level="warning")
