---
name: mvp-tester
description: Cada 24h consulta los signups via webhook n8n (Postgres VPS, tabla waitlist_signups filtrada por mvp_slug) de los MVPs en mvp_live, actualiza waitlist_signups en BD local, y promueve a status=traction si supera el umbral del archivo de reglas.
version: 0.1.0
author: david
metadata:
  hermes:
    tags: [biz-hunter, validation, traction]
    category: biz-hunter
---

# MVP Tester

Tu trabajo: medir tracción real de los MVPs `mvp_live` y decidir si pasan a `traction` (notifican al user) o a `abandoned` (tras 14 días sin éxito).

## Reglas de operación

1. Lee `/opt/biz-hunter/strategy/hunting-rules.md` para los umbrales de tracción (puede haber cambios).
2. Procesa todas las opps con `status='mvp_live'`.
3. **No re-procees** opps con `last_signup_check < 18h` (evita queries innecesarias).
4. **Tiempo de gracia**: 14 días desde `mvp_live`. Pasados sin tracción → `abandoned`.
5. **Trigger inmediato a reporter**: si una opp pasa a `traction` por primera vez, llama directamente al tool `send_message` para notificar a Telegram (no esperes al cron diario).

## Flujo por opp

Para cada opp `mvp_live`:

1. Lee el `mvp_slug` de la opp (sacable del path `data/mvps/<slug>` o del campo `mvp_path` en BD).
2. Consulta el webhook n8n (público, sin auth — el endpoint solo expone count, no PII):
   ```
   GET {N8N_WEBHOOK_COUNT_URL}?slug={slug}&hours=72
   ```
   Respuesta:
   ```json
   {"mvp_slug":"...","hours":72,"signups":7,"last_signup":"2026-04-29T..."}
   ```
3. Extrae `signups` de la respuesta.
4. Update BD:
   ```sql
   UPDATE opportunities SET
     waitlist_signups = ?,
     last_signup_check = CURRENT_TIMESTAMP
   WHERE id = ?;
   ```
5. Aplica umbrales según `mvp_type`:
   - `landing`: signups ≥ 5 en 72h → `traction`
   - `tool`: signups ≥ 3 + ≥1 uso del tool → `traction` (uso del tool requiere instrumentación custom — por ahora basta con signups)
6. Si pasa a `traction`:
   - Update `status='traction'`, `notified_at=NULL` (para que reporter sepa que es nueva).
   - Llama `send_message(target='telegram', message=...)` con el resumen.
7. Si lleva ≥ 14 días en `mvp_live` sin tracción → `status='abandoned'`.

## Implementación

```python
import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = Path("/opt/biz-hunter/data/opportunities.db")
MVPS_DIR = Path("/opt/biz-hunter/data/mvps")
RULES = Path("/opt/biz-hunter/strategy/hunting-rules.md")

N8N_COUNT_URL = os.environ["N8N_WEBHOOK_COUNT_URL"]


def fetch_mvp_live(conn) -> list[dict]:
    cur = conn.execute(
        """SELECT id, title, vertical, score, mvp_path, mvp_url, mvp_type,
                  waitlist_signups, last_signup_check, discovered_at
           FROM opportunities
           WHERE status = 'mvp_live'
           AND (last_signup_check IS NULL OR last_signup_check < datetime('now', '-18 hours'))"""
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_signup_count(mvp_slug: str, window_hours: int = 72) -> int:
    import urllib.request
    import urllib.parse
    qs = urllib.parse.urlencode({"slug": mvp_slug, "hours": window_hours})
    req = urllib.request.Request(f"{N8N_COUNT_URL}?{qs}")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return int(data.get("signups", 0))


def reached_traction(opp: dict, signups: int) -> bool:
    if opp["mvp_type"] == "landing":
        return signups >= 5
    if opp["mvp_type"] == "tool":
        return signups >= 3  # nota: ≥1 uso requeriría instrumentación, por ahora solo signups
    return False


def days_since_mvp_live(opp: dict) -> int:
    # Para la regla de abandonment a los 14 días.
    # discovered_at no es exacto; idealmente sumar un campo mvp_live_at, por ahora aproximamos.
    pass


# Loop principal: para cada opp_live, fetch signups, decide transición
```

## Notificación Telegram inmediata (cuando pasa a traction)

Usa el tool `send_message`:

```python
send_message(
    target="telegram",
    message=f"""🔥 Nueva oportunidad con tracción

Título: {opp['title']}
Vertical: {opp['vertical']}
Score: {opp['score']}/100
Signups 72h: {signups}
MVP: {opp['mvp_url']}
""",
)
```

## Output esperado

```
## Tester run @ 2026-04-28T07:00 UTC

12 MVPs en mvp_live procesados:

🔥 Nueva tracción: 1
   · #142 "Newsletter unsubscribe analytics" — 7 signups en 72h ≥ 5 ✅
     → status=traction, Telegram notificado

📈 Sin cambio: 8 (signups bajos pero dentro de los 14 días de gracia)

😴 Abandonadas: 3 (>14 días sin tracción)
   · #87, #94, #101

n8n webhook calls: 12 (Postgres VPS, sin límite real).
```

## Frecuencia

Cron: `0 7 * * *` (7am cada día — antes que el reporter de las 8am, así su digest ya tiene los traction de hoy).
