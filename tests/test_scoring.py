"""Tests offline del esquema BD y consistencia repo.

NO llaman a Claude/red. Validan invariantes del repo:
- BD se inicializa sin error.
- hunting-rules.md tiene secciones esperadas.
- Crontab tiene los 5 scripts del pipeline.
- Scripts existen en disco.
"""
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

EXPECTED_SCRIPTS = ["scout.py", "validator.py", "builder.py", "tester.py", "reporter.py"]


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
    assert row[0] == "raw"
    assert row[1] is None
    assert row[2] == 0


def test_hunting_rules_existe_y_tiene_secciones_clave():
    rules = ROOT / "strategy" / "hunting-rules.md"
    assert rules.is_file()
    text = rules.read_text()
    for section in ["Scoring", "Vetos hard", "Verticals soportados", "Umbrales del tester"]:
        assert section in text, f"Falta sección '{section}' en hunting-rules.md"


def test_crontab_lista_los_5_scripts():
    crontab = ROOT / "infra" / "crontab"
    assert crontab.is_file(), "Falta infra/crontab"
    text = crontab.read_text()
    for script in EXPECTED_SCRIPTS:
        assert f"scripts/{script}" in text, f"Falta {script} en infra/crontab"


def test_score_threshold_validated():
    rules = (ROOT / "strategy" / "hunting-rules.md").read_text()
    assert "60/100" in rules or "≥ 60" in rules


def test_mvp_type_choice_threshold():
    rules = (ROOT / "strategy" / "hunting-rules.md").read_text()
    assert "80/100" in rules or "≥ 80" in rules


def test_lib_modulos_importables():
    """Las libs comunes (db, notify, llm) deben existir como módulos."""
    libs = ROOT / "scripts" / "lib"
    for mod in ["db.py", "notify.py", "llm.py", "__init__.py"]:
        assert (libs / mod).is_file(), f"Falta scripts/lib/{mod}"


def test_sources_existen():
    sources = ROOT / "scripts" / "sources"
    for src in ["reddit.py", "hn.py"]:
        assert (sources / src).is_file(), f"Falta scripts/sources/{src}"


def test_scout_es_ejecutable_python():
    """El scout debe tener shebang y __main__ block."""
    scout = ROOT / "scripts" / "scout.py"
    assert scout.is_file()
    text = scout.read_text()
    assert text.startswith("#!/usr/bin/env python"), "scout.py debe tener shebang"
    assert 'if __name__ == "__main__"' in text


def test_n8n_workflows_referenciados():
    """Los webhooks n8n deben estar en .env.example."""
    env_ex = (ROOT / ".env.example").read_text()
    assert "N8N_WEBHOOK_SIGNUP_URL" in env_ex
    assert "N8N_WEBHOOK_COUNT_URL" in env_ex
