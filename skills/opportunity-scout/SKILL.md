---
name: opportunity-scout
description: Escanea fuentes públicas (Reddit, IndieHackers, Hacker News, Product Hunt, Google Trends, X) buscando pain points y oportunidades de negocio low-budget. Inserta hallazgos en data/opportunities.db con status=raw para validación posterior.
version: 0.1.0
author: david
metadata:
  hermes:
    tags: [biz-hunter, research, scraping]
    category: biz-hunter
---

# Opportunity Scout

Tu trabajo es escanear fuentes públicas y detectar pain points / oportunidades de negocio que cumplan los criterios definidos en `/opt/biz-hunter/strategy/hunting-rules.md`. Insertas cada hallazgo en `/opt/biz-hunter/data/opportunities.db` con `status=raw`.

## Reglas de operación

1. Lee siempre `/opt/biz-hunter/strategy/hunting-rules.md` antes de empezar — define vetos y filosofía.
2. **Antes de insertar** una opp, verifica que no esté duplicada (consulta BD: mismo `title` o `source_url` en últimos 30 días).
3. Target: **10-20 opps nuevas por ejecución**. No fuerces si no hay material decente.
4. Cada opp debe incluir: `title`, `pain_point`, `vertical`, `source`, `source_url`, `raw_signals` (JSON con los datos que usaste para detectarla).
5. **NO scoreas** aquí — eso lo hace `opportunity-validator`. Solo identifica y registra.
6. Aplica **vetos hard** del archivo de reglas: si la opp es claramente MLM, dropship Aliexpress, NSFW, etc., no la insertes (NO la registres como vetoed — simplemente ignórala).

## Fuentes priorizadas

| Fuente | Cómo | Tools |
|---|---|---|
| Reddit | `https://www.reddit.com/r/{Entrepreneur,SaaS,IndieHackers,sideproject}/top.json?t=week` | `web_extract` |
| IndieHackers | `https://www.indiehackers.com/posts` filtros recientes | `web_extract` o `browser_tool` si requiere JS |
| Hacker News | `https://hn.algolia.com/api/v1/search_by_date?tags=ask_hn,show_hn&numericFilters=created_at_i>{ts_24h}` | `web_extract` |
| Product Hunt | `https://www.producthunt.com/leaderboard/daily/{date}` | `browser_tool` |
| Google Trends | `pytrends` lib via `execute_code` (rising queries por categoría) | `execute_code` |
| X / Twitter | búsquedas tipo "I wish there was a tool that..." | `browser_tool` con cookies persistentes |

## Verticals a clasificar

Cada opp debe tener exactamente uno: `microsaas`, `content_seo`, `digital_product`, `newsletter`. Si dudas, usa el LLM para clasificar a partir del `pain_point`.

## Implementación

Usa `execute_code` para ejecutar este flujo Python (single-file, modular):

```python
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = Path("/opt/biz-hunter/data/opportunities.db")
RULES = Path("/opt/biz-hunter/strategy/hunting-rules.md")


def already_exists(conn: sqlite3.Connection, title: str, url: str | None) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    if url:
        row = conn.execute(
            "SELECT 1 FROM opportunities WHERE source_url = ? AND discovered_at > ? LIMIT 1",
            (url, cutoff),
        ).fetchone()
        if row:
            return True
    row = conn.execute(
        "SELECT 1 FROM opportunities WHERE title = ? AND discovered_at > ? LIMIT 1",
        (title, cutoff),
    ).fetchone()
    return bool(row)


def insert_opp(conn: sqlite3.Connection, opp: dict) -> int | None:
    if already_exists(conn, opp["title"], opp.get("source_url")):
        return None
    cur = conn.execute(
        """INSERT INTO opportunities
           (source, source_url, title, pain_point, vertical, raw_signals, status)
           VALUES (?, ?, ?, ?, ?, ?, 'raw')""",
        (
            opp["source"],
            opp.get("source_url"),
            opp["title"],
            opp["pain_point"],
            opp.get("vertical"),
            json.dumps(opp.get("raw_signals", {})),
        ),
    )
    return cur.lastrowid


# 1. Lee reglas para tener vetos en contexto
rules_text = RULES.read_text()

# 2. Scout: usa web_extract / browser_tool / execute_code para cada fuente
# (el agente decide qué fuentes priorizar según hora del día y estado del backlog)

# 3. Por cada hallazgo, normaliza a dict {source, source_url, title, pain_point, vertical, raw_signals}
# y llama a insert_opp(conn, opp)

# 4. Reporta al final: cuántas opps nuevas, por fuente, por vertical.
```

## Output esperado

Al terminar, devuelve un resumen markdown:

```
## Scout run @ 2026-04-28T14:00 UTC

Inserted N opps:
- reddit:r/SaaS → 4 (microsaas: 3, content_seo: 1)
- indiehackers → 3 (microsaas: 2, digital_product: 1)
- producthunt → 5 (...)

Skipped M (duplicates last 30d).
Vetoed K (failed hard rules).
```

## Frecuencia

Cron: `0 */6 * * *` (cada 6 horas).
