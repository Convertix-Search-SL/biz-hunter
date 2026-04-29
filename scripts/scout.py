#!/usr/bin/env python3
"""Opportunity Scout — escanea fuentes y guarda opps raw.

Flujo:
1. Fetch posts crudos de Reddit + HN.
2. Pasa el lote a Claude Sonnet para que extraiga pain points y vertical.
3. Inserta en BD con status='raw' (anti-dup por title/url en últimos 30d).
4. Manda mini-resumen a Telegram.

Cron típico: cada 6h. Idempotente.
"""
import json
import sys
from pathlib import Path

# Path resolver: añade scripts/ al sys.path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn, insert_opp
from lib.llm import ask_json, HAIKU_MODEL
from lib.notify import send_telegram
from sources import reddit, hn


SYSTEM = """Eres un scout de oportunidades de negocio low-budget.
Recibes posts crudos de Reddit/HN/IH. Para cada uno, extraes (si aplica):
- title (máx 100 chars, conciso)
- pain_point (1-2 frases describiendo el dolor real)
- vertical: uno de [microsaas, content_seo, digital_product, newsletter, none]

Aplica filtros DUROS — NO incluyas:
- MLM, dropship Aliexpress/Temu, crypto pumps, NSFW, médico/legal sin licencia, apuestas.
- Wrappers triviales de ChatGPT sin moat.
- Productos físicos con stock.
- Posts de "I made $X with my SaaS" (no son oportunidades, son self-promo).
- Posts puramente técnicos/tutorial sin pain point comercial.

Si el post NO contiene una oportunidad real → vertical='none' y la descartamos.

Devuelve JSON estricto:
{
  "opportunities": [
    { "post_id": "<id que te di>", "title": "...", "pain_point": "...", "vertical": "..." }
  ]
}
"""


def build_user_prompt(posts: list[dict]) -> str:
    blocks = ["## Posts a clasificar\n"]
    for i, p in enumerate(posts):
        body = p.get("selftext") or p.get("story_text") or ""
        blocks.append(
            f"### post_id={i}\n"
            f"Source: {p.get('source')}\n"
            f"Title: {p['title']}\n"
            f"Body (excerpt): {body[:600]}\n"
            f"Signals: ups={p.get('ups', p.get('points', 0))}, comments={p.get('num_comments', 0)}\n"
        )
    return "\n".join(blocks)


def main() -> int:
    print("[scout] fetch reddit...")
    reddit_posts = reddit.fetch_all()
    for p in reddit_posts:
        p["source"] = f"reddit:r/{p['subreddit']}"

    print("[scout] fetch HN...")
    hn_posts = hn.fetch_show_and_ask()
    for p in hn_posts:
        p["source"] = f"hn:{p['tag']}"

    posts = reddit_posts + hn_posts
    print(f"[scout] total raw posts: {len(posts)}")

    if not posts:
        send_telegram("🦗 *Scout*: 0 posts fetcheados (¿problema de red?)")
        return 0

    # Llama a Claude Haiku para clasificar (es barato, suficiente)
    user = build_user_prompt(posts)
    try:
        result = ask_json(SYSTEM, user, model=HAIKU_MODEL, max_tokens=8192)
    except Exception as e:
        send_telegram(f"❌ *Scout*: Claude falló: `{str(e)[:200]}`")
        return 1

    classified = result.get("opportunities", [])
    inserted = 0
    duplicates = 0
    skipped_vertical = 0

    with conn() as c:
        for opp in classified:
            if opp.get("vertical") in (None, "none", ""):
                skipped_vertical += 1
                continue
            try:
                pid = int(opp["post_id"])
                p = posts[pid]
            except (KeyError, ValueError, IndexError):
                continue

            row = {
                "source": p["source"],
                "source_url": p["url"],
                "title": opp["title"][:300],
                "pain_point": opp["pain_point"][:1000],
                "vertical": opp["vertical"],
                "raw_signals": {
                    "ups": p.get("ups", p.get("points", 0)),
                    "num_comments": p.get("num_comments", 0),
                    "body_excerpt": (p.get("selftext") or p.get("story_text") or "")[:500],
                },
            }
            if insert_opp(c, row) is not None:
                inserted += 1
            else:
                duplicates += 1

    summary = (
        f"🔍 *Scout run*\n"
        f"Posts crudos: {len(posts)}\n"
        f"Insertadas (status=raw): {inserted}\n"
        f"Duplicadas (skip): {duplicates}\n"
        f"Sin vertical / descartadas: {skipped_vertical}"
    )
    print(summary.replace("*", ""))
    send_telegram(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
