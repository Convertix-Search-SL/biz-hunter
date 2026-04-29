"""Telegram Bot API directo (sin gateway Hermes)."""
import os

import httpx


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = (
    os.environ.get("TELEGRAM_HOME_CHANNEL")
    or os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()
)


def send_telegram(text: str, parse_mode: str = "Markdown") -> bool:
    """Manda mensaje al chat principal del user. Devuelve True si OK."""
    if not BOT_TOKEN or not CHAT_ID:
        print("[notify] TELEGRAM_BOT_TOKEN o chat_id no configurados — skip notify")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text[:4000],
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = httpx.post(url, json=payload, timeout=10)
        return bool(r.json().get("ok"))
    except Exception as e:
        print(f"[notify] error mandando telegram: {e}")
        return False
