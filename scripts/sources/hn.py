"""Fetch Show HN y Ask HN recientes via Algolia API."""
import time

import httpx


HN_API = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_show_and_ask(hours_back: int = 168) -> list[dict]:
    """Posts Show HN + Ask HN de las últimas N horas (default 1 semana)."""
    since = int(time.time()) - hours_back * 3600
    out = []

    for tag in ["show_hn", "ask_hn"]:
        params = {
            "tags": tag,
            "numericFilters": f"created_at_i>{since},points>10",
            "hitsPerPage": 30,
        }
        try:
            r = httpx.get(HN_API, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[hn] error fetch {tag}: {e}")
            continue

        for hit in data.get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            out.append({
                "tag": tag,
                "title": (hit.get("title") or "")[:300],
                "url": url,
                "story_text": (hit.get("story_text", "") or "")[:1500],
                "points": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "created_at": hit.get("created_at"),
            })
    return out
