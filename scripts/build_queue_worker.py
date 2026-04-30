#!/usr/bin/env python3
"""Build Queue Worker — drena build_requests + escoge tracción si no hay queue.

Cron: cada 1 min (en biz-hunter-cron via supercronic).

Política:
- 1ª prioridad: filas pendientes en build_requests (manuales /build).
  Drena hasta 2/run para no acaparar el container un turno.
- 2ª prioridad: opps en status='traction' sin proyecto (auto). 1/run.
- Cap global diario: MAX_BUILDS_PER_DAY (env, default 8). Si excede, no
  procesa traction auto pero SÍ procesa manuales (override del user).

Cada llamada delega en project_builder.py --opp <id> y captura stderr
para guardar en build_requests.error si falla.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn


PYTHON = sys.executable
BUILDER = str(Path(__file__).parent / "project_builder.py")
MAX_BUILDS_PER_DAY = int(os.environ.get("MAX_BUILDS_PER_DAY", "8"))
MAX_PENDING_PER_RUN = 2


def builds_today(c) -> int:
    row = c.execute(
        """SELECT COUNT(*) FROM opportunities
           WHERE project_built_at >= date('now', 'utc')"""
    ).fetchone()
    return int(row[0] if row else 0)


def fetch_pending(c, limit: int) -> list[dict]:
    cur = c.execute(
        """SELECT id, opp_id, requested_by, force
           FROM build_requests
           WHERE processed_at IS NULL
           ORDER BY id ASC
           LIMIT ?""",
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_traction_target(c) -> int | None:
    row = c.execute(
        """SELECT id FROM opportunities
           WHERE status='traction' AND project_path IS NULL
           ORDER BY id ASC LIMIT 1"""
    ).fetchone()
    return int(row[0]) if row else None


def mark_processed(c, req_id: int, ok: bool, error: str | None):
    c.execute(
        """UPDATE build_requests SET
             processed_at = CURRENT_TIMESTAMP,
             status = ?,
             error = ?
           WHERE id = ?""",
        ("ok" if ok else "failed", (error or "")[:1000] if not ok else None, req_id),
    )


def run_builder(opp_id: int, *, force: bool, tg_chat: str | None) -> tuple[bool, str]:
    """Llama a project_builder.py. Devuelve (ok, last_stderr_or_msg)."""
    cmd = [PYTHON, BUILDER, "--opp", str(opp_id)]
    if force:
        cmd.append("--force")
    if tg_chat:
        cmd.extend(["--tg-chat", tg_chat])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        out = (r.stdout + r.stderr)[-2000:]
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "project_builder timeout (>900s)"
    except Exception as e:
        return False, str(e)


def extract_chat_id(requested_by: str) -> str | None:
    """'tg-user:288647408' → '288647408', otro caso → None."""
    if requested_by.startswith("tg-user:"):
        return requested_by.split(":", 1)[1].strip() or None
    return None


def main() -> int:
    with conn() as c:
        today = builds_today(c)
        pending = fetch_pending(c, MAX_PENDING_PER_RUN)

    # 1) Drena pending (manuales). Procesan SIEMPRE, ignoran cap (override user).
    if pending:
        print(f"[worker] {len(pending)} pending requests")
        for req in pending:
            chat_id = extract_chat_id(req["requested_by"])
            ok, log = run_builder(req["opp_id"], force=bool(req["force"]), tg_chat=chat_id)
            with conn() as c:
                mark_processed(c, req["id"], ok, log if not ok else None)
            print(f"[worker] req {req['id']} opp {req['opp_id']} → {'OK' if ok else 'FAIL'}")
        return 0  # un run = una pasada; siguiente tick en 1 min

    # 2) Si no hay manuales y no hemos topado el cap, traction auto.
    if today >= MAX_BUILDS_PER_DAY:
        print(f"[worker] cap diario alcanzado ({today}/{MAX_BUILDS_PER_DAY}), skipping traction auto")
        return 0

    with conn() as c:
        opp_id = fetch_traction_target(c)
    if not opp_id:
        # silencioso: no hay nada que hacer
        return 0

    print(f"[worker] traction auto: opp {opp_id}")
    ok, log = run_builder(opp_id, force=False, tg_chat=None)
    print(f"[worker] traction opp {opp_id} → {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
