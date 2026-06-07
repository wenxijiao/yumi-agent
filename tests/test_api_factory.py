"""FastAPI app factory smoke tests (no server startup)."""

from yumi.core.api import app, create_app


def test_create_app_returns_module_singleton():
    assert create_app() is app
