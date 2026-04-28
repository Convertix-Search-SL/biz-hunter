"""Tests offline del esquema y la lógica básica del scorer.

Estos tests NO llaman a Claude ni a APIs externas. Validan invariantes:
- BD se inicializa sin error.
- Las transiciones de estado documentadas son consistentes.
- Los umbrales del archivo de reglas son parseables.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from init_db import SCHEMA  # noqa: E402


VALID_STATUSES = {
    "raw", "validated", "vetoed",
    "mvp_live", "traction", "reported", "abandoned",
}

VALID_VERTICALS = {"microsaas", "content_seo", "digital_product", "newsletter"}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    yield c
    c.close()


def test_schema_se_aplica_sin_error(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert "opportunities" in tables


def test_insert_minimal_opp(conn):
    conn.execute(
        """INSERT INTO opportunities (source, title, pain_point) VALUES (?, ?, ?)""",
        ("reddit:r/SaaS", "Test opp", "users want X"),
    )
    row = conn.execute("SELECT status, score, waitlist_signups FROM opportunities").fetchone()
    assert row[0] == "raw"  # default
    assert row[1] is None    # score no asignado aún
    assert row[2] == 0       # default signups


def test_status_transitions_documentadas(conn):
    """Verifica que todos los status mencionados en las skills existen."""
    skill_files = list((ROOT / "skills").glob("*/SKILL.md"))
    assert len(skill_files) == 5, "Deben existir 5 skills"

    for f in skill_files:
        text = f.read_text()
        for status in ["raw", "validated", "vetoed", "mvp_live", "traction"]:
            # No exigimos que TODOS los status estén en TODAS las skills,
            # solo que los que aparezcan sean de la lista válida
            pass

    # Que todas las menciones explícitas a status='X' usen status válidos
    for f in skill_files:
        text = f.read_text()
        import re
        for m in re.finditer(r"status\s*=\s*['\"]([a-z_]+)['\"]", text):
            assert m.group(1) in VALID_STATUSES, f"Status inválido en {f.name}: {m.group(1)}"


def test_hunting_rules_existe_y_tiene_secciones_clave():
    rules = ROOT / "strategy" / "hunting-rules.md"
    assert rules.is_file(), "Falta strategy/hunting-rules.md"
    text = rules.read_text()
    for section in ["Scoring", "Vetos hard", "Verticals soportados", "Umbrales del tester"]:
        assert section in text, f"Falta sección '{section}' en hunting-rules.md"


def test_cron_jobs_json_es_valido():
    cron = ROOT / "cron" / "jobs.json"
    assert cron.is_file()
    data = json.loads(cron.read_text())
    assert isinstance(data, list)
    assert len(data) == 5
    skills_in_cron = {j["skill"] for j in data}
    skills_in_disk = {f.parent.name for f in (ROOT / "skills").glob("*/SKILL.md")}
    assert skills_in_cron == skills_in_disk, (
        f"Cron y skills en disco no coinciden: cron={skills_in_cron}, disk={skills_in_disk}"
    )


def test_score_threshold_validated():
    """Score ≥ 60 debe promover a validated, < 60 se queda raw."""
    # Lee la regla del archivo
    rules = (ROOT / "strategy" / "hunting-rules.md").read_text()
    assert "validated" in rules
    assert "60/100" in rules or "≥ 60" in rules


def test_mvp_type_choice_threshold():
    """Score < 80 → landing | score ≥ 80 → tool funcional."""
    rules = (ROOT / "strategy" / "hunting-rules.md").read_text()
    assert "80/100" in rules or "score ≥ 80" in rules.lower() or "≥ 80" in rules


def test_vetoed_no_se_revisita():
    """Una opp vetoed no debe poder pasar a otro estado por el flujo normal."""
    # Documental: el flujo solo procesa raw o mvp_live. vetoed es terminal.
    # Aquí solo aseguramos que ninguna skill menciona promover desde vetoed.
    skill_files = list((ROOT / "skills").glob("*/SKILL.md"))
    for f in skill_files:
        text = f.read_text().lower()
        # Patrón que indicaría re-promover vetoed
        assert "vetoed' to " not in text
        assert "from vetoed" not in text
