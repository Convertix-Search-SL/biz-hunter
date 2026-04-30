"""Plantilla newsletter — sin Docker. Genera setup notes Beehiiv + 3 emails seed."""
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.llm import ask_text


SPEC_SYSTEM = """Eres un editor de newsletters de nicho. Diseñas la
estructura de una newsletter sobre el pain point dado.

Devuelve markdown con:
1. Nombre sugerido (3 opciones)
2. Pitch (140 chars)
3. Cadencia recomendada (semanal | quincenal)
4. Estructura del email (secciones fijas)
5. 3 segmentos de audiencia diferenciados
6. Setup notes para Beehiiv (cómo configurar la publicación)
"""


EMAIL_SYSTEM = """Generas un email de bienvenida/onboarding para una
newsletter recién lanzada.

Reglas:
- Plain text con líneas cortas (máx 80 chars).
- Sin emojis. Sin marketing fluff.
- Personal, escrito en primera persona.
- Promete valor concreto y dice qué viene en la próxima edición.
- 200-350 palabras.

Devuelve SOLO el cuerpo del email (sin asunto, sin firma)."""


def build(opp: dict, dest_dir: Path) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "emails").mkdir(exist_ok=True)

    spec_user = (
        f"Pain point: {opp['pain_point']}\n"
        f"Título original: {opp['title']}\n"
    )
    spec = ask_text(SPEC_SYSTEM, spec_user, max_tokens=2500)

    # 3 emails seed (welcome + 2 ediciones piloto)
    emails: list[str] = []
    for ed in [
        ("welcome", "Email de bienvenida cuando alguien se suscribe"),
        ("issue-01", "Primera edición real con valor inmediato"),
        ("issue-02", "Segunda edición con un caso/recurso concreto"),
    ]:
        slug, brief = ed
        body = ask_text(
            EMAIL_SYSTEM,
            f"Brief: {brief}\nPain point: {opp['pain_point']}\n\nGenera el email.",
            max_tokens=1500,
        )
        (dest_dir / "emails" / f"{slug}.md").write_text(body)
        emails.append(slug)

    (dest_dir / "PROJECT_SPEC.md").write_text(spec)
    (dest_dir / "SETUP.md").write_text(dedent(f"""\
        # Newsletter setup

        1. Beehiiv (https://www.beehiiv.com/) — crea publication con el nombre del spec.
        2. Importa el welcome email como "Welcome automation" (`emails/welcome.md`).
        3. Programa `emails/issue-01.md` para el primer envío.
        4. Apunta la landing waitlist (`mvp_url`) a la signup form de Beehiiv.

        Emails seed listos: {", ".join(emails)}.
    """))

    (dest_dir / "README.md").write_text(dedent(f"""\
        # {opp['title']} — Newsletter

        Sin Docker. Setup en `SETUP.md`. Spec en `PROJECT_SPEC.md`.
        3 emails seed generados en `emails/`.
    """))

    return {
        "framework": "newsletter",
        "has_docker": False,
        "healthcheck_timeout_s": None,
        "spec_md": spec,
    }
