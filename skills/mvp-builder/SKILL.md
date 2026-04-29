---
name: mvp-builder
description: Toma las top-3 oportunidades validated sin MVP cada 24h, genera el contenido (landing si score<80, landing+tool si score≥80) con form que postea a webhook n8n→Postgres, y deploya a Cloudflare Pages. Marca la opp como mvp_live con la URL pública.
version: 0.1.0
author: david
metadata:
  hermes:
    tags: [biz-hunter, mvp, deploy]
    category: biz-hunter
---

# MVP Builder

Tu trabajo: tomar las **top-3 oportunidades validated** (sin `mvp_path`), generar el MVP correspondiente y desplegarlo a Cloudflare Pages.

## Reglas de operación

1. **Top-3 por score** ordenado descendente. Solo `status=validated` y `mvp_path IS NULL`.
2. **Tipo de MVP según score**:
   - `60 ≤ score < 80`: solo landing + waitlist (n8n webhook).
   - `score ≥ 80`: landing + herramienta funcional básica (Python/JS según naturaleza).
3. **Stack landing**: HTML + Tailwind via CDN (sin build step). Una sola página, sin SPA. Mobile-first.
4. **Stack tool funcional**: si es lógica client-side → vanilla JS en la misma página. Si requiere backend → FastAPI single-file en `data/mvps/<slug>/server.py` (despliegue manual cuando llegue ese caso, por ahora marca `mvp_type=tool` y deja note).
5. **Privacidad**: cada landing lleva `<meta name="robots" content="noindex,nofollow">` hasta que llegue a `traction`.
6. **Sin marca propia**: nada que mencione tu nombre o Convertix. La landing tiene que parecer un experimento independiente.

## Estructura por MVP

```
data/mvps/<slug>/
├── index.html
├── deploy_meta.json    # { "cf_pages_url": "...", "deployed_at": "...", "mvp_slug": "..." }
└── README.md           # qué problema resuelve, vertical, MVP type, score
```

`<slug>` = `kebab-case` del título de la opp (limit 50 chars).

## Flujo por opp

1. **Genera contenido** con Claude (Sonnet 4.6, temperatura 0.7):
   - Hero: headline directo (problema ↔ promesa de solución).
   - Sección problema (3-5 bullets con el pain point real).
   - Sección solución (qué resuelve el producto).
   - Beneficios (3 bullets concretos).
   - CTA de waitlist con formulario n8n webhook.
   - Footer mínimo (sin marca, solo "© 2026").

2. **Genera HTML** insertando el copy en una plantilla base (incluida en `data/mvps/_template/index.html` — la creas la primera vez).

3. **Inyecta el formulario** en el HTML que postea al webhook n8n. NO hace
   falta crear nada nuevo por cada landing — usamos un único webhook
   `${N8N_WEBHOOK_SIGNUP_URL}` que inserta en la tabla `waitlist_signups`
   (Postgres VPS) etiquetando con el `mvp_slug` para distinguir.

   Plantilla:

   ```html
   <form id="waitlist" onsubmit="return submitSignup(event)">
     <input type="email" name="email" required placeholder="tu@email.com">
     <button type="submit">Get early access</button>
   </form>

   <script>
   const SIGNUP_URL = "{{N8N_WEBHOOK_SIGNUP_URL}}";
   const MVP_SLUG = "{{MVP_SLUG}}";

   async function submitSignup(e) {
     e.preventDefault();
     const email = e.target.email.value;
     const r = await fetch(SIGNUP_URL, {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ mvp_slug: MVP_SLUG, email })
     });
     if (r.ok) e.target.outerHTML = "<p>✅ Estás dentro. Te avisamos pronto.</p>";
     else alert("Error, prueba de nuevo");
     return false;
   }
   </script>
   ```

   Reemplaza `{{N8N_WEBHOOK_SIGNUP_URL}}` (del env) y `{{MVP_SLUG}}`
   (slug de la opp) en el HTML antes de deployar. **No exponemos
   credenciales** — el webhook valida y filtra el input en n8n.

4. **Deploy a Cloudflare Pages**:
   - Comando: `wrangler pages deploy data/mvps/<slug> --project-name biz-hunter-mvps`
   - El subdominio queda `https://<commit-hash>.biz-hunter-mvps.pages.dev`.
   - Captura la URL en `deploy_meta.json`.

5. **Update BD**:
   ```sql
   UPDATE opportunities SET
     status = 'mvp_live',
     mvp_path = 'data/mvps/<slug>',
     mvp_url = '<cf_pages_url>',
     mvp_type = 'landing'  -- o 'tool' si score≥80
   WHERE id = ?;
   ```

## Implementación

```python
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/opt/biz-hunter/data/opportunities.db")
MVPS_DIR = Path("/opt/biz-hunter/data/mvps")
TEMPLATE = MVPS_DIR / "_template" / "index.html"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:50]


def fetch_top_validated(conn, n: int = 3) -> list[dict]:
    cur = conn.execute(
        """SELECT id, title, pain_point, vertical, score, score_reasoning
           FROM opportunities
           WHERE status = 'validated' AND mvp_path IS NULL
           ORDER BY score DESC
           LIMIT ?""",
        (n,),
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def deploy_to_cloudflare(slug: str, mvp_dir: Path) -> str:
    result = subprocess.run(
        ["wrangler", "pages", "deploy", str(mvp_dir), "--project-name", "biz-hunter"],
        capture_output=True, text=True, check=True,
    )
    # Parsear URL del output de wrangler
    for line in result.stdout.splitlines():
        if "https://" in line and ".pages.dev" in line:
            return line.strip().split()[-1]
    raise RuntimeError("No se pudo extraer URL de wrangler output")


# (continúa con flujo completo: para cada opp, generar HTML con Claude,
#  crear form n8n webhook, insertar action, deploy, update BD)
```

## Plantilla HTML base (genérica)

Se crea **la primera vez** que se ejecuta el builder en `data/mvps/_template/index.html`. Tiene placeholders tipo `{{HEADLINE}}`, `{{PROBLEM_BULLETS}}`, `{{FORM_ACTION}}`, etc.

## Output esperado

```
## Builder run @ 2026-04-28T03:00 UTC

Top-3 validated procesadas:

1. [#142] "Newsletter unsubscribe analytics" — score 78 → landing
   Slug: newsletter-unsubscribe-analytics
   URL: https://abc123.biz-hunter.pages.dev
   Form ID: xyzpdq
   Status: mvp_live ✅

2. [#150] "AI prompt pack para SEO local" — score 82 → landing+tool
   Slug: ai-prompt-pack-seo-local
   URL: https://def456.biz-hunter.pages.dev
   Form ID: abcdef
   Status: mvp_live ✅
   Note: tool funcional pendiente (requiere backend, marcado mvp_type=tool)

3. [#149] "Deal alerts feed para AppSumo lifetime deals" — score 71 → landing
   Slug: appsumo-deal-alerts
   ...

Coste tokens: ~50k input / ~12k output Sonnet 4.6 = ~$0.30
Deploys CF Pages: 3 (límite mes 500, va sobrado)
```

## Frecuencia

Cron: `0 3 * * *` (3am cada día — offpeak para no competir por wrangler).
