# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "httpx>=0.27"]
# ///
"""MCP server for Google Trends (unofficial web endpoints, no API key)."""
import json
import logging
import os
import random
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

BASE = "https://trends.google.com"
HL = os.environ.get("TRENDS_HL", "pt-PT")
DEFAULT_GEO = os.environ.get("TRENDS_DEFAULT_GEO", "PT")
TZ = os.environ.get("TRENDS_TZ", "0")  # minutes offset from UTC, Google style
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
PROPERTIES = {"web": "", "images": "images", "news": "news", "youtube": "youtube", "shopping": "froogle"}

logging.getLogger("httpx").setLevel(logging.WARNING)
mcp = FastMCP("google-trends")
_client: httpx.Client | None = None
_cache: dict[str, tuple[float, dict]] = {}


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": UA, "Accept-Language": HL},
                               timeout=20, follow_redirects=True)
        _client.get(f"{BASE}/trends/?geo={DEFAULT_GEO}")  # obtains NID cookie
    return _client


def _get(path: str, params: dict | None = None, raw: bool = False):
    for attempt in range(5):
        r = client().get(BASE + path, params=params)
        if r.status_code == 429:
            time.sleep(2 ** attempt + random.random())
            continue
        r.raise_for_status()
        if raw:
            return r.text
        body = r.text
        return json.loads(body[body.index("{"):] if body.lstrip().startswith(")]}'") else body)
    raise RuntimeError("Google Trends rate limit (429). Try again in a minute.")


def _explore(keywords: list[str], geo: str, timeframe: str, category: int, prop: str) -> dict:
    if not 1 <= len(keywords) <= 5:
        raise ValueError("Pass between 1 and 5 keywords.")
    if prop not in PROPERTIES:
        raise ValueError(f"property must be one of {list(PROPERTIES)}")
    req = {"comparisonItem": [{"keyword": k, "geo": geo, "time": timeframe} for k in keywords],
           "category": category, "property": PROPERTIES[prop]}
    key = json.dumps(req, sort_keys=True)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    data = _get("/trends/api/explore", {"hl": HL, "tz": TZ, "req": json.dumps(req)})
    _cache[key] = (time.time(), data)
    return data


def _widget_data(widget: dict, endpoint: str) -> dict:
    return _get(f"/trends/api/widgetdata/{endpoint}",
                {"hl": HL, "tz": TZ, "req": json.dumps(widget["request"]), "token": widget["token"]})


def _widgets(data: dict, wid: str) -> list[dict]:
    return [w for w in data["widgets"] if w["id"].startswith(wid)]


@mcp.tool()
def interest_over_time(keywords: list[str], geo: str = DEFAULT_GEO, timeframe: str = "today 12-m",
                       category: int = 0, property: str = "web") -> dict:
    """Relative search interest (0-100) over time for up to 5 keywords or topic ids (/m/...).

    geo: ISO country ('PT'), region ('PT-11') or '' for worldwide.
    timeframe: 'now 1-H', 'now 7-d', 'today 1-m', 'today 3-m', 'today 12-m', 'today 5-y', 'all',
               or 'YYYY-MM-DD YYYY-MM-DD'.
    property: web | images | news | youtube | shopping.
    """
    data = _explore(keywords, geo, timeframe, category, property)
    w = _widgets(data, "TIMESERIES")[0]
    res = _widget_data(w, "multiline")["default"]
    points = [{"date": p["formattedTime"],
               **{k: v for k, v in zip(keywords, p["value"])},
               **({"partial": True} if p.get("isPartial") else {})}
              for p in res["timelineData"]]
    avg = res.get("averages") or []
    return {"keywords": keywords, "geo": geo or "worldwide", "timeframe": timeframe,
            "averages": dict(zip(keywords, avg)) if avg else None, "points": points}


@mcp.tool()
def interest_by_region(keywords: list[str], geo: str = DEFAULT_GEO, timeframe: str = "today 12-m",
                       resolution: str = "", category: int = 0, property: str = "web",
                       limit: int = 50) -> dict:
    """Search interest broken down by sub-region (or by country when geo='').

    resolution: '' (auto), 'COUNTRY', 'REGION', 'CITY' or 'DMA'.
    """
    data = _explore(keywords, geo, timeframe, category, property)
    w = _widgets(data, "GEO_MAP")[0]
    if resolution:
        w["request"]["resolution"] = resolution
    rows = _widget_data(w, "comparedgeo")["default"]["geoMapData"]
    out = [{"name": r["geoName"], "code": r.get("geoCode"),
            **{k: v for k, v in zip(keywords, r["value"])}}
           for r in rows if r.get("hasData", [True])[0] or any(r["value"])]
    out.sort(key=lambda r: -r[keywords[0]])
    return {"keywords": keywords, "geo": geo or "worldwide", "regions": out[:limit]}


def _related(keyword: str, geo: str, timeframe: str, category: int, prop: str, wid: str, limit: int):
    data = _explore([keyword], geo, timeframe, category, prop)
    w = _widgets(data, wid)[0]
    lists = _widget_data(w, "relatedsearches")["default"]["rankedList"]

    def norm(item):
        if "topic" in item:
            base = {"title": item["topic"]["title"], "type": item["topic"]["type"], "mid": item["topic"]["mid"]}
        else:
            base = {"query": item["query"]}
        return {**base, "value": item["formattedValue"]}

    top = [norm(i) for i in lists[0]["rankedKeyword"]][:limit] if lists else []
    rising = [norm(i) for i in lists[1]["rankedKeyword"]][:limit] if len(lists) > 1 else []
    return {"keyword": keyword, "geo": geo or "worldwide", "timeframe": timeframe, "top": top, "rising": rising}


@mcp.tool()
def related_queries(keyword: str, geo: str = DEFAULT_GEO, timeframe: str = "today 12-m",
                    category: int = 0, property: str = "web", limit: int = 25) -> dict:
    """Top and rising search queries related to a keyword. Rising values are % growth or 'Breakout'."""
    return _related(keyword, geo, timeframe, category, property, "RELATED_QUERIES", limit)


@mcp.tool()
def trending_now(geo: str = DEFAULT_GEO, limit: int = 25) -> dict:
    """Searches trending right now (last ~24h) in a country, with approximate traffic and news."""
    xml = _get("/trending/rss", {"geo": geo}, raw=True)
    ns = {"ht": "https://trends.google.com/trending/rss"}
    items = []
    for it in ET.fromstring(xml).iter("item"):
        news = [{"title": n.findtext("ht:news_item_title", namespaces=ns),
                 "source": n.findtext("ht:news_item_source", namespaces=ns),
                 "url": n.findtext("ht:news_item_url", namespaces=ns)}
                for n in it.findall("ht:news_item", ns)]
        items.append({"title": it.findtext("title"),
                      "traffic": it.findtext("ht:approx_traffic", namespaces=ns),
                      "started": it.findtext("pubDate"), "news": news})
    return {"geo": geo, "trends": items[:limit]}


@mcp.tool()
def suggestions(term: str) -> list[dict]:
    """Autocomplete: keyword and topic suggestions (topics have a mid like /m/0xyz to use as keyword)."""
    data = _get(f"/trends/api/autocomplete/{quote(term, safe='')}", {"hl": HL, "tz": TZ})
    return [{"title": t["title"], "type": t["type"], "mid": t["mid"]} for t in data["default"]["topics"]]


if __name__ == "__main__":
    mcp.run()
