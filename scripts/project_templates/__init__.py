"""Plantillas de generación de proyectos por vertical.

Cada módulo expone:
    build(opp: dict, dest_dir: Path, port: int | None) -> dict

Devuelve metadata mínima:
    {
        "framework": str,
        "has_docker": bool,
        "healthcheck_timeout_s": int | None,  # None si has_docker=False
        "spec_md": str,                       # PRD para guardar en BD
    }

`port` es el host port asignado por project_registry. Las plantillas con
Docker lo embeden literal en el docker-compose.yml (no via ${VAR}).
Las plantillas sin Docker (digital_product, newsletter) ignoran port.
"""
from . import content_seo, digital_product, microsaas, newsletter


# Map vertical → módulo plantilla. Si vertical desconocido → microsaas.
TEMPLATES = {
    "microsaas": microsaas,
    "content_seo": content_seo,
    "digital_product": digital_product,
    "newsletter": newsletter,
}


def get_template(vertical: str | None):
    return TEMPLATES.get(vertical or "microsaas", microsaas)
