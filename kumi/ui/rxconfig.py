import os

import reflex as rx

_backend_port = 8001
_api_host = os.getenv("KUMI_UI_API_HOST", "localhost")

config = rx.Config(
    app_name="ui",
    backend_port=_backend_port,
    api_url=f"http://{_api_host}:{_backend_port}",
    vite_allowed_hosts=True,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ],
)
