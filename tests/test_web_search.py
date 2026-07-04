"""Provider chain, fallback, and parsing behavior of the web_search tool."""

import yumi.tools.search_providers as sp
from yumi.core.features.config.model import ModelConfig
from yumi.tools.search_providers import (
    SearchProviderError,
    SearchResponse,
    SearchResult,
    extract_text_from_html,
    normalize_time_range,
    parse_duckduckgo_html,
    provider_chain,
    run_web_search,
)


def _config(**kwargs) -> ModelConfig:
    return ModelConfig.model_validate(kwargs)


def test_normalize_time_range_aliases():
    assert normalize_time_range("day") == "day"
    assert normalize_time_range("W") == "week"
    assert normalize_time_range("m") == "month"
    assert normalize_time_range("YEAR") == "year"
    assert normalize_time_range("") == ""
    assert normalize_time_range("fortnight") == ""
    assert normalize_time_range(None) == ""


def test_provider_chain_keyless_defaults_to_duckduckgo():
    assert provider_chain(_config()) == ["duckduckgo"]


def test_provider_chain_auto_priority():
    config = _config(brave_search_api_key="b", serper_api_key="s", tavily_api_key="t")
    assert provider_chain(config) == ["tavily", "brave", "serper", "duckduckgo"]


def test_provider_chain_explicit_provider_goes_first():
    config = _config(
        search_provider="serper",
        tavily_api_key="t",
        serper_api_key="s",
    )
    assert provider_chain(config) == ["serper", "tavily", "duckduckgo"]


def test_provider_chain_explicit_but_unconfigured_falls_back_to_auto():
    # brave selected but no brave key saved — auto order applies.
    config = _config(search_provider="brave", tavily_api_key="t")
    assert provider_chain(config) == ["tavily", "duckduckgo"]


def test_search_provider_config_normalization():
    assert _config(search_provider="TAVILY").search_provider == "tavily"
    assert _config(search_provider="not-a-provider").search_provider == "auto"
    assert _config().search_provider == "auto"


def test_run_web_search_formats_results(monkeypatch):
    def fake_ddg(query, max_results, time_range):
        assert query == "auckland weather"
        assert time_range == "day"
        return SearchResponse(
            provider="duckduckgo",
            results=[
                SearchResult(title="MetService", url="https://metservice.com", snippet="Rain expected"),
                SearchResult(title="NIWA", url="https://niwa.co.nz", snippet="", published="2026-07-04"),
            ],
        )

    monkeypatch.setattr(sp, "_search_duckduckgo", fake_ddg)
    output = run_web_search("auckland weather", 5, "d", _config())
    assert "via duckduckgo" in output
    assert "1. MetService — Rain expected (https://metservice.com)" in output
    assert "2. NIWA (https://niwa.co.nz) [2026-07-04]" in output


def test_run_web_search_falls_back_when_provider_fails(monkeypatch):
    def failing_tavily(query, max_results, time_range, api_key):
        raise SearchProviderError("tavily", "401 unauthorized")

    def fake_ddg(query, max_results, time_range):
        return SearchResponse(
            provider="duckduckgo",
            results=[SearchResult(title="Result", url="https://example.com")],
        )

    monkeypatch.setattr(sp, "_search_tavily", failing_tavily)
    monkeypatch.setattr(sp, "_search_duckduckgo", fake_ddg)
    output = run_web_search("query", 3, "", _config(tavily_api_key="bad-key"))
    assert "via duckduckgo" in output
    assert "tavily: 401 unauthorized" in output


def test_run_web_search_reports_total_failure(monkeypatch):
    def failing_ddg(query, max_results, time_range):
        raise SearchProviderError("duckduckgo", "connection refused")

    monkeypatch.setattr(sp, "_search_duckduckgo", failing_ddg)
    output = run_web_search("query", 3, "", _config())
    assert output.startswith("Web search failed")
    assert "duckduckgo: connection refused" in output


def test_run_web_search_includes_answer(monkeypatch):
    def fake_tavily(query, max_results, time_range, api_key):
        return SearchResponse(
            provider="tavily",
            results=[SearchResult(title="T", url="https://t.example")],
            answer="42 is the answer.",
        )

    monkeypatch.setattr(sp, "_search_tavily", fake_tavily)
    output = run_web_search("meaning of life", 3, "", _config(tavily_api_key="k"))
    assert "via tavily" in output
    assert "Answer: 42 is the answer." in output


DDG_SAMPLE_HTML = """
<html><body>
<div class="result results_links">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews&rut=abc">Example <b>News</b></a>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Latest &amp; greatest headlines today.</a>
</div>
<div class="result result--ad">
  <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_provider=x">Sponsored thing</a>
</div>
<div class="result results_links">
  <a rel="nofollow" class="result__a" href="https://plain.example/page">Plain link</a>
  <div class="result__snippet">Second snippet.</div>
</div>
</body></html>
"""


def test_parse_duckduckgo_html_extracts_results_and_skips_ads():
    results = parse_duckduckgo_html(DDG_SAMPLE_HTML, 10)
    assert len(results) == 2
    assert results[0].title == "Example News"
    assert results[0].url == "https://example.com/news"
    assert results[0].snippet == "Latest & greatest headlines today."
    assert results[1].title == "Plain link"
    assert results[1].url == "https://plain.example/page"
    assert results[1].snippet == "Second snippet."


def test_parse_duckduckgo_html_respects_max_results():
    assert len(parse_duckduckgo_html(DDG_SAMPLE_HTML, 1)) == 1


def test_extract_text_from_html_strips_chrome():
    page = """
    <html><head><title>My Article</title><style>.x{color:red}</style></head>
    <body><script>alert(1)</script>
    <h1>Heading</h1><p>First paragraph.</p><p>Second &amp; final.</p>
    </body></html>
    """
    title, text = extract_text_from_html(page)
    assert title == "My Article"
    assert "Heading" in text
    assert "First paragraph." in text
    assert "Second & final." in text
    assert "alert(1)" not in text
    assert "color:red" not in text


def test_web_search_rejects_empty_query():
    from yumi.tools.web_tools import web_search

    assert web_search("   ") == "Search query cannot be empty."


def test_fetch_webpage_rejects_non_http():
    from yumi.tools.web_tools import fetch_webpage

    assert "only http/https" in fetch_webpage("file:///etc/passwd")
    assert fetch_webpage("  ") == "URL cannot be empty."


def test_fetch_webpage_rejects_private_and_metadata_urls():
    from yumi.tools.web_tools import fetch_webpage

    assert "not allowed" in fetch_webpage("http://127.0.0.1:8000/admin")
    assert "not allowed" in fetch_webpage("http://10.0.0.2/admin")
    assert "not allowed" in fetch_webpage("http://169.254.169.254/latest/meta-data")
    assert "not allowed" in fetch_webpage("http://metadata.google.internal/computeMetadata/v1/")


def test_fetch_webpage_blocks_private_redirect(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        assert host == "example.com"
        return [(sp.socket.AF_INET, sp.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return sp.httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            request=sp.httpx.Request("GET", url),
        )

    monkeypatch.setattr(sp.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(sp.httpx, "get", fake_get)

    output = sp.fetch_page_text("https://example.com/start", 1000)

    assert "not allowed" in output
    assert calls == ["https://example.com/start"]
