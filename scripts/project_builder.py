#!/usr/bin/env python3
"""Project Builder — construye UNA opportunity (V1 funcional).

No decide a quién construir; eso es del build_queue_worker.

Modos:
    project_builder.py --opp <id>             # build normal (lock atómico)
    project_builder.py --opp <id> --force     # ignora estado actual
    project_builder.py --opp <id> --rebuild   # docker compose down -v + rm + rebuild
    project_builder.py --opp <id> --tg-chat <chat_id>  # dirige push TG a chat específico

Estados resultantes:
    project_live   → docker up + healthcheck OK + mvp_url asignada.
    project_failed → fallo en cualquier paso. Quedan archivos para inspección.

Idempotencia:
    Sin --force / --rebuild, una segunda llamada con UPDATE ... WHERE
    project_path IS NULL no progresa. Devuelve exit 0 si ya OK, exit 2 si en
    curso por otro proceso.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn
from lib.notify import send_telegram
from lib.project_registry import next_free_port, project_dir, slug_for
from project_templates import get_template


HOST_UID = os.environ.get("HOST_UID", "501")
HOST_GID = os.environ.get("HOST_GID", "20")
HEALTHCHECK_URL_TPL = "http://host.docker.internal:{port}/"
# Si corremos directamente en el Mac (no container), usamos localhost
if not Path("/.dockerenv").exists():
    HEALTHCHECK_URL_TPL = "http://localhost:{port}/"


def fetch_opp(c, opp_id: int) -> dict | None:
    cur = c.execute(
        """SELECT id, title, pain_point, vertical, score, score_reasoning, status,
                  project_path, project_port, project_template
           FROM opportunities WHERE id = ?""",
        (opp_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def acquire_lock(c, opp_id: int, slug: str, port: int, template: str) -> bool:
    """UPDATE atómico. True si conseguimos el lock (no había proyecto)."""
    cur = c.execute(
        """UPDATE opportunities SET
             project_path = ?,
             project_port = ?,
             project_template = ?
           WHERE id = ? AND project_path IS NULL""",
        (f"data/projects/{slug}", port, template, opp_id),
    )
    return cur.rowcount == 1


def write_meta(dest_dir: Path, meta: dict):
    (dest_dir / "deploy_meta.json").write_text(json.dumps(meta, indent=2, default=str))


def docker_compose_up(dest_dir: Path, port: int) -> tuple[bool, str]:
    """Lanza docker compose up -d --build. Devuelve (ok, last_logs)."""
    env = os.environ.copy()
    env["PROJECT_PORT"] = str(port)
    try:
        r = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            cwd=dest_dir, env=env, capture_output=True, text=True, timeout=600,
        )
        out = (r.stdout + r.stderr)[-3000:]
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "docker compose timeout (>600s)"
    except Exception as e:
        return False, f"docker compose error: {e}"


def docker_compose_down(dest_dir: Path):
    try:
        subprocess.run(
            ["docker", "compose", "down", "-v"],
            cwd=dest_dir, capture_output=True, text=True, timeout=120,
        )
    except Exception:
        pass


def healthcheck(port: int, timeout_s: int) -> bool:
    """Hace GET cada 2s hasta timeout_s. True si responde 200-3xx."""
    url = HEALTHCHECK_URL_TPL.format(port=port)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if 200 <= r.status_code < 400:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def chown_to_host(dest_dir: Path):
    """Restora ownership al user del host Mac para que David pueda editar."""
    if not Path("/.dockerenv").exists():
        return  # corremos en el host directamente, no hace falta
    try:
        subprocess.run(
            ["chown", "-R", f"{HOST_UID}:{HOST_GID}", str(dest_dir)],
            capture_output=True, timeout=30,
        )
    except Exception as e:
        print(f"[builder] chown warning: {e}")


def push_tg(text: str, chat_id: str | None = None):
    """Si chat_id viene, sobrescribe el TELEGRAM_HOME_CHANNEL temporalmente."""
    if chat_id:
        old = os.environ.get("TELEGRAM_HOME_CHANNEL")
        os.environ["TELEGRAM_HOME_CHANNEL"] = chat_id
        # send_telegram lee CHAT_ID desde env al import — recargamos módulo
        import importlib

        from lib import notify
        importlib.reload(notify)
        notify.send_telegram(text)
        if old is not None:
            os.environ["TELEGRAM_HOME_CHANNEL"] = old
        else:
            os.environ.pop("TELEGRAM_HOME_CHANNEL", None)
    else:
        send_telegram(text)


def mark_failed(c, opp_id: int, reason: str):
    c.execute(
        "UPDATE opportunities SET status='project_failed' WHERE id=?",
        (opp_id,),
    )
    print(f"[builder] FAILED opp {opp_id}: {reason}")


def mark_live(c, opp_id: int, url: str):
    c.execute(
        """UPDATE opportunities SET
             status='project_live',
             project_url=?,
             project_built_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (url, opp_id),
    )


def write_spec(c, opp_id: int, spec_md: str):
    c.execute(
        "UPDATE opportunities SET project_spec=? WHERE id=?",
        (spec_md, opp_id),
    )


