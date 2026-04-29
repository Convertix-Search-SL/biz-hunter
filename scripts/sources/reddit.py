"""Fetch top posts de subreddits de business/sideprojects.

Usa la JSON pública de reddit (sin auth, rate-limit suave). Si REDDIT_CLIENT_ID
está en env, podríamos pasar a auth y subir el rate limit, pero no hace falta
para nuestro volumen (5-6 calls cada 6h).
"""
import httpx


SUBREDDITS = ["Entrepreneur", "SaaS", "indiehackers", "sideproject"]


def fetch_subreddit(name: str, limit: int = 25, time_window: str = "week") -> list[dict]:
    url = f"https://www.reddit.com/r/{name}/top.json?t={time_window}&limit={limit}"
    try:
        r = httpx.get(url, headers={"User-Agent": "biz-hunter/0.1"}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[reddit] error fetch r/{name}: {e}")
        return []

    posts = []
    for item in data.get("data", {}).get("children", []):
        d = item.get("data", {})
        # Filtra: > 50 upvotes O > 10 comentarios para señal mínima
        if d.get("ups", 0) < 50 and d.get("num_comments", 0) < 10:
            continue
        if d.get("over_18"):
            continue
        posts.append({
            "subreddit": name,
            "title": d.get("title", "")[:300],
            "url": f"https://www.reddit.com{d.get('permalink', '')}",
            "selftext": (d.get("selftext", "") or "")[:1500],
            "ups": d.get("ups", 0),
            "num_comments": d.get("num_comments", 0),
            "created_utc": d.get("created_utc", 0),
        })
    return posts


def fetch_all() -> list[dict]:
    """Devuelve posts de todos los subs configurados, deduplicados por url."""
    out = []
    seen = set()
    for sub in SUBREDDITS:
        for p in fetch_subreddit(sub):
            if p["url"] in seen:
                continue
            seen.add(p["url"])
            out.append(p)
    return out
