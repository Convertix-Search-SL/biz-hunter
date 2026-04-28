---
name: reporter
description: Cron diario 8am que envía digest por Telegram con el estado del pipeline biz-hunter (opps activas, MVPs en tracción, abandonadas, métricas del día). También se invoca on-demand cuando otra skill detecta nueva tracción.
version: 0.1.0
author: david
metadata:
  hermes:
    tags: [biz-hunter, reporting, notifications]
    category: biz-hunter
---

# Reporter

Tu trabajo: generar el **digest diario 8am** y enviarlo por **Telegram**. También responder a invocaciones on-demand desde `mvp-tester` cuando detecta tracción nueva.

## Reglas de operación

1. Modos:
   - **`/reporter`** sin args → digest diario completo.
   - **`/reporter --traction <opp_id>`** → mensaje corto e inmediato (solo Telegram).
2. **Idempotencia**: una opp `traction` solo se notifica una vez (campo `notified_at` se llena tras el push). El digest diario sí incluye opps ya notificadas (resumen).
3. **Canal único: Telegram**. Usa `send_message(target='telegram', ...)`.

## Flujo

### Modo digest diario

1. Query a BD para cada categoría:
   - Tracción nueva últimas 24h (`status=traction`, `notified_at IS NULL`).
   - Tracción acumulada (`status=traction`, total).
   - MVPs activos midiéndose (`status=mvp_live`).
   - Validadas pendientes de MVP (`status=validated`).
   - Raw pendientes de validar (`status=raw` count).
   - Vetadas/abandonadas hoy (count, no detalle).
2. Genera markdown plano (Telegram soporta MarkdownV2 o texto).
3. Push Telegram con `send_message`.
4. Marca `notified_at = NOW()` en las traction nuevas.

### Modo `--traction <opp_id>`

1. Carga la opp del id.
2. Construye mensaje corto (5-7 líneas).
3. Push Telegram.
4. Marca `notified_at`.

## Plantillas

### Telegram digest (markdown plano)

```
🤖 Biz Hunter Digest — 2026-04-28

🔥 Nueva tracción (24h): 2
  · "Newsletter unsubscribe analytics" — 7 signups → ver
  · "AI prompt pack SEO local" — 4 signups → ver

📊 Pipeline:
  · Raw pendientes: 12
  · Validadas pendientes MVP: 5
  · MVPs midiendo: 8
  · Tracción total: 4
  · Abandonadas hoy: 1

💰 Coste tokens últimas 24h: ~$1.20
```

### Telegram traction inmediato

```
🔥 Nueva oportunidad con tracción

Título: Newsletter unsubscribe analytics
Vertical: microsaas
Score: 78/100
Signups 72h: 7
MVP: https://abc123.biz-hunter.pages.dev

Razonamiento:
{score_reasoning truncado a 300 chars}
```

## Implementación

```python
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/opt/biz-hunter/data/opportunities.db")
REPORTS_DIR = Path("/opt/biz-hunter/data/reports")


def query_summary(conn) -> dict:
    out = {}
    out["new_traction"] = conn.execute(
        """SELECT id, title, vertical, score, waitlist_signups, mvp_url, score_reasoning
           FROM opportunities
           WHERE status = 'traction' AND notified_at IS NULL
           ORDER BY waitlist_signups DESC"""
    ).fetchall()
    out["raw_count"] = conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE status='raw'"
    ).fetchone()[0]
    out["validated_count"] = conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE status='validated'"
    ).fetchone()[0]
    out["mvp_live_count"] = conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE status='mvp_live'"
    ).fetchone()[0]
    out["traction_total"] = conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE status='traction'"
    ).fetchone()[0]
    return out


def render_telegram_digest(summary: dict) -> str:
    # ... (formatea markdown plano para Telegram)
    pass


def mark_notified(conn, ids: list[int]):
    if not ids:
        return
    conn.execute(
        f"UPDATE opportunities SET notified_at = CURRENT_TIMESTAMP WHERE id IN ({','.join('?'*len(ids))})",
        ids,
    )
```

## Output esperado

Devuelve un resumen breve del cron (el digest detallado va a Telegram):

```
## Reporter run @ 2026-04-28T08:00 UTC

Digest Telegram: ✅
Nuevas tracciones notificadas: 2
```

## Frecuencia

Cron: `0 8 * * *` (8am diario). On-demand desde `mvp-tester` cuando detecta tracción.
