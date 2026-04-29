#!/usr/bin/env python3
"""Reporter — digest diario por Telegram + push inmediato si nueva tracción.

Modos:
- `python reporter.py`               → digest diario completo.
- `python reporter.py --traction ID` → push corto sobre una opp con tracción.

Cron: 8am diario (digest). El tester invoca el modo --traction inline cuando
detecta nueva tracción.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn
from lib.notify import send_telegram


def fetch_summary(c) -> dict:
    out = {}
    out["new_traction"] = c.execute(
        """SELECT id, title, vertical, score, waitlist_signups, mvp_url, score_reasoning
           FROM opportunities
           WHERE status = 'traction' AND notified_at IS NULL
           ORDER BY waitlist_signups DESC""",
    ).fetchall()
    out["raw_count"] = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='raw'").fetchone()[0]
    out["validated_count"] = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='validated'").fetchone()[0]
    out["mvp_live_count"] = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='mvp_live'").fetchone()[0]
    out["traction_total"] = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='traction'").fetchone()[0]
    out["vetoed_count"] = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='vetoed'").fetchone()[0]
    out["abandoned_count"] = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='abandoned'").fetchone()[0]
    # Top 3 validated sin MVP (por score)
    out["top_validated"] = c.execute(
        """SELECT id, title, vertical, score
           FROM opportunities
           WHERE status='validated' AND mvp_path IS NULL
           ORDER BY score DESC LIMIT 3""",
    ).fetchall()
    return out


def render_digest(s: dict) -> str:
    lines = ["🤖 *Biz Hunter Digest*", ""]

    if s["new_traction"]:
        lines.append(f"🔥 *Nueva tracción 24h: {len(s['new_traction'])}*")
        for row in s["new_traction"]:
            id_, title, vertical, score, signups, url, _ = row
            lines.append(f"  · _{vertical}_ · score {score} · {signups} signups")
            lines.append(f"    `{title[:80]}`")
            if url:
                lines.append(f"    {url}")
        lines.append("")

    lines.append("📊 *Pipeline:*")
    lines.append(f"  · Raw pendientes: {s['raw_count']}")
    lines.append(f"  · Validadas pendientes MVP: {s['validated_count']}")
    lines.append(f"  · MVPs midiendo: {s['mvp_live_count']}")
    lines.append(f"  · Tracción total: {s['traction_total']}")
    lines.append(f"  · Vetadas: {s['vetoed_count']}")
    lines.append(f"  · Abandonadas: {s['abandoned_count']}")
    lines.append("")

    if s["top_validated"]:
        lines.append("🎯 *Top 3 validadas sin MVP:*")
        for row in s["top_validated"]:
            id_, title, vertical, score = row
            lines.append(f"  · `[{score}]` _{vertical}_ — {title[:80]}")

    return "\n".join(lines)


def mark_notified(c, ids: list[int]):
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    c.execute(
        f"UPDATE opportunities SET notified_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        ids,
    )


def render_traction(opp_id: int) -> str | None:
    with conn() as c:
        row = c.execute(
            """SELECT id, title, vertical, score, waitlist_signups, mvp_url, score_reasoning
               FROM opportunities WHERE id = ?""",
            (opp_id,),
        ).fetchone()
    if not row:
        return None
    id_, title, vertical, score, signups, url, reasoning = row
    parts = [
        "🔥 *Nueva oportunidad con tracción*",
        "",
        f"*Título:* {title}",
        f"*Vertical:* {vertical}",
        f"*Score:* {score}/100",
        f"*Signups 72h:* {signups}",
    ]
    if url:
        parts.append(f"*MVP:* {url}")
    if reasoning:
        parts.append("")
        parts.append(f"_{reasoning[:300]}_")
    return "\n".join(parts)


def main_traction(opp_id: int) -> int:
    text = render_traction(opp_id)
    if not text:
        print(f"[reporter] opp {opp_id} no encontrada")
        return 1
    sent = send_telegram(text)
    if sent:
        with conn() as c:
            mark_notified(c, [opp_id])
        print(f"[reporter] traction push enviado para opp {opp_id}")
        return 0
    return 2


def main_digest() -> int:
    with conn() as c:
        s = fetch_summary(c)
        text = render_digest(s)

    print(text.replace("*", "").replace("`", "").replace("_", ""))
    sent = send_telegram(text)
    if sent and s["new_traction"]:
        with conn() as c:
            mark_notified(c, [row[0] for row in s["new_traction"]])
    return 0 if sent else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--traction", type=int, help="Push corto para una opp con tracción nueva")
    args = parser.parse_args()

    if args.traction:
        sys.exit(main_traction(args.traction))
    sys.exit(main_digest())
