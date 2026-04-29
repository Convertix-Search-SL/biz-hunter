#!/usr/bin/env python3
"""MVP Builder — top-3 validated → genera landing → deploy a CF Pages.

Para cada opp:
- Score < 80 → solo landing + waitlist.
- Score ≥ 80 → landing con CTA hacia tool funcional (la tool requiere backend
  manual por ahora, así que el flag mvp_type='tool' indica que falta build
  hands-on, pero el landing+waitlist YA mide demanda).

El form postea al webhook n8n que ya tenemos (`waitlist_signups`).
Deploy via `wrangler pages deploy` con CLOUDFLARE_API_TOKEN.

Cron: 3am diario.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn
from lib.llm import ask_text
from lib.notify import send_telegram


REPO_ROOT = Path(__file__).parent.parent
MVPS_DIR = REPO_ROOT / "data" / "mvps"
MVPS_DIR.mkdir(parents=True, exist_ok=True)

CF_PROJECT = os.environ.get("CF_PAGES_PROJECT", "biz-hunter-mvps")
CF_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
N8N_SIGNUP_URL = os.environ.get(
    "N8N_WEBHOOK_SIGNUP_URL", "https://n8n.convertix.net/webhook/biz-hunter/signup"
)
TOP_N = 3


COPY_SYSTEM = """Eres un copywriter de landings de validación de demanda.
Generas el copy para una landing que valida una oportunidad de negocio detectada.
La landing tiene: hero (h1 + subhead), 3-5 bullets de pain point, 3 bullets de
beneficios/solución, y un CTA de waitlist.

Reglas duras:
- NO menciones marca propia, NO digas que eres una empresa establecida.
- Pretende ser un fundador solo construyendo algo para resolver un dolor real.
- Idioma: igual que el target keyword (suele ser inglés en posts de Reddit/HN).
- Tono: directo, sin fluff, sin emojis. Como un IndieHacker que vende su MVP.
- NO inventes precios ni features irreales. La landing valida demanda, no vende.

Devuelve TEXTO PLANO (NO markdown, NO JSON), exactamente con este formato (separadores ---):

H1: <una línea, 60-80 chars>
SUBHEAD: <una línea, 100-140 chars>
---PAIN
- bullet 1
- bullet 2
- bullet 3
---SOLUTION
- bullet 1
- bullet 2
- bullet 3
---CTA
<call-to-action button text, 2-4 palabras>
---REASSURANCE
<una línea bajo el form, 80-120 chars>
"""


def slugify(s: str, maxlen: int = 50) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:maxlen] or "mvp"


def parse_copy(text: str) -> dict:
    sections = {"H1": "", "SUBHEAD": "", "PAIN": [], "SOLUTION": [], "CTA": "Get early access", "REASSURANCE": ""}
    current = None
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("H1:"):
            sections["H1"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("SUBHEAD:"):
            sections["SUBHEAD"] = line.split(":", 1)[1].strip()
            continue
        if line.startswith("---PAIN"):
            current = "PAIN"; continue
        if line.startswith("---SOLUTION"):
            current = "SOLUTION"; continue
        if line.startswith("---CTA"):
            current = "CTA"; continue
        if line.startswith("---REASSURANCE"):
            current = "REASSURANCE"; continue
        if current in ("PAIN", "SOLUTION") and line.startswith("-"):
            sections[current].append(line.lstrip("- ").strip())
        elif current == "CTA" and line.strip():
            sections["CTA"] = line.strip()
        elif current == "REASSURANCE" and line.strip():
            sections["REASSURANCE"] = line.strip()
    return sections


def render_html(copy: dict, mvp_slug: str) -> str:
    pain_html = "\n".join(f'  <li>{p}</li>' for p in copy["PAIN"])
    sol_html = "\n".join(f'  <li>{p}</li>' for p in copy["SOLUTION"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{copy['H1']}</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen flex flex-col">
<main class="max-w-2xl mx-auto px-6 py-16 flex-1">
<h1 class="text-4xl md:text-5xl font-bold leading-tight mb-4">{copy['H1']}</h1>
<p class="text-lg text-gray-400 mb-10">{copy['SUBHEAD']}</p>

<section class="mb-10">
  <h2 class="text-xs uppercase tracking-widest text-gray-500 mb-3">The problem</h2>
  <ul class="space-y-2 text-gray-200 list-disc list-inside">
{pain_html}
  </ul>
</section>

<section class="mb-10">
  <h2 class="text-xs uppercase tracking-widest text-gray-500 mb-3">What we're building</h2>
  <ul class="space-y-2 text-gray-200 list-disc list-inside">
{sol_html}
  </ul>
</section>

<form id="waitlist" onsubmit="return submitSignup(event)" class="bg-gray-900 border border-gray-800 rounded-lg p-5">
  <label class="block text-sm font-medium mb-2">Get early access</label>
  <div class="flex gap-2">
    <input type="email" name="email" required autocomplete="email"
      placeholder="you@example.com"
      class="flex-1 bg-gray-950 border border-gray-700 rounded px-3 py-2 text-gray-100 focus:border-blue-500 focus:outline-none">
    <button type="submit"
      class="bg-blue-600 hover:bg-blue-500 text-white font-medium px-4 py-2 rounded">
      {copy['CTA']}
    </button>
  </div>
  <p class="mt-3 text-xs text-gray-500">{copy['REASSURANCE']}</p>
</form>

<p class="mt-12 text-xs text-gray-600">© 2026</p>
</main>

<script>
const SIGNUP_URL = "{N8N_SIGNUP_URL}";
const MVP_SLUG = "{mvp_slug}";
async function submitSignup(e) {{
  e.preventDefault();
  const email = e.target.email.value;
  try {{
    const r = await fetch(SIGNUP_URL, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ mvp_slug: MVP_SLUG, email }})
    }});
    if (r.ok) {{
      e.target.outerHTML = '<p class="text-green-400">✓ You\\'re on the list. We\\'ll be in touch.</p>';
    }} else {{
      alert("Something went wrong. Try again.");
    }}
  }} catch (err) {{
    alert("Network error.");
  }}
  return false;
}}
</script>
</body>
</html>
"""


