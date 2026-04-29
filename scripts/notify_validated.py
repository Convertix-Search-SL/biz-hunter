#!/usr/bin/env python3
"""Notify Validated — manda a Telegram las validated pendientes con botones aprobar/rechazar.

Cron: cada 4h aprox. Sólo manda las que aún no se hayan notificado
(notified_at IS NULL) y que estén en status='validated' (no aprobadas
ni rechazadas todavía).

Cada opp se manda como mensaje individual con InlineKeyboard:
  [✅ Aprobar]  [❌ Descartar]

El callback_data lleva `approve:<id>` o `reject:<id>`. El listener
(scripts/telegram_listener.py, container biz-hunter-bot) recibe el
callback y muta el status en BD.
"""
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = (
    os.environ.get("TELEGRAM_HOME_CHANNEL")
    or os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()
)
# Máximo de opps por run para no spamear de golpe (cron cada 4h * 5 = 30/día max)
MAX_PER_RUN = 5


def fetch_pending(c, limit: int) -> list[dict]:
    cur = c.execute(
        """SELECT id, title, pain_point, vertical, score, score_reasoning, source_url
           FROM opportunities
           WHERE status = 'validated'
             AND notified_at IS NULL
           ORDER BY score DESC
           LIMIT ?""",
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def esc(s: str) -> str:
    """Escape HTML mínimo para Telegram."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_card(o: dict) -> str:
    parts = [
        f"💡 <b>Nueva oportunidad — score {o['score']}/100</b>",
        f"<i>{esc(o['vertical'])}</i>",
        "",
        f"<b>{esc(o['title'])}</b>",
        "",
        esc(o["pain_point"][:400]),
    ]
    if o.get("source_url"):
        parts.append("")
        parts.append(f'🔗 <a href="{esc(o["source_url"])}">Source</a>')
    if o.get("score_reasoning"):
        parts.append("")
        parts.append(f"<b>Razonamiento:</b>")
        parts.append(esc(o["score_reasoning"][:500]))
    return "\n".join(parts)


def send_with_buttons(opp: dict) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("[notify_validated] sin BOT_TOKEN o CHAT_ID")
        return False
    text = render_card(opp)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Aprobar", "callback_data": f"approve:{opp['id']}"},
            {"text": "❌ Descartar", "callback_data": f"reject:{opp['id']}"},
        ]]
    }
    payload = {
        "chat_id": CHAT_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": keyboard,
    }
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload, timeout=10,
        )
        body = r.json()
        if not body.get("ok"):
            print(f"[notify_validated] opp {opp['id']} TG error: {body}")
        return bool(body.get("ok"))
    except Exception as e:
        print(f"[notify_validated] error: {e}")
        return False


def mark_notified(c, opp_id: int):
    c.execute(
        "UPDATE opportunities SET notified_at = CURRENT_TIMESTAMP WHERE id = ?",
        (opp_id,),
    )


def main() -> int:
    with conn() as c:
        pending = fetch_pending(c, MAX_PER_RUN)

    if not pending:
        print("[notify_validated] no hay validated pendientes de notificar")
        return 0

    print(f"[notify_validated] mandando {len(pending)} opps a Telegram")

    sent = 0
    for opp in pending:
        if send_with_buttons(opp):
            with conn() as c:
                mark_notified(c, opp["id"])
            sent += 1
        else:
            print(f"[notify_validated] fallo al mandar opp {opp['id']}")

    print(f"[notify_validated] enviadas: {sent}/{len(pending)}")
    return 0 if sent == len(pending) else 1


if __name__ == "__main__":
    sys.exit(main())
