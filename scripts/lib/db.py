"""Helpers SQLite para biz-hunter."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Path BD: respeta env var BIZ_HUNTER_DB si se pasa, si no usa el del repo.
DB_PATH = Path(os.environ.get("BIZ_HUNTER_DB", "/opt/biz-hunter/data/opportunities.db"))
if not DB_PATH.exists():
    # Fallback dev local (fuera de docker)
    DB_PATH = Path(__file__).parent.parent.parent / "data" / "opportunities.db"


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=10.0)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def already_exists(c: sqlite3.Connection, title: str, url: str | None) -> bool:
    """Heurística anti-duplicados: mismo title o mismo source_url en últimos 30 días."""
    if url:
        r = c.execute(
            """SELECT 1 FROM opportunities
               WHERE source_url = ? AND discovered_at > datetime('now', '-30 days')
               LIMIT 1""",
            (url,),
        ).fetchone()
        if r:
            return True
    r = c.execute(
        """SELECT 1 FROM opportunities
           WHERE title = ? AND discovered_at > datetime('now', '-30 days')
           LIMIT 1""",
        (title,),
    ).fetchone()
    return bool(r)


def insert_opp(c: sqlite3.Connection, opp: dict) -> int | None:
    """Inserta opp con status=raw. Devuelve id o None si duplicada."""
    if already_exists(c, opp["title"], opp.get("source_url")):
        return None
    cur = c.execute(
        """INSERT INTO opportunities
           (source, source_url, title, pain_point, vertical, raw_signals, status)
           VALUES (?, ?, ?, ?, ?, ?, 'raw')""",
        (
            opp["source"],
            opp.get("source_url"),
            opp["title"],
            opp["pain_point"],
            opp.get("vertical"),
            json.dumps(opp.get("raw_signals") or {}),
        ),
    )
    return cur.lastrowid
