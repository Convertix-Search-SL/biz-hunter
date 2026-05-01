"""Plantilla digital_product — sin Docker. Genera spec + outline PDF + draft Gumroad listing."""
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.llm import ask_text


SPEC_SYSTEM = """Eres un creator de productos digitales (ebooks, plantillas, cursos cortos).
Recibes una oportunidad y diseñas el producto MÁS SIMPLE que valida demanda.

Devuelve markdown con:
1. Producto recomendado (ebook 30-40 páginas | plantilla Notion | mini-curso 5 lecciones)
2. Outline detallado (capítulos/secciones)
3. Pricing sugerido y rationale
4. Plataforma sugerida (Gumroad/LemonSqueezy)
"""


LISTING_SYSTEM = """Generas un draft de listing para Gumroad/LemonSqueezy.
Devuelve markdown con:
- Title (60-80 chars)
- Subtitle (130-150 chars)
- Description (3-4 párrafos, en formato bullets)
- Tags (5-7)
- Suggested price tier
- 5 ideas de hero image / cover
"""


def build(opp: dict, dest_dir: Path, port: int | None = None) -> dict:  # noqa: ARG001
    dest_dir.mkdir(parents=True, exist_ok=True)

    spec_user = (
        f"Pain point: {opp['pain_point']}\n"
        f"Título: {opp['title']}\n"
        f"Score: {opp.get('score', '?')}/100"
    )
    spec = ask_text(SPEC_SYSTEM, spec_user, max_tokens=3000)
    listing = ask_text(LISTING_SYSTEM, spec_user + "\n\n## Spec del producto\n" + spec[:1500], max_tokens=2000)

    (dest_dir / "PROJECT_SPEC.md").write_text(spec)
    (dest_dir / "LISTING.md").write_text(listing)

    (dest_dir / "README.md").write_text(dedent(f"""\
        # {opp['title']} — Digital Product

        Sin Docker (no aplica). Pasos:

        1. Lee `PROJECT_SPEC.md` con el outline.
        2. Crea el producto siguiendo la estructura.
        3. Sube a Gumroad/LemonSqueezy con el listing de `LISTING.md`.
        4. Apunta la landing waitlist (`mvp_url` en BD) al checkout.
    """))

    return {
        "framework": "digital_product",
        "has_docker": False,
        "healthcheck_timeout_s": None,
        "spec_md": spec,
    }
