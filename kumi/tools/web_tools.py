import json
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 10


def _fetch_json(url: str):
    request = Request(
        url,
        headers={
            "User-Agent": "Kumi/0.1 (+https://github.com/)",
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


def _flatten_related_topics(topics):
    flattened = []
    for item in topics:
        if "Topics" in item:
            flattened.extend(_flatten_related_topics(item["Topics"]))
        else:
            flattened.append(item)
    return flattened


def web_search(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "Search query cannot be empty."

    max_results = max(1, min(max_results, 10))

    ddg_query = urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    ddg_url = f"https://api.duckduckgo.com/?{ddg_query}"

    results = []
    errors = []

    try:
        data = _fetch_json(ddg_url)

        abstract_text = (data.get("AbstractText") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        if abstract_text:
            line = abstract_text
            if abstract_url:
                line += f" ({abstract_url})"
            results.append(line)

        answer = (data.get("Answer") or "").strip()
        answer_url = (data.get("AnswerType") or "").strip()
        if answer and answer not in results:
            suffix = f" [answer_type={answer_url}]" if answer_url else ""
            results.append(answer + suffix)

        for item in _flatten_related_topics(data.get("RelatedTopics", [])):
            text = (item.get("Text") or "").strip()
            first_url = (item.get("FirstURL") or "").strip()
            if not text:
                continue
            line = text
            if first_url:
                line += f" ({first_url})"
            results.append(line)
            if len(results) >= max_results:
                break
    except Exception as e:
        errors.append(f"DuckDuckGo lookup failed: {e}")

    if len(results) < max_results:
        try:
            wiki_query = urlencode(
                {
                    "action": "opensearch",
                    "search": query,
                    "limit": max_results,
                    "namespace": "0",
                    "format": "json",
                }
            )
            wiki_url = f"https://en.wikipedia.org/w/api.php?{wiki_query}"
            wiki_data = _fetch_json(wiki_url)

            titles = wiki_data[1] if len(wiki_data) > 1 else []
            descriptions = wiki_data[2] if len(wiki_data) > 2 else []
            urls = wiki_data[3] if len(wiki_data) > 3 else []

            for title, description, url in zip(titles, descriptions, urls):
                line = title
                if description:
                    line += f": {description}"
                if url:
                    line += f" ({url})"
                if line not in results:
                    results.append(line)
                if len(results) >= max_results:
                    break
        except Exception as e:
            errors.append(f"Wikipedia lookup failed: {e}")

    if results:
        lines = [f"Web search results for '{query}':"]
        for index, item in enumerate(results[:max_results], start=1):
            lines.append(f"{index}. {item}")
        return "\n".join(lines)

    if errors:
        return "Web search failed.\n" + "\n".join(errors)

    return f"No useful web results found for '{query}'."


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
