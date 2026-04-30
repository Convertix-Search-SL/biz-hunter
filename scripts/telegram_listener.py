#!/usr/bin/env python3
"""Telegram long-polling listener — recibe callbacks de los botones inline.

Procesa:
- callback_query con data='approve:<id>' → opp pasa a status='approved'
- callback_query con data='reject:<id>'  → opp pasa a status='rejected'
- mensajes /status, /run scout|validator|builder|reporter, /help

Corre como container long-running (`biz-hunter-bot`).
Es un loop: getUpdates(offset) → procesa → ack → repeat.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = {
    int(x.strip()) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip()
}
SCRIPTS_DIR = Path(__file__).parent
PYTHON = sys.executable


def api(method: str, **params) -> dict | None:
    """Wrapper Telegram Bot API."""
    if not BOT_TOKEN:
        return None
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=params, timeout=35,
        )
        return r.json()
    except Exception as e:
        print(f"[listener] API {method} error: {e}")
        return None


def answer_callback(callback_id: str, text: str = ""):
    api("answerCallbackQuery", callback_query_id=callback_id, text=text)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Default HTML — más permisivo con caracteres especiales que Markdown.
    Si el caller pasa Markdown legacy, queda como 'HTML' por defecto y los
    callers críticos (cmd_build, cmd_status, etc.) ya usan tags HTML."""
    r = api("sendMessage", chat_id=chat_id, text=text[:4000], parse_mode=parse_mode,
            disable_web_page_preview=True)
    if r and not r.get("ok"):
        print(f"[listener] send_message FAILED: {r.get('description', r)}")
    return r


def edit_message(chat_id: int, message_id: int, text: str):
    api("editMessageText", chat_id=chat_id, message_id=message_id,
        text=text[:4000], parse_mode="HTML", disable_web_page_preview=True)


def remove_keyboard(chat_id: int, message_id: int):
    api("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
        reply_markup={"inline_keyboard": []})


def is_authorized(user_id: int) -> bool:
    """Solo el dueño del bot puede comandar/aprobar."""
    if not ALLOWED_USERS:
        return True  # sin lista → permisivo (no bloquees al user que es solo él)
    return user_id in ALLOWED_USERS


