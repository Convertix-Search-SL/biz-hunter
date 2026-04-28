---
name: opportunity-validator
description: Toma oportunidades en status=raw, las valida con datos públicos (SERP, Trends, contraste con vetos) y les asigna un score 0-100 + razonamiento. Promueve a status=validated si score≥60, o vetoed si choca con reglas hard.
version: 0.1.0
author: david
metadata:
  hermes:
    tags: [biz-hunter, validation, scoring]
    category: biz-hunter
---

# Opportunity Validator

Tu trabajo es procesar todo el backlog de oportunidades en `status=raw` y darle un veredicto: **scoreada y validada**, **vetada** o **necesita más info**.

## Reglas de operación

1. **Lee siempre** `/opt/biz-hunter/strategy/hunting-rules.md` al empezar. Define los 5 sub-scores (Demanda, Competencia, Capital, Time-to-MVP, Monetization) de 0 a 20 y los vetos hard.
2. **Procesa todo** el backlog `raw` por orden de antigüedad. Sin límite por ejecución (si hay 50, scorealas las 50).
3. **No re-scorees** opps que ya tengan score (a menos que el user lo pida explícitamente con `--rescore`).
4. **Usa Sonnet 4.6** para razonar el score (no Opus — overkill, no Haiku — falta criterio).
5. Cada validación produce: `score` (0-100), `score_reasoning` (markdown explicando los 5 sub-scores), `veto_reasons` (JSON list si aplica).

## Flujo por opp

Para cada opp `raw`:

1. **Aplica vetos hard primero** (cheap):
   - Comprueba contra la lista del archivo de reglas (MLM, dropship Aliexpress, crypto pump, NSFW, médico/legal, apuestas, wrappers ChatGPT triviales, productos físicos con stock).
   - Si veta: `status=vetoed`, llena `veto_reasons` con las claves que disparan el veto.
   - **Si veta, no consume tokens en el resto del análisis**.

2. **Recoge señales adicionales** (web):
   - SERP top 10 para la keyword principal del pain point (`web_search`).
   - Volumen de búsqueda aproximado (Google Trends via `execute_code` con `pytrends`).
   - Reddit search count para la query (más threads = más demanda).
   - Producto Hunt: ¿hay productos en este nicho? Calidad?

3. **Razona los 5 sub-scores** (Sonnet 4.6 con temperatura baja):
   - Demanda (0-20)
   - Competencia (0-20)
   - Capital required (0-20)
   - Time-to-MVP (0-20)
   - Monetization (0-20)
   - Suma → `score` total.

4. **Promociona**:
   - `score ≥ 60` → `status=validated`.
   - `score < 60` → `status=raw` se queda (no se vuelve a scorear, pero queda en BD).

## Implementación

```python
import json
import sqlite3
from pathlib import Path

DB = Path("/opt/biz-hunter/data/opportunities.db")
RULES = Path("/opt/biz-hunter/strategy/hunting-rules.md")


def fetch_raw(conn) -> list[dict]:
    cur = conn.execute(
        """SELECT id, source, source_url, title, pain_point, vertical, raw_signals
           FROM opportunities WHERE status = 'raw' ORDER BY discovered_at ASC"""
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def update_score(conn, opp_id: int, score: int, reasoning: str, new_status: str):
    conn.execute(
        "UPDATE opportunities SET score=?, score_reasoning=?, status=? WHERE id=?",
        (score, reasoning, new_status, opp_id),
    )


def update_veto(conn, opp_id: int, veto_reasons: list[str]):
    conn.execute(
        "UPDATE opportunities SET veto_reasons=?, status='vetoed' WHERE id=?",
        (json.dumps(veto_reasons), opp_id),
    )


# 1. Lee reglas
rules = RULES.read_text()

# 2. Procesa cada raw:
#    - Aplica vetos (cheap, sin LLM si es obvio)
#    - Si pasa, llama a Claude Sonnet con: rules + opp data + señales web
#    - Parsea el JSON {score: int, sub_scores: {...}, reasoning: str, veto: bool, veto_reasons: []}
#    - Update BD
```

## Prompt para Claude (template)

```
Eres un analista de oportunidades de negocio bootstrap (low-budget, time-to-MVP corto).
Recibes una oportunidad detectada por un scout y debes validarla siguiendo estas reglas:

{rules_text}

Oportunidad:
- Título: {title}
- Pain point: {pain_point}
- Vertical: {vertical}
- Fuente: {source} ({source_url})
- Señales raw: {raw_signals}

Señales web adicionales (búsquedas que he hecho):
- Top 10 SERP: {serp_results}
- Tendencia 12 meses: {trends_data}
- Threads Reddit relacionados: {reddit_count}

Devuelve SOLO JSON, sin texto adicional:
{
  "veto": true|false,
  "veto_reasons": [...],
  "sub_scores": {
    "demand": 0-20,
    "competition": 0-20,
    "capital": 0-20,
    "time_to_mvp": 0-20,
    "monetization": 0-20
  },
  "score": 0-100,
  "reasoning": "markdown breve explicando cada sub_score"
}
```

## Output esperado

```
## Validator run @ 2026-04-28T15:00 UTC

Procesadas 23 opps raw:
- Validadas (score ≥ 60): 8
  · #142 "Tool to track newsletter unsubscribes per topic" — score 78
  · #143 "Astro plantilla landing waitlist" — score 71
  · ...
- Vetadas: 5
  · #145 "Side hustle dropship Aliexpress watches" — [aliexpress_dropship, requires_capital]
- Bajo umbral (score < 60, se queda raw): 10

Tokens consumidos: ~32k input / ~4k output (Sonnet 4.6).
Coste estimado: $0.18.
```

## Frecuencia

Cron: `30 */12 * * *` (cada 12h, offset 30min para no chocar con scout).