def main(opp_id: int, force: bool, rebuild: bool, tg_chat: str | None) -> int:
    with conn() as c:
        opp = fetch_opp(c, opp_id)
        if not opp:
            print(f"[builder] opp {opp_id} no existe")
            push_tg(f"❌ Builder: opp {opp_id} no encontrada", tg_chat)
            return 1

    # Validaciones
    if not force and opp["project_path"] and opp["status"] == "project_live" and not rebuild:
        print(f"[builder] opp {opp_id} ya tiene proyecto live ({opp['project_url']}). Usa --rebuild para recrear.")
        push_tg(f"ℹ️ Opp {opp_id} ya está live: {opp['project_url']}", tg_chat)
        return 0

    template_mod = get_template(opp.get("vertical"))
    template_name = opp.get("vertical") or "microsaas"
    if template_name not in ("microsaas", "content_seo", "digital_product", "newsletter"):
        template_name = "microsaas"

    slug = slug_for(opp)
    dest_dir = project_dir(slug)

    # Rebuild: tear down y limpia
    if rebuild and dest_dir.exists():
        print(f"[builder] --rebuild: docker compose down + rm -rf {dest_dir}")
        docker_compose_down(dest_dir)
        shutil.rmtree(dest_dir, ignore_errors=True)
        with conn() as c:
            c.execute(
                """UPDATE opportunities SET
                     project_path=NULL, project_port=NULL,
                     project_url=NULL, project_built_at=NULL,
                     project_template=NULL
                   WHERE id=?""",
                (opp_id,),
            )

    # Lock atómico — solo si no hay proyecto previo (o si rebuild lo limpió)
    with conn() as c:
        port = next_free_port(c)
        got_lock = acquire_lock(c, opp_id, slug, port, template_name)

    if not got_lock and not force:
        print(f"[builder] opp {opp_id} ya tiene proyecto en curso/built")
        return 2

    if not got_lock and force:
        # con force, sobrescribimos los campos
        with conn() as c:
            c.execute(
                """UPDATE opportunities SET
                     project_path=?, project_port=?, project_template=?
                   WHERE id=?""",
                (f"data/projects/{slug}", port, template_name, opp_id),
            )
            port = port  # ya asignado
        print(f"[builder] --force: sobrescribiendo proyecto opp {opp_id}")

    # Generación de archivos via plantilla
    print(f"[builder] opp {opp_id} → template={template_name} slug={slug} port={port}")
    push_tg(f"⏳ Construyendo opp {opp_id}: <b>{opp['title'][:80]}</b>\n→ {template_name}, port {port}", tg_chat)

    try:
        meta = template_mod.build(opp, dest_dir)
    except Exception as e:
        with conn() as c:
            mark_failed(c, opp_id, f"template error: {e}")
        push_tg(f"❌ Build falló (template): opp {opp_id}\n<code>{str(e)[:300]}</code>", tg_chat)
        return 1

    # Persiste spec
    if meta.get("spec_md"):
        with conn() as c:
            write_spec(c, opp_id, meta["spec_md"][:20000])

    # Project sin Docker (digital_product, newsletter): se queda como spec-only.
    if not meta.get("has_docker"):
        # No URL, status='project_live' significa "spec listo, user lo ejecuta a mano"
        with conn() as c:
            mark_live(c, opp_id, "")  # sin URL, no aplica
        chown_to_host(dest_dir)
        push_tg(
            f"📄 Project SPEC listo (sin docker): opp {opp_id}\n"
            f"<b>{opp['title'][:80]}</b>\n"
            f"Path: <code>{dest_dir}</code>\n"
            f"Lee README.md y PROJECT_SPEC.md.",
            tg_chat,
        )
        return 0

    # Docker compose up
    write_meta(dest_dir, {
        "opp_id": opp_id, "slug": slug, "port": port,
        "template": template_name, "framework": meta["framework"],
        "built_at": datetime.now(timezone.utc).isoformat(),
    })

    ok, logs = docker_compose_up(dest_dir, port)
    if not ok:
        with conn() as c:
            mark_failed(c, opp_id, "docker compose up failed")
        push_tg(f"❌ docker compose up falló opp {opp_id}\n<pre>{logs[-1500:]}</pre>", tg_chat)
        return 1

    # Healthcheck
    timeout = int(meta.get("healthcheck_timeout_s") or 60)
    print(f"[builder] healthcheck localhost:{port} (timeout {timeout}s)")
    if not healthcheck(port, timeout):
        with conn() as c:
            mark_failed(c, opp_id, "healthcheck timeout")
        push_tg(
            f"⚠️ docker arrancó pero healthcheck timeout opp {opp_id}\n"
            f"Revisa: <code>docker logs biz-hunter-project-{slug}</code>",
            tg_chat,
        )
        return 1

    chown_to_host(dest_dir)
    url = f"http://localhost:{port}"
    with conn() as c:
        mark_live(c, opp_id, url)

    push_tg(
        f"🚀 <b>Project live</b>: opp {opp_id}\n"
        f"<b>{opp['title'][:120]}</b>\n"
        f"→ {url}\n"
        f"Template: <code>{template_name}</code>",
        tg_chat,
    )
    print(f"[builder] OK opp {opp_id} → {url}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--opp", type=int, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--tg-chat", default=None)
    args = parser.parse_args()
    sys.exit(main(args.opp, args.force, args.rebuild, args.tg_chat))
