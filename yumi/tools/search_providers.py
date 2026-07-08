"""Pluggable web-search provider layer behind the ``web_search`` tool.

Provider selection is driven by ``ModelConfig.search_provider``:

* ``auto`` (default) — try the first *configured* provider in priority order
  ``tavily > brave > serper > searxng``, always keeping the keyless
  DuckDuckGo HTML endpoint as the final fallback.
* an explicit provider name — that provider is tried first; the remaining
  configured providers (and DuckDuckGo) stay available as fallbacks.

Every provider maps to real web results (title / URL / snippet, optionally a
publish date), unlike the old DuckDuckGo Instant Answer API which only served
encyclopedia-style abstracts and missed anything recent.
"""

from __future__ import annotations

import html as html_module
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

import httpx

REQUEST_TIMEOUT_SECONDS = 12
USER_AGENT = "Mozilla/5.0 (compatible; YumiAgent/0.1)"
# Page fetches use a browser-like UA: many news/article sites 403 anything
# that self-identifies as a bot, and fetch_webpage exists to read exactly those.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Accepted values for the web_search ``time_range`` argument (aliases included).
_TIME_RANGE_ALIASES = {
    "d": "day",
    "day": "day",
    "w": "week",
    "week": "week",
    "m": "month",
    "month": "month",
    "y": "year",
    "year": "year",
}

_SNIPPET_MAX_CHARS = 320
_TAG_RE = re.compile(r"<[^>]+>")
_FETCH_REDIRECT_LIMIT = 5
_BLOCKED_FETCH_HOSTS = {"metadata", "metadata.google.internal"}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published: str = ""


@dataclass
class SearchResponse:
    provider: str
    results: list[SearchResult] = field(default_factory=list)
    answer: str = ""


SearchCallable = Callable[[str, int, str], SearchResponse]