def handle_callback(cb: dict):
    """Procesa click en botón inline aprobar/rechazar."""
    cb_id = cb["id"]
    user_id = cb.get("from", {}).get("id")
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")

    if not is_authorized(user_id):
        answer_callback(cb_id, "No autorizado")
        return

    if ":" not in data:
        answer_callback(cb_id, "Callback inválido")
        return

    action, _, opp_id_str = data.partition(":")
    try:
        opp_id = int(opp_id_str)
    except ValueError:
        answer_callback(cb_id, "ID inválido")
        return

    with conn() as c:
        row = c.execute(
            "SELECT title, status FROM opportunities WHERE id = ?", (opp_id,),
        ).fetchone()
        if not row:
            answer_callback(cb_id, "Opp no encontrada")
            return
        title, status = row[0], row[1]

        if status != "validated":
            answer_callback(cb_id, f"Ya estaba en estado: {status}")
            if chat_id and message_id:
                remove_keyboard(chat_id, message_id)
            return

        def _esc(s):
            return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if action == "approve":
            c.execute(
                """UPDATE opportunities SET
                     status = 'approved',
                     approved_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (opp_id,),
            )
            answer_callback(cb_id, "✅ Aprobada")
            if chat_id and message_id:
                edit_message(
                    chat_id, message_id,
                    f"✅ <b>Aprobada</b> — pasa a cola de build\n\n<b>{_esc(title[:200])}</b>",
                )
        elif action == "reject":
            c.execute(
                "UPDATE opportunities SET status = 'rejected' WHERE id = ?",
                (opp_id,),
            )
            answer_callback(cb_id, "❌ Descartada")
            if chat_id and message_id:
                edit_message(
                    chat_id, message_id,
                    f"❌ <b>Descartada</b>\n\n<b>{_esc(title[:200])}</b>",
                )
        else:
            answer_callback(cb_id, "Acción desconocida")


def run_script(script_name: str) -> tuple[int, str]:
    """Ejecuta un script del pipeline y devuelve (rc, last_lines)."""
    path = SCRIPTS_DIR / script_name
    if not path.exists():
        return 1, f"Script {script_name} no existe"
    try:
        r = subprocess.run(
            [PYTHON, str(path)],
            capture_output=True, text=True, timeout=600,
        )
        out = (r.stdout + r.stderr).strip().splitlines()
        return r.returncode, "\n".join(out[-15:])
    except subprocess.TimeoutExpired:
        return 124, "Timeout (>10min)"
    except Exception as e:
        return 1, str(e)


def cmd_status(chat_id: int):
    with conn() as c:
        rows = c.execute(
            """SELECT status, COUNT(*) FROM opportunities GROUP BY status
               ORDER BY status""",
        ).fetchall()
    lines = ["📊 <b>Pipeline status</b>"]
    for status, n in rows:
        lines.append(f"  · {_esc(status)}: {n}")
    send_message(chat_id, "\n".join(lines))


def cmd_run(chat_id: int, target: str):
    valid = {"scout": "scout.py", "validator": "validator.py",
             "builder": "builder.py", "tester": "tester.py",
             "reporter": "reporter.py", "notify": "notify_validated.py"}
    if target not in valid:
        send_message(chat_id, f"Targets: {', '.join(valid)}")
        return
    send_message(chat_id, f"⏳ Ejecutando {target}...")
    rc, last = run_script(valid[target])
    emoji = "✅" if rc == 0 else "❌"
    send_message(chat_id, f"{emoji} <b>{_esc(target)}</b> (rc={rc})\n<pre>{_esc(last[:3500])}</pre>")


def cmd_help(chat_id: int):
    text = (
        "<b>Biz Hunter Bot</b>\n\n"
        "Comandos:\n"
        "  <code>/status</code> — counts del pipeline\n"
        "  <code>/run scout|validator|builder|tester|reporter|notify</code>\n"
        "  <code>/build &lt;opp_id&gt;</code> — encola un proyecto V1 para construir\n"
        "  <code>/help</code> — esta ayuda\n\n"
        "También respondo a los botones de las opps validadas (aprobar/descartar)."
    )
    send_message(chat_id, text)


def cmd_build(chat_id: int, user_id: int, opp_id_str: str):
    """Encola una build. Inserta en build_requests; el worker la coge en ≤1min."""
    try:
        opp_id = int(opp_id_str)
    except ValueError:
        send_message(chat_id, "Uso: <code>/build &lt;opp_id&gt;</code> (entero)")
        return
    with conn() as c:
        opp = c.execute(
            "SELECT id, title, status FROM opportunities WHERE id = ?", (opp_id,),
        ).fetchone()
        if not opp:
            send_message(chat_id, f"❌ Opp {opp_id} no existe")
            return
        c.execute(
            """INSERT INTO build_requests (opp_id, requested_by, force)
               VALUES (?, ?, 1)""",
            (opp_id, f"tg-user:{chat_id}"),
        )
    send_message(
        chat_id,
        f"⏳ Encolado build de opp {opp_id} (<code>{_esc(opp[1][:60])}</code>, status={_esc(opp[2])}).\n"
        f"El worker lo coge en ≤1 min. Te aviso al terminar.",
    )


def handle_message(msg: dict):
    user_id = msg.get("from", {}).get("id")
    if not is_authorized(user_id):
        return
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    if text in ("/status", "/status@*"):
        cmd_status(chat_id); return
    if text.startswith("/run "):
        target = text[5:].strip().split()[0]
        cmd_run(chat_id, target); return
    if text.startswith("/build "):
        cmd_build(chat_id, user_id, text[7:].strip()); return
    if text in ("/help", "/start"):
        cmd_help(chat_id); return


def loop():
    if not BOT_TOKEN:
        print("[listener] TELEGRAM_BOT_TOKEN faltando — abortando")
        return 1
    print(f"[listener] arrancando long-polling (allowed_users={ALLOWED_USERS})")
    offset = 0
    while True:
        try:
            r = httpx.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=40,
            )
            data = r.json()
        except httpx.TimeoutException:
            continue
        except Exception as e:
            print(f"[listener] getUpdates error: {e}")
            time.sleep(5)
            continue

        if not data.get("ok"):
            print(f"[listener] getUpdates ko: {data}")
            time.sleep(5)
            continue

        for update in data.get("result", []):
            offset = update["update_id"] + 1
            try:
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    handle_message(update["message"])
            except Exception as e:
                print(f"[listener] error procesando update: {e}")


if __name__ == "__main__":
    sys.exit(loop() or 0)