def fetch_top_validated(c, n: int) -> list[dict]:
    cur = c.execute(
        """SELECT id, title, pain_point, vertical, score, score_reasoning
           FROM opportunities
           WHERE status = 'validated' AND mvp_path IS NULL
           ORDER BY score DESC
           LIMIT ?""",
        (n,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _wrangler_deploy(mvp_dir: Path) -> str | None:
    """Deploy via wrangler CLI si está disponible. Mejor opción cuando existe."""
    import shutil
    import subprocess

    wrangler = shutil.which("wrangler") or shutil.which("npx")
    if not wrangler:
        return None
    cmd = [
        wrangler,
        *([] if wrangler.endswith("wrangler") else ["-y", "wrangler"]),
        "pages", "deploy", str(mvp_dir),
        "--project-name", CF_PROJECT,
        "--commit-dirty=true",
        "--branch", mvp_dir.name,
    ]
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = CF_TOKEN
    env["CLOUDFLARE_ACCOUNT_ID"] = CF_ACCOUNT
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=90)
        out = r.stdout + r.stderr
        m = re.search(r"https://[a-z0-9-]+\.[a-z0-9-]+\.pages\.dev", out)
        if m:
            return m.group(0)
        print(f"[builder] wrangler no devolvió URL: {out[-300:]}")
    except subprocess.TimeoutExpired:
        print("[builder] wrangler timeout")
    except Exception as e:
        print(f"[builder] wrangler error: {e}")
    return None


def _api_deploy_direct(mvp_dir: Path) -> str | None:
    """Deploy via Cloudflare Pages Direct Upload API (sin wrangler).

    Flujo manifest-based: hash blake3 → check missing → upload → finalize.
    Útil cuando wrangler no está disponible (e.g. container cron sin node).
    """
    api_root = (
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}"
        f"/pages/projects/{CF_PROJECT}"
    )
    headers = {"Authorization": f"Bearer {CF_TOKEN}"}

    # 1. Manifest: path → hash. CF usa blake3 truncado a 32 chars hex.
    # Si no hay blake3 (no estándar en stdlib), usamos sha256 truncado:
    # CF acepta cualquier hash mientras se mantenga consistencia interna.
    files = {}
    file_data = {}
    for f in sorted(mvp_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = "/" + str(f.relative_to(mvp_dir))
        content = f.read_bytes()
        h = hashlib.sha256(content).hexdigest()[:32]
        files[rel] = h
        file_data[h] = content

    if not files:
        return None

    # 2. JWT para upload
    try:
        jwt_r = httpx.get(f"{api_root}/upload-jwt", headers=headers, timeout=30)
        if jwt_r.status_code >= 400:
            print(f"[builder] upload-jwt {jwt_r.status_code}: {jwt_r.text[:300]}")
            return None
        jwt = jwt_r.json().get("result", {}).get("jwt")
    except Exception as e:
        print(f"[builder] upload-jwt error: {e}")
        return None

    # 3. Sube los archivos al endpoint de upload (uno a uno, son pocos)
    upload_url = "https://api.cloudflare.com/client/v4/pages/assets/upload"
    upload_headers = {"Authorization": f"Bearer {jwt}"}
    payload = []
    for h, content in file_data.items():
        import base64
        payload.append({
            "key": h,
            "value": base64.b64encode(content).decode(),
            "metadata": {"contentType": "text/html"},
            "base64": True,
        })
    try:
        up = httpx.post(upload_url, headers=upload_headers, json=payload, timeout=60)
        if up.status_code >= 400:
            print(f"[builder] upload assets {up.status_code}: {up.text[:300]}")
            return None
    except Exception as e:
        print(f"[builder] upload error: {e}")
        return None

    # 4. Crear deployment con manifest
    try:
        deploy_r = httpx.post(
            f"{api_root}/deployments",
            headers=headers,
            files={"manifest": (None, json.dumps(files), "application/json"),
                   "branch": (None, mvp_dir.name)},
            timeout=60,
        )
        if deploy_r.status_code >= 400:
            print(f"[builder] deployment {deploy_r.status_code}: {deploy_r.text[:300]}")
            return None
        url = deploy_r.json().get("result", {}).get("url")
        return url
    except Exception as e:
        print(f"[builder] deployment error: {e}")
        return None


def deploy_to_cloudflare(mvp_dir: Path) -> str | None:
    """Intenta wrangler primero (más fiable), cae al API REST si no está."""
    if not CF_TOKEN or not CF_ACCOUNT:
        print("[builder] CLOUDFLARE_API_TOKEN o ACCOUNT_ID no configurados")
        return None
    url = _wrangler_deploy(mvp_dir)
    if url:
        return url
    return _api_deploy_direct(mvp_dir)


def update_mvp(c, opp_id: int, slug: str, mvp_path: str, mvp_url: str | None, mvp_type: str):
    c.execute(
        """UPDATE opportunities SET
             status='mvp_live', mvp_path=?, mvp_url=?, mvp_type=?
           WHERE id=?""",
        (mvp_path, mvp_url, mvp_type, opp_id),
    )


def build_one(opp: dict) -> dict:
    """Genera HTML, lo guarda, intenta deploy. Devuelve summary."""
    slug = slugify(opp["title"])
    mvp_dir = MVPS_DIR / slug
    mvp_dir.mkdir(parents=True, exist_ok=True)

    # Copy via Claude
    user = (
        f"## Oportunidad\n"
        f"Título: {opp['title']}\n"
        f"Vertical: {opp['vertical']}\n"
        f"Pain point: {opp['pain_point']}\n"
        f"Score: {opp['score']}/100 — {opp.get('score_reasoning', '')[:300]}"
    )
    raw_copy = ask_text(COPY_SYSTEM, user, max_tokens=2048)
    copy = parse_copy(raw_copy)

    html = render_html(copy, slug)
    (mvp_dir / "index.html").write_text(html)

    mvp_url = deploy_to_cloudflare(mvp_dir)
    mvp_type = "tool" if opp["score"] >= 80 else "landing"

    meta = {
        "slug": slug,
        "deployed_url": mvp_url,
        "mvp_type": mvp_type,
        "h1": copy["H1"],
        "score": opp["score"],
        "needs_followup_tool": opp["score"] >= 80,
    }
    (mvp_dir / "deploy_meta.json").write_text(json.dumps(meta, indent=2))

    return {
        "opp_id": opp["id"],
        "slug": slug,
        "mvp_url": mvp_url,
        "mvp_type": mvp_type,
        "title": opp["title"],
        "score": opp["score"],
    }


def main() -> int:
    with conn() as c:
        top = fetch_top_validated(c, TOP_N)

    if not top:
        print("[builder] no hay validated sin MVP")
        send_telegram("🛠 *Builder*: 0 validated pendientes de MVP.")
        return 0

    print(f"[builder] {len(top)} opps a montar (top score {top[0]['score']})")

    results = []
    failures = 0
    for opp in top:
        try:
            r = build_one(opp)
            results.append(r)
            mvp_path_rel = f"data/mvps/{r['slug']}"
            with conn() as c:
                update_mvp(c, opp["id"], r["slug"], mvp_path_rel, r["mvp_url"], r["mvp_type"])
        except Exception as e:
            failures += 1
            print(f"[builder] error en opp {opp['id']}: {e}")

    lines = [f"🛠 *Builder run*", f"MVPs montados: {len(results)} / {len(top)}"]
    for r in results:
        emoji = "🚀" if r["mvp_url"] else "⚠️"
        lines.append(f"{emoji} `[{r['score']}]` _{r['mvp_type']}_ — {r['title'][:60]}")
        if r["mvp_url"]:
            lines.append(f"   {r['mvp_url']}")
        else:
            lines.append("   (deploy falló — HTML local OK, requiere deploy manual)")
    if failures:
        lines.append(f"❌ Errores: {failures}")
    send_telegram("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
