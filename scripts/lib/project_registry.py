"""Asignación de puertos y rutas para proyectos generados por project_builder.

Range 4001-4099 (99 slots). Asignación atómica via UPDATE ... WHERE
project_path IS NULL en BD para evitar carrera entre dos workers.
"""
import re
import sqlite3
from pathlib import Path


PORT_RANGE = (4001, 4100)  # exclusive end → 4001..4099
REPO_ROOT = Path(__file__).parent.parent.parent
PROJECTS_DIR = REPO_ROOT / "data" / "projects"


def next_free_port(c: sqlite3.Connection) -> int:
    """Devuelve el primer puerto libre del range. Lanza si está agotado."""
    used = {
        row[0] for row in c.execute(
            "SELECT project_port FROM opportunities WHERE project_port IS NOT NULL"
        )
    }
    for p in range(*PORT_RANGE):
        if p not in used:
            return p
    raise RuntimeError(f"port range {PORT_RANGE} exhausted ({len(used)} ocupados)")


def project_dir(slug: str) -> Path:
    """data/projects/<slug>/. No crea el dir, eso lo hace project_builder."""
    return PROJECTS_DIR / slug


def slug_for(opp: dict, maxlen: int = 50) -> str:
    """Slug kebab-case del título de la opp, idéntico al que usa builder.py."""
    s = (opp.get("title") or f"opp-{opp.get('id')}").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen] or f"opp-{opp.get('id')}"
