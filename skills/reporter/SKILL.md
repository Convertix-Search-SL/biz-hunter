---
name: reporter
description: Cron diario 8am que envía digest a email + telegram con el estado del pipeline biz-hunter (opps activas, MVPs en tracción, abandonadas, métricas del día). También se invoca on-demand cuando otra skill detecta nueva tracción.
version: 0.1.0
author: david
metadata:
  hermes:
    tags: [biz-hunter, reporting, notifications]
    category: biz-hunter
---

# Reporter

Tu trabajo: generar el **digest diario 8am** y enviarlo por **Telegram + email**. También responder a invocaciones on-demand desde `mvp-tester` cuando detecta tracción nueva.

## Reglas de operación

1. Modos:
   - **`/reporter`** sin args → digest diario completo.
   - **`/reporter --traction <opp_id>`** → mensaje corto e inmediato (solo Telegram).
2. **Idempotencia**: una opp `traction` solo se notifica una vez (campo `notified_at` se llena tras el push). El digest diario sí incluye opps ya notificadas (resumen).
3. **Telegram**: usa `send_message(target='telegram', ...)`.
4. **Email**: ejecuta `python /opt/biz-hunter/scripts/send_digest.py` que toma el HTML generado y lo manda via SMTP.
5. **Output del cron**: como `deliver=telegram,email`, el output del cron se entrega también automáticamente por esos canales — pero queremos formato bonito, así que generamos el digest dentro de la skill y solo emitimos el resumen plano del cron.

## Flujo

### Modo digest diario

1. Query a BD para cada categoría:
   - Tracción nueva últimas 24h (`status=traction`, `notified_at IS NULL`).
   - Tracción acumulada (`status=traction`, total).
   - MVPs activos midiéndose (`status=mvp_live`).
   - Validadas pendientes de MVP (`status=validated`).
   - Raw pendientes de validar (`status=raw` count).
   - Vetadas/abandonadas hoy (count, no detalle).
2. Genera markdown (texto plano) → para Telegram.
3. Genera HTML (tabla + estilos inline) → para email.
4. Push Telegram con `send_message`.
5. `subprocess.run(["python", "/opt/biz-hunter/scripts/send_digest.py", "--html-file", html_path])`.
6. Marca `notified_at = NOW()` en las traction nuevas.

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

### Email HTML

Tabla bootstrap-style con todas las opps activas + bloque destacado en amarillo arriba con las nuevas tracciones del día. Plantilla embebida en `scripts/send_digest.py`.

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
    # ... (formatea)
    pass


def render_html_digest(summary: dict) -> str:
    # ... (HTML con tabla)
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

Devuelve un resumen breve del cron (ya que el digest detallado va a Telegram/email):

```
## Reporter run @ 2026-04-28T08:00 UTC

Digest enviado:
  · Telegram: ✅
  · Email: ✅ (a david.ruiz@convertix.net)

Nuevas tracciones notificadas: 2
HTML guardado en data/reports/2026-04-28.html
```

## Frecuencia

Cron: `0 8 * * *` (8am diario). On-demand desde `mvp-tester` cuando detecta tracción.
