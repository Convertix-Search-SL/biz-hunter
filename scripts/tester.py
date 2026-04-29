#!/usr/bin/env python3
"""MVP Tester — mide signups via webhook n8n, promueve a traction/abandoned.

Reglas (alinear con strategy/hunting-rules.md):
- mvp_type='landing': ≥ 5 signups en 72h → traction.
- mvp_type='tool':    ≥ 3 signups en 72h → traction.
- 14 días sin tracción tras mvp_live → abandoned.

Cuando una opp pasa a traction nueva, dispara reporter.py --traction <id>
inmediatamente (push Telegram on-demand).

Cron: 7am diario (antes del reporter de las 8).
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn
from lib.notify import send_telegram


N8N_COUNT_URL = os.environ.get(
    "N8N_WEBHOOK_COUNT_URL", "https://n8n.convertix.net/webhook/biz-hunter/count"
)
WINDOW_HOURS = 72
GRACE_DAYS = 14

TRACTION_THRESHOLDS = {"landing": 5, "tool": 3}


def fetch_mvp_live(c) -> list[dict]:
    cur = c.execute(
        """SELECT id, title, vertical, score, mvp_path, mvp_url, mvp_type,
                  waitlist_signups, last_signup_check,
                  COALESCE(notified_at, discovered_at) as ref_date
           FROM opportunities
           WHERE status = 'mvp_live'
             AND (last_signup_check IS NULL
                  OR last_signup_check < datetime('now', '-18 hours'))""",
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_signup_count(slug: str, hours: int = WINDOW_HOURS) -> int:
    try:
        r = httpx.get(N8N_COUNT_URL, params={"slug": slug, "hours": hours}, timeout=15)
        r.raise_for_status()
        return int(r.json().get("signups", 0))
    except Exception as e:
        print(f"[tester] error count {slug}: {e}")
        return 0


def update_signups(c, opp_id: int, count: int, status: str | None = None):
    if status:
        c.execute(
            """UPDATE opportunities SET
                 waitlist_signups=?, last_signup_check=CURRENT_TIMESTAMP, status=?,
                 notified_at=NULL
               WHERE id=?""",
            (count, status, opp_id),
        )
    else:
        c.execute(
            """UPDATE opportunities SET
                 waitlist_signups=?, last_signup_check=CURRENT_TIMESTAMP
               WHERE id=?""",
            (count, opp_id),
        )


def days_since_iso(s: str) -> int:
    if not s:
        return 0
    try:
        # SQLite isoformat -> datetime
        s = s.replace("Z", "+00:00").split(".")[0]
        if "+" not in s and "T" in s:
            s = s + "+00:00"
        dt = datetime.fromisoformat(s.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0


def trigger_traction_push(opp_id: int):
    """Llama a reporter.py --traction <id> inline."""
    try:
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "reporter.py"), "--traction", str(opp_id)],
            check=False, timeout=30,
        )
    except Exception as e:
        print(f"[tester] error triggering reporter: {e}")


def main() -> int:
    with conn() as c:
        live = fetch_mvp_live(c)

    if not live:
        print("[tester] no MVPs live to check")
        return 0

    print(f"[tester] checking {len(live)} live MVPs")

    new_traction_ids: list[int] = []
    abandoned = 0
    no_change = 0

    for opp in live:
        slug = Path(opp["mvp_path"] or "").name
        count = get_signup_count(slug, hours=WINDOW_HOURS)
        threshold = TRACTION_THRESHOLDS.get(opp["mvp_type"] or "landing", 5)

        if count >= threshold:
            with conn() as c:
                update_signups(c, opp["id"], count, status="traction")
            new_traction_ids.append(opp["id"])
        else:
            grace = days_since_iso(opp["ref_date"])
            if grace >= GRACE_DAYS:
                with conn() as c:
                    update_signups(c, opp["id"], count, status="abandoned")
                abandoned += 1
            else:
                with conn() as c:
                    update_signups(c, opp["id"], count)
                no_change += 1

    # Disparar push inmediato por cada nueva traction
    for opp_id in new_traction_ids:
        trigger_traction_push(opp_id)

    msg = (
        f"⚖️ *Tester run*\n"
        f"Live revisados: {len(live)}\n"
        f"Nuevas tracciones: {len(new_traction_ids)}\n"
        f"Sin cambio (en gracia): {no_change}\n"
        f"Abandonadas (>14d): {abandoned}"
    )
    print(msg.replace("*", ""))
    send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
