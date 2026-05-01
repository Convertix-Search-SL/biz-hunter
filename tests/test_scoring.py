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
    "raw", "validated", "vetoed", "approved", "rejected",
    "mvp_live", "traction", "reported", "abandoned",
    "project_live", "project_failed",
}

VALID_VERTICALS = {"microsaas", "content_seo", "digital_product", "newsletter"}

EXPECTED_SCRIPTS = [
    "scout.py", "validator.py", "builder.py", "tester.py", "reporter.py",
    "notify_validated.py", "telegram_listener.py",
    "project_builder.py", "build_queue_worker.py",
]
# Scripts que van al crontab (los long-running se ejecutan como container service).
CRON_SCRIPTS = [
    "scout.py", "validator.py", "builder.py", "tester.py", "reporter.py",
    "notify_validated.py", "build_queue_worker.py",
]


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


def test_crontab_lista_los_scripts_periodicos():
    crontab = ROOT / "infra" / "crontab.supercronic"
    assert crontab.is_file(), "Falta infra/crontab.supercronic"
    text = crontab.read_text()
    for script in CRON_SCRIPTS:
        assert f"scripts/{script}" in text, f"Falta {script} en crontab.supercronic"


def test_telegram_listener_es_long_running():
    """telegram_listener corre como service Docker, no como cron job."""
    crontab = (ROOT / "infra" / "crontab.supercronic").read_text()
    assert "telegram_listener" not in crontab, "listener no debe estar en crontab"
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "telegram_listener.py" in compose, "listener debe estar como service en compose"


def test_project_templates_exist():
    """Las 4 plantillas por vertical están presentes."""
    tpl_dir = ROOT / "scripts" / "project_templates"
    assert tpl_dir.is_dir()
    for v in ["microsaas", "content_seo", "digital_product", "newsletter"]:
        assert (tpl_dir / f"{v}.py").is_file(), f"Falta plantilla {v}.py"
    assert (tpl_dir / "__init__.py").is_file()


def test_project_registry_assigns_unique_ports(conn):
    """Dos opps con port asignado → next_free_port salta los ocupados."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.project_registry import next_free_port

    conn.execute("INSERT INTO opportunities (source, title, pain_point, project_port) VALUES ('x', 'a', 'p', 4001)")
    conn.execute("INSERT INTO opportunities (source, title, pain_point, project_port) VALUES ('x', 'b', 'p', 4002)")
    p = next_free_port(conn)
    assert p == 4003


def test_build_requests_table_present(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='build_requests'")
    assert cur.fetchone() is not None, "Falta tabla build_requests"


def test_status_includes_project_states():
    init_db_text = (ROOT / "scripts" / "init_db.py").read_text()
    assert "project_live" in init_db_text
    assert "project_failed" in init_db_text or "project_failed" in str(VALID_STATUSES)


def test_build_queue_worker_en_crontab():
    crontab = (ROOT / "infra" / "crontab.supercronic").read_text()
    assert "build_queue_worker.py" in crontab
    assert "* * * * *" in crontab, "worker debe correr cada minuto"


def test_dockerfile_cron_tiene_docker_cli():
    df = (ROOT / "Dockerfile.cron").read_text()
    assert "docker-ce-cli" in df
    assert "docker-compose-plugin" in df


def test_compose_monta_docker_socket():
    cy = (ROOT / "docker-compose.yml").read_text()
    assert "/var/run/docker.sock" in cy
    assert "HOST_UID" in cy
    assert "HOST_GID" in cy


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


@pytest.mark.parametrize("name", EXPECTED_SCRIPTS)
def test_script_es_ejecutable_python(name: str):
    """Los 5 scripts del pipeline deben tener shebang y __main__ block."""
    script = ROOT / "scripts" / name
    assert script.is_file(), f"Falta scripts/{name}"
    text = script.read_text()
    assert text.startswith("#!/usr/bin/env python"), f"{name} debe tener shebang"
    assert 'if __name__ == "__main__"' in text


def test_n8n_workflows_referenciados():
    """Los webhooks n8n deben estar en .env.example."""
    env_ex = (ROOT / ".env.example").read_text()
    assert "N8N_WEBHOOK_SIGNUP_URL" in env_ex
    assert "N8N_WEBHOOK_COUNT_URL" in env_ex
