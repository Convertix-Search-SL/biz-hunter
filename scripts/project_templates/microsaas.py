"""Plantilla microsaas — FastAPI single-file + frontend HTML/Tailwind.

3 LLM calls:
1. SPEC JSON con feature core (endpoint, schemas, lógica).
2. app.py FastAPI con SQLite local.
3. static/index.html Tailwind CDN que llama al endpoint.
"""
import ast
import json
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.llm import ask_json, ask_text


SPEC_SYSTEM = """Eres un product designer de microSaaS bootstrap.
Recibes una oportunidad de negocio y defines el feature MÁS SIMPLE que
demuestra valor real (no MVP completo, no SaaS con auth/billing — solo
la herramienta core que resuelve el dolor en 1 endpoint).

Devuelve SOLO JSON con este formato:
{
  "feature_name": "kebab-case-corto",
  "endpoint": "/api/<verbo>",
  "method": "POST" | "GET",
  "input_schema": {...},        // pydantic-style fields
  "output_schema": {...},
  "logic_summary": "1-3 frases describiendo qué hace el endpoint",
  "ui_summary": "1 frase: cómo se usa desde el frontend"
}
"""


CODE_SYSTEM = """Eres un dev senior Python. Generas FastAPI single-file
(app.py) deployable. Reglas:

- SQLite local en /data/db.sqlite (creado al arrancar).
- Tabla(s) que necesite la lógica.
- Sin auth, sin billing, sin multi-tenant. V1.
- CORS abierto (permitir localhost:* y file://).
- Servir static/ en /.
- uvicorn arranca en host=0.0.0.0, port=8000.
- Cero dependencias externas más allá de fastapi[standard], pydantic.
- Manejo de errores básico (HTTPException con mensaje útil).
- Comentarios mínimos: solo donde el "por qué" no es obvio.

Devuelve SOLO el código Python, sin code fence ni explicación."""


HTML_SYSTEM = """Generas HTML+Tailwind (CDN, sin build) que invoca un
endpoint FastAPI local via fetch.

Reglas:
- 1 archivo, 1 página, sin SPA framework.
- Mobile-first responsive. Dark theme (bg-gray-950).
- Form principal con inputs según input_schema, botón submit.
- Muestra el output_schema en una card debajo, formato útil al user.
- Sin emojis, sin marketing. Es una tool, no una landing.
- Usa fetch async/await, maneja errores mostrando alert.

Devuelve SOLO el HTML, sin code fence."""


def _strip_fence(s: str) -> str:
    if s.startswith("```"):
        lines = s.splitlines()
        s = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return s


def build(opp: dict, dest_dir: Path, port: int | None = None) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "static").mkdir(exist_ok=True)
    (dest_dir / "data").mkdir(exist_ok=True)

    # 1. SPEC
    spec_user = (
        f"## Oportunidad\n"
        f"Título: {opp['title']}\n"
        f"Pain point: {opp['pain_point']}\n"
        f"Score: {opp.get('score', 'N/A')}/100\n"
        f"Razonamiento: {(opp.get('score_reasoning') or '')[:400]}"
    )
    spec = ask_json(SPEC_SYSTEM, spec_user, max_tokens=1500)

    # 2. app.py — max_tokens alto + retry si parse falla.
    # FastAPI single-file con SQLite + endpoint puede pasar de 4k tokens.
    code_user = (
        f"Spec del feature:\n```json\n{json.dumps(spec, indent=2)}\n```\n\n"
        f"Genera el `app.py` completo. Mantén el código compacto para que quepa en una sola respuesta."
    )
    app_py = None
    for attempt in range(2):
        candidate = _strip_fence(ask_text(CODE_SYSTEM, code_user, max_tokens=8192))
        try:
            ast.parse(candidate)
            app_py = candidate
            break
        except SyntaxError as e:
            print(f"[microsaas] app.py parse falló intento {attempt + 1}: {e}")
            code_user += f"\n\nNota: la respuesta anterior tenía SyntaxError ({e}). Genera código completo y compilable."
    if app_py is None:
        # Fallback: usar último intento aunque tenga sintaxis rota — el user
        # lo verá en logs y podrá iterar a mano.
        app_py = candidate
        print("[microsaas] WARN: app.py con SyntaxError tras 2 intentos, escribiendo igualmente")

    # 3. index.html
    html_user = (
        f"Spec del feature:\n```json\n{json.dumps(spec, indent=2)}\n```\n\n"
        f"Genera el `static/index.html` que llama a {spec['endpoint']}."
    )
    html = _strip_fence(ask_text(HTML_SYSTEM, html_user, max_tokens=3000))

    # Render archivos
    (dest_dir / "app.py").write_text(app_py)
    (dest_dir / "static" / "index.html").write_text(html)

    (dest_dir / "Dockerfile").write_text(dedent("""\
        FROM python:3.13-slim
        WORKDIR /app
        RUN pip install --no-cache-dir 'fastapi[standard]' uvicorn pydantic
        COPY app.py /app/app.py
        COPY static /app/static
        RUN mkdir -p /app/data
        EXPOSE 8000
        CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
    """))

    # Port hardcoded (no ${VAR}) para evitar problemas de env propagation
    # cuando el compose lo lanza un subprocess desde otro container.
    # Volumen NAMED (no bind ./data) porque el daemon del host no resuelve
    # el path relativo cuando el cliente compose corre desde otro container.
    host_port = port or 8000
    (dest_dir / "docker-compose.yml").write_text(dedent(f"""\
        services:
          app:
            build: .
            container_name: biz-hunter-project-{dest_dir.name}
            ports:
              - "{host_port}:8000"
            volumes:
              - app-data:/app/data
            restart: unless-stopped

        volumes:
          app-data:
    """))

    spec_md = dedent(f"""\
        # {opp['title']}

        ## Feature: `{spec.get('feature_name', '?')}`

        **Endpoint:** `{spec.get('method', 'POST')} {spec.get('endpoint', '/api/?')}`

        **Lógica:** {spec.get('logic_summary', '')}

        **UI:** {spec.get('ui_summary', '')}

        ## Input
        ```json
        {json.dumps(spec.get('input_schema', {}), indent=2)}
        ```

        ## Output
        ```json
        {json.dumps(spec.get('output_schema', {}), indent=2)}
        ```

        ## Pain point original
        {opp['pain_point']}
    """)
    (dest_dir / "PROJECT_SPEC.md").write_text(spec_md)

    (dest_dir / "README.md").write_text(dedent(f"""\
        # {opp['title']}

        V1 funcional generado por biz-hunter project_builder.

        ## Run
        ```bash
        docker compose up -d --build
        # Abre http://localhost:{host_port}
        ```

        ## Itera
        - Lógica core: `app.py`
        - UI: `static/index.html`
        - Spec del feature: `PROJECT_SPEC.md`
        - Cambia el puerto editando `docker-compose.yml`
    """))

    return {
        "framework": "fastapi",
        "has_docker": True,
        "healthcheck_timeout_s": 60,
        "spec_md": spec_md,
    }
