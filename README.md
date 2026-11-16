# google-trends-mcp

MCP server for Google Trends. Single-file `uv` script, no API key: it uses the same
web endpoints as trends.google.com (unofficial, so Google can change or rate-limit them).

## Tools

| Tool | What it returns |
|---|---|
| `interest_over_time` | 0–100 interest over time for up to 5 keywords (or topic mids `/m/...`), with averages |
| `interest_by_region` | Interest per region/city, or per country when `geo=""` |
| `related_queries` | Top and rising related searches (`Breakout` = >5000% growth) |
| `trending_now` | What is trending in a country in the last ~24h, with traffic and news links |
| `suggestions` | Autocomplete: keywords and topics with their `mid` |

Common parameters: `geo` (`PT`, `PT-11`, `""` = worldwide), `timeframe`
(`now 7-d`, `today 3-m`, `today 12-m`, `today 5-y`, `all`, `2025-01-01 2025-06-30`),
`category` (numeric Trends category id), `property` (`web|images|news|youtube|shopping`).

Related *topics* is not exposed: Google tags these requests as `USER_TYPE_SCRAPER`
and always returns an empty topic list for them.

## Setup

```json
"google-trends": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--script", "/path/to/google-trends-mcp/server.py"],
  "env": { "TRENDS_DEFAULT_GEO": "PT", "TRENDS_HL": "pt-PT" }
}
```

Env: `TRENDS_DEFAULT_GEO` (default `PT`), `TRENDS_HL` (UI language, default `pt-PT`),
`TRENDS_TZ` (minutes offset, default `0`).

## Limits

Google answers 429 when hit too often; the server retries with backoff (up to ~30 s)
and caches explore results for 10 minutes. Values are relative (0–100), not search volumes.
