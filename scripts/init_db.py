"""Bootstrap de la BD SQLite del biz-hunter.

Crea data/opportunities.db con el esquema definido en el plan. Idempotente:
si ya existe, no destruye datos. Solo asegura que la tabla y los índices
están al día (CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS).

Uso:
    python scripts/init_db.py
    python scripts/init_db.py --reset   # peligroso: borra y recrea
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "opportunities.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    source_url TEXT,
    title TEXT NOT NULL,
    pain_point TEXT NOT NULL,
    vertical TEXT,
    raw_signals TEXT,             -- JSON serializado
    score INTEGER,
    score_reasoning TEXT,
    veto_reasons TEXT,            -- JSON serializado
    mvp_path TEXT,
    mvp_url TEXT,
    mvp_type TEXT,                -- 'landing' | 'tool'
    waitlist_signups INTEGER DEFAULT 0,
    last_signup_check TIMESTAMP,
    -- Estados:
    -- raw → validated → approved → mvp_live → traction
    -- (rejected si user descarta validated, vetoed por reglas, abandoned post-mvp)
    status TEXT NOT NULL DEFAULT 'raw',
    approved_at TIMESTAMP,        -- timestamp de aprobación manual (botón Telegram)
    notified_at TIMESTAMP,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_score ON opportunities(score DESC);
CREATE INDEX IF NOT EXISTS idx_discovered ON opportunities(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_status_approved ON opportunities(status, approved_at);
"""


def init(reset: bool = False) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if reset and DB_PATH.exists():
        confirm = input(f"Borro {DB_PATH}? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Abortado.")
            sys.exit(1)
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT COUNT(*) FROM opportunities")
        n = cur.fetchone()[0]

    print(f"BD lista en {DB_PATH} ({n} oportunidades existentes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Borra y recrea (pide confirmación)")
    args = parser.parse_args()
    init(reset=args.reset)