class SearchProviderError(Exception):
    """A single provider failed; the orchestrator falls through to the next one."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"{provider}: {message}")


def normalize_time_range(time_range: str | None) -> str:
    return _TIME_RANGE_ALIASES.get((time_range or "").strip().lower(), "")


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html_module.unescape(_TAG_RE.sub(" ", str(value)))
    return re.sub(r"\s+", " ", text).strip()


def _http_get(url: str, *, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    response = httpx.get(
        url,
        params=params,
        headers=merged,
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response


def _http_post_json(url: str, payload: dict, *, headers: dict | None = None) -> dict:
    merged = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if headers:
        merged.update(headers)
    response = httpx.post(url, json=payload, headers=merged, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("unexpected response shape")
    return data


class FetchUrlBlocked(ValueError):
    """The model supplied a URL that should not be fetched by the server."""


def _is_public_ip_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _assert_public_http_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise FetchUrlBlocked(f"Cannot fetch '{url}': only http/https URLs are supported.")

    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchUrlBlocked(f"Cannot fetch '{url}': URL must include a host.")
    if host in _BLOCKED_FETCH_HOSTS:
        raise FetchUrlBlocked(f"Cannot fetch '{url}': private, local, and cloud metadata URLs are not allowed.")

    try:
        public_host_ip = _is_public_ip_address(host)
    except ValueError:
        pass
    else:
        if not public_host_ip:
            raise FetchUrlBlocked(f"Cannot fetch '{url}': private, local, and cloud metadata URLs are not allowed.")
        return

    try:
        resolved = socket.getaddrinfo(
            host,
            parts.port or (443 if parts.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise FetchUrlBlocked(f"Cannot fetch '{url}': host could not be resolved ({exc}).") from exc

    addresses = {item[4][0] for item in resolved if item and len(item) >= 5 and item[4]}
    if not addresses:
        raise FetchUrlBlocked(f"Cannot fetch '{url}': host could not be resolved.")

    for address in addresses:
        try:
            public = _is_public_ip_address(address)
        except ValueError:
            public = False
        if not public:
            raise FetchUrlBlocked(f"Cannot fetch '{url}': private, local, and cloud metadata URLs are not allowed.")


def _http_get_public_page(url: str, *, headers: dict | None = None) -> httpx.Response:
    merged = {"User-Agent": BROWSER_USER_AGENT}
    if headers:
        merged.update(headers)

    current_url = url
    for _ in range(_FETCH_REDIRECT_LIMIT + 1):
        _assert_public_http_url(current_url)
        response = httpx.get(
            current_url,
            headers=merged,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                response.raise_for_status()
                return response
            current_url = urljoin(current_url, location)
            continue
        response.raise_for_status()
        return response

    raise FetchUrlBlocked(f"Cannot fetch '{url}': too many redirects.")


# ── providers ──


def _search_tavily(query: str, max_results: int, time_range: str, api_key: str) -> SearchResponse:
    payload: dict = {
        "query": query,
        "max_results": max_results,
        "include_answer": True,
    }
    if time_range:
        payload["time_range"] = time_range
    try:
        data = _http_post_json(
            "https://api.tavily.com/search",
            payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as exc:
        raise SearchProviderError("tavily", str(exc)) from exc

    results = [
        SearchResult(
            title=_clean_text(item.get("title")),
            url=str(item.get("url") or ""),
            snippet=_clean_text(item.get("content"))[:_SNIPPET_MAX_CHARS],
            published=_clean_text(item.get("published_date")),
        )
        for item in data.get("results") or []
        if isinstance(item, dict) and item.get("url")
    ]
    return SearchResponse(provider="tavily", results=results, answer=_clean_text(data.get("answer")))


def _search_brave(query: str, max_results: int, time_range: str, api_key: str) -> SearchResponse:
    params = {"q": query, "count": max_results}
    freshness = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}.get(time_range)
    if freshness:
        params["freshness"] = freshness
    try:
        response = _http_get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        data = response.json()
    except Exception as exc:
        raise SearchProviderError("brave", str(exc)) from exc

    items = (data.get("web") or {}).get("results") or [] if isinstance(data, dict) else []
    results = [
        SearchResult(
            title=_clean_text(item.get("title")),
            url=str(item.get("url") or ""),
            snippet=_clean_text(item.get("description"))[:_SNIPPET_MAX_CHARS],
            published=_clean_text(item.get("age") or item.get("page_age")),
        )
        for item in items
        if isinstance(item, dict) and item.get("url")
    ]
    return SearchResponse(provider="brave", results=results)


def _search_serper(query: str, max_results: int, time_range: str, api_key: str) -> SearchResponse:
    payload: dict = {"q": query, "num": max_results}
    tbs = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}.get(time_range)
    if tbs:
        payload["tbs"] = tbs
    try:
        data = _http_post_json(
            "https://google.serper.dev/search",
            payload,
            headers={"X-API-KEY": api_key},
        )
    except Exception as exc:
        raise SearchProviderError("serper", str(exc)) from exc

    answer = ""
    answer_box = data.get("answerBox")
    if isinstance(answer_box, dict):
        answer = _clean_text(answer_box.get("answer") or answer_box.get("snippet"))

    results = [
        SearchResult(
            title=_clean_text(item.get("title")),
            url=str(item.get("link") or ""),
            snippet=_clean_text(item.get("snippet"))[:_SNIPPET_MAX_CHARS],
            published=_clean_text(item.get("date")),
        )
        for item in data.get("organic") or []
        if isinstance(item, dict) and item.get("link")
    ]
    return SearchResponse(provider="serper", results=results, answer=answer)


def _search_searxng(query: str, max_results: int, time_range: str, base_url: str) -> SearchResponse:
    params: dict = {"q": query, "format": "json"}
    if time_range:
        params["time_range"] = time_range
    try:
        response = _http_get(f"{base_url.rstrip('/')}/search", params=params)
        data = response.json()
    except Exception as exc:
        raise SearchProviderError("searxng", str(exc)) from exc

    items = data.get("results") or [] if isinstance(data, dict) else []
    results = [
        SearchResult(
            title=_clean_text(item.get("title")),
            url=str(item.get("url") or ""),
            snippet=_clean_text(item.get("content"))[:_SNIPPET_MAX_CHARS],
            published=_clean_text(item.get("publishedDate")),
        )
        for item in items[:max_results]
        if isinstance(item, dict) and item.get("url")
    ]
    return SearchResponse(provider="searxng", results=results)


class _DuckDuckGoHtmlParser(HTMLParser):
    """Extracts (title, url, snippet) triples from html.duckduckgo.com/html markup.

    Result links carry class ``result__a``; snippets carry class ``result__snippet``.
    Ad results link through ``duckduckgo.com/y.js`` and are skipped.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._in_title = False
        self._in_snippet = False
        self._current_title: list[str] = []
        self._current_url = ""
        self._current_snippet: list[str] = []

    @staticmethod
    def _resolve_href(href: str) -> str:
        # DDG wraps targets as //duckduckgo.com/l/?uddg=<urlencoded-target>&...
        if "uddg=" in href:
            query = urlsplit(href).query
            target = parse_qs(query).get("uddg", [""])[0]
            if target:
                return target
        return href

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            href = self._resolve_href(attrs_dict.get("href") or "")
            if "duckduckgo.com/y.js" in href:
                return
            self._flush()
            self._in_title = True
            self._current_url = href
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag):
        if self._in_title and tag == "a":
            self._in_title = False
        elif self._in_snippet and tag in ("a", "div", "td", "span"):
            self._in_snippet = False

    def handle_data(self, data):
        if self._in_title:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)

    def _flush(self) -> None:
        if self._current_url and self._current_title:
            self.results.append(
                SearchResult(
                    title=_clean_text("".join(self._current_title)),
                    url=self._current_url,
                    snippet=_clean_text("".join(self._current_snippet))[:_SNIPPET_MAX_CHARS],
                )
            )
        self._current_title = []
        self._current_url = ""
        self._current_snippet = []

    def close(self) -> None:
        super().close()
        self._flush()


def parse_duckduckgo_html(page: str, max_results: int) -> list[SearchResult]:
    parser = _DuckDuckGoHtmlParser()
    parser.feed(page)
    parser.close()
    return parser.results[:max_results]


