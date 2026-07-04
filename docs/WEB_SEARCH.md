# Web Search

The built-in `web_search` tool queries real search engines through a pluggable
provider layer (`yumi/tools/search_providers.py`). It works with **zero
configuration** — the keyless DuckDuckGo HTML endpoint is always available as
the final fallback — but configuring a dedicated provider gives noticeably
better results, especially for recent news.

## Providers

| Provider | Needs | Notes |
| --- | --- | --- |
| `tavily` | API key ([tavily.com](https://tavily.com), free tier ~1000 req/mo) | Built for LLM agents; returns a synthesized `Answer:` line plus results. |
| `brave` | API key ([brave.com/search/api](https://brave.com/search/api), free tier ~2000 req/mo) | Independent index, good freshness. |
| `serper` | API key ([serper.dev](https://serper.dev)) | Google results; strong for non-English queries. |
| `searxng` | Base URL of a self-hosted [SearXNG](https://docs.searxng.org) instance (JSON format enabled) | No key, fully self-hosted. |
| `duckduckgo` | Nothing | Keyless fallback; parses the DuckDuckGo HTML endpoint. |

## Selection and fallback

`search_provider` in `~/.yumi/config.json` (or `YUMI_SEARCH_PROVIDER`) is one of
`auto | tavily | brave | serper | searxng | duckduckgo`.

- `auto` (default): the first *configured* provider in the order
  `tavily > brave > serper > searxng`, with `duckduckgo` last.
- An explicit name moves that provider to the front of the chain.

If a provider errors or returns nothing, the next one in the chain is tried
automatically; the tool output notes which providers failed.

## Configuration

`~/.yumi/config.json` keys (also settable via `PUT /config/model`):

```json
{
  "search_provider": "auto",
  "tavily_api_key": null,
  "brave_search_api_key": null,
  "serper_api_key": null,
  "searxng_base_url": null
}
```

Environment overrides: `YUMI_SEARCH_PROVIDER`, `TAVILY_API_KEY`,
`BRAVE_SEARCH_API_KEY`, `SERPER_API_KEY`, `SEARXNG_BASE_URL`.

## Tool surface

- `web_search(query, max_results=5, time_range="")` — `time_range` accepts
  `day | week | month | year` (or `d/w/m/y`) and maps to each provider's
  freshness filter; the model is instructed to use it for news-style queries.
- `fetch_webpage(url, max_chars=6000)` — fetches a result URL and returns the
  page title plus readable text (markup, scripts, and styles stripped), so the
  model can read full articles instead of relying on snippets. Only public
  http(s) URLs are fetched; local, private-network, and cloud metadata URLs are
  blocked.
