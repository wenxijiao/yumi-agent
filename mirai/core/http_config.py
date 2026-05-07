import os
from collections.abc import Sequence

DEFAULT_LOCAL_BROWSER_ORIGINS: tuple[str, ...] = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
    "https://127.0.0.1:3000",
    "https://localhost:3000",
    "https://127.0.0.1:8000",
    "https://localhost:8000",
    "https://127.0.0.1:8001",
    "https://localhost:8001",
)

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


def _parse_csv_list(raw_value: str | None) -> list[str]:
    if raw_value is None:
        return []
    normalized = raw_value.strip()
    if not normalized or normalized.lower() == "none":
        return []
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in _TRUE_ENV_VALUES


def get_cors_settings(
    origins_env_var: str,
    allow_credentials_env_var: str,
    *,
    default_origins: Sequence[str] = DEFAULT_LOCAL_BROWSER_ORIGINS,
) -> dict[str, object]:
    env_origins = os.getenv(origins_env_var)
    origins = _parse_csv_list(env_origins) if env_origins is not None else list(default_origins)
    allow_credentials = _parse_bool_env(allow_credentials_env_var, default=False)

    # Browsers reject wildcard origins together with credentialed requests; fail fast on misconfig
    # rather than silently demoting credentials, which produces a confusing CORS error in the browser.
    if "*" in origins and allow_credentials:
        raise ValueError(
            f"{origins_env_var}='*' cannot be combined with {allow_credentials_env_var}=true; "
            "list explicit origins or disable credentials."
        )

    return {
        "allow_origins": origins,
        "allow_credentials": allow_credentials,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
