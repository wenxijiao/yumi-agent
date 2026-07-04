import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from yumi.tools.search_providers import fetch_page_text, run_web_search

DEFAULT_TIMEOUT_SECONDS = 10


def _fetch_json(url: str):
    request = Request(
        url,
        headers={
            "User-Agent": "Yumi/0.1 (+https://github.com/)",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _first_dict(value):
    if isinstance(value, list) and value:
        first_item = value[0]
        return first_item if isinstance(first_item, dict) else {}
    return value if isinstance(value, dict) else {}


def _first_value(items):
    item = _first_dict(items)
    value = item.get("value")
    return value.strip() if isinstance(value, str) else ""


def web_search(query: str, max_results: int = 5, time_range: str = "") -> str:
    if not query.strip():
        return "Search query cannot be empty."

    max_results = max(1, min(max_results, 10))

    # Imported lazily so importing web_tools never pulls the config stack
    # (tests and edge tooling import this module standalone).
    from yumi.core.features.config import load_model_config

    config = load_model_config()
    return run_web_search(query.strip(), max_results, time_range, config)


def fetch_webpage(url: str, max_chars: int = 6000) -> str:
    if not url.strip():
        return "URL cannot be empty."
    max_chars = max(500, min(max_chars, 30000))
    return fetch_page_text(url.strip(), max_chars)


def get_weather(location: str) -> str:
    if not location.strip():
        return "Location cannot be empty."

    url = f"https://wttr.in/{quote(location)}?format=j1"

    try:
        data = _fetch_json(url)
    except Exception as e:
        return f"Weather lookup failed for '{location}': {e}"

    if not isinstance(data, dict):
        return f"Weather lookup failed for '{location}': unexpected response format."

    current = _first_dict(data.get("current_condition"))
    weather = _first_dict(data.get("weather"))
    nearest = _first_dict(data.get("nearest_area"))

    resolved_location = _first_value(nearest.get("areaName")) or location
    country = _first_value(nearest.get("country"))
    region = _first_value(nearest.get("region"))

    feels_like_c = current.get("FeelsLikeC", "unknown")
    temp_c = current.get("temp_C", "unknown")
    humidity = current.get("humidity", "unknown")
    wind_kmph = current.get("windspeedKmph", "unknown")
    description = _first_value(current.get("weatherDesc")) or "Unknown"
    max_temp_c = weather.get("maxtempC", "unknown")
    min_temp_c = weather.get("mintempC", "unknown")

    location_parts = [part for part in [resolved_location, region, country] if part]
    resolved_text = ", ".join(location_parts) if location_parts else location

    return (
        f"Current weather for {resolved_text}: {description}. "
        f"Temperature: {temp_c} C, feels like {feels_like_c} C. "
        f"Humidity: {humidity}%. Wind speed: {wind_kmph} km/h. "
        f"Today's range: {min_temp_c} C to {max_temp_c} C."
    )