def _search_duckduckgo(query: str, max_results: int, time_range: str) -> SearchResponse:
    params: dict = {"q": query}
    df = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(time_range)
    if df:
        params["df"] = df
    try:
        response = _http_get("https://html.duckduckgo.com/html/", params=params)
        results = parse_duckduckgo_html(response.text, max_results)
    except Exception as exc:
        raise SearchProviderError("duckduckgo", str(exc)) from exc
    return SearchResponse(provider="duckduckgo", results=results)


# ── orchestration ──

SUPPORTED_SEARCH_PROVIDERS = ("auto", "tavily", "brave", "serper", "searxng", "duckduckgo")

# auto-mode priority; duckduckgo is appended last as the keyless fallback.
_AUTO_PRIORITY = ("tavily", "brave", "serper", "searxng")


def _configured_providers(config) -> dict[str, SearchCallable]:
    """Map provider name → zero-config-arg search callable for providers usable right now."""
    available: dict[str, SearchCallable] = {}
    tavily_key = (config.tavily_api_key or "").strip()
    if tavily_key:
        available["tavily"] = lambda q, n, t: _search_tavily(q, n, t, tavily_key)
    brave_key = (config.brave_search_api_key or "").strip()
    if brave_key:
        available["brave"] = lambda q, n, t: _search_brave(q, n, t, brave_key)
    serper_key = (config.serper_api_key or "").strip()
    if serper_key:
        available["serper"] = lambda q, n, t: _search_serper(q, n, t, serper_key)
    searxng_url = (config.searxng_base_url or "").strip()
    if searxng_url:
        available["searxng"] = lambda q, n, t: _search_searxng(q, n, t, searxng_url)
    available["duckduckgo"] = _search_duckduckgo
    return available


def provider_chain(config) -> list[str]:
    """Ordered provider names to attempt for this configuration."""
    available = _configured_providers(config)
    chain = [name for name in _AUTO_PRIORITY if name in available]
    chain.append("duckduckgo")

    selected = (getattr(config, "search_provider", "auto") or "auto").strip().lower()
    if selected != "auto" and selected in available:
        chain.remove(selected)
        chain.insert(0, selected)
    return chain


def run_web_search(query: str, max_results: int, time_range: str, config) -> str:
    """Execute the provider chain and format results for the model."""
    time_range = normalize_time_range(time_range)
    available = _configured_providers(config)
    chain = provider_chain(config)

    errors: list[str] = []
    response: SearchResponse | None = None
    for name in chain:
        try:
            candidate = available[name](query, max_results, time_range)
        except SearchProviderError as exc:
            errors.append(str(exc))
            continue
        if candidate.results or candidate.answer:
            response = candidate
            break
        errors.append(f"{name}: no results")

    if response is None:
        return (
            f"Web search failed for '{query}'.\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\nCheck the search provider configuration (see `search_provider` in ~/.yumi/config.json)."
        )

    lines = [f"Web search results for '{query}' (via {response.provider}):"]
    if response.answer:
        lines.append(f"Answer: {response.answer}")
    for index, item in enumerate(response.results[:max_results], start=1):
        entry = item.title or item.url
        if item.snippet:
            entry += f" — {item.snippet}"
        if item.url:
            entry += f" ({item.url})"
        if item.published:
            entry += f" [{item.published}]"
        lines.append(f"{index}. {entry}")
    if errors:
        lines.append("Note: earlier providers failed: " + "; ".join(errors))
    return "\n".join(lines)


# ── page fetching (used by the fetch_webpage tool) ──


class _TextExtractor(HTMLParser):
    """Strips markup, skipping script/style/nav chrome, and keeps block spacing."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def extract_text_from_html(page: str) -> tuple[str, str]:
    """Return (title, readable_text) for an HTML document."""
    extractor = _TextExtractor()
    extractor.feed(page)
    extractor.close()
    return _clean_text(extractor.title), extractor.text()


def fetch_page_text(url: str, max_chars: int) -> str:
    try:
        response = _http_get_public_page(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "en,zh;q=0.8",
            },
        )
    except FetchUrlBlocked as exc:
        return str(exc)
    except Exception as exc:
        return f"Failed to fetch '{url}': {exc}"

    content_type = response.headers.get("content-type", "")
    body = response.text
    if "html" in content_type or "<html" in body[:2000].lower():
        title, text = extract_text_from_html(body)
    else:
        title, text = "", body

    if not text.strip():
        return f"Fetched '{url}' but found no readable text (content-type: {content_type or 'unknown'})."

    truncated = len(text) > max_chars
    text = text[:max_chars]
    header = f"Content of {url}"
    if title:
        header += f" — {title}"
    footer = f"\n[Truncated at {max_chars} characters]" if truncated else ""
    return f"{header}:\n\n{text}{footer}"


def duckduckgo_search_url(query: str) -> str:
    """Human-facing search URL (handy for 'see more results' style replies)."""
    return f"https://duckduckgo.com/?q={quote_plus(query)}"
