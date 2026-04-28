"""Wrapper Cloudflare Pages para deployar landings de MVPs.

Uso:
    python scripts/deploy_landing.py data/mvps/<slug>

Requiere `wrangler` instalado y `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`
en el entorno. La salida del comando se parsea para extraer la URL pública.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


CF_PAGES_PROJECT = os.environ.get("CF_PAGES_PROJECT", "biz-hunter")
URL_RE = re.compile(r"https://[a-z0-9-]+\.[a-z0-9-]+\.pages\.dev")


def deploy(mvp_dir: Path) -> str:
    if not mvp_dir.is_dir():
        raise FileNotFoundError(f"No existe: {mvp_dir}")
    if not (mvp_dir / "index.html").is_file():
        raise FileNotFoundError(f"No hay index.html en {mvp_dir}")

    cmd = [
        "wrangler", "pages", "deploy", str(mvp_dir),
        "--project-name", CF_PAGES_PROJECT,
        "--commit-dirty=true",
    ]
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    print("--- stdout ---")
    print(result.stdout)
    if result.stderr:
        print("--- stderr ---")
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"wrangler falló con code {result.returncode}")

    match = URL_RE.search(result.stdout + result.stderr)
    if not match:
        raise RuntimeError("No pude parsear la URL pública del output de wrangler")
    return match.group(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mvp_dir", type=Path, help="Carpeta con index.html del MVP")
    args = parser.parse_args()

    try:
        url = deploy(args.mvp_dir)
        print(f"\n✅ Deployed: {url}")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
