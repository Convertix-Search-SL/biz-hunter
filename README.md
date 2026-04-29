# Biz Hunter

Equipo de agentes 24/7 sobre [Hermes Agent](https://github.com/NousResearch/hermes-agent) tirando de la API de Claude. Investiga oportunidades de negocio low-budget en fuentes públicas, las valida con datos reales, genera MVPs (landing/tool), mide tracción y avisa por Telegram cuando una pinta prometedora.

## Pipeline

```
[opportunity-scout]      cada 6h   →  status=raw
        ↓
[opportunity-validator]  cada 12h  →  status=validated (score≥60) | vetoed
        ↓
[mvp-builder]            cada 24h  →  status=mvp_live
        ↓                              · score 60-79 → landing+waitlist
        ↓                              · score ≥80   → landing+tool funcional
[mvp-tester]             cada 24h  →  status=traction (signups ≥ umbral) | abandoned
        ↓
[reporter]               diario 8am + trigger inmediato si traction
                                   →  Telegram digest
```

Reglas, scoring y umbrales en [`strategy/hunting-rules.md`](./strategy/hunting-rules.md). Editable en caliente — las skills lo leen en cada ejecución.

## Stack

- **Scripts Python** (`scripts/`) — pipeline determinista, cada paso autónomo.
- **Claude API** (Anthropic SDK directo) — usado por validator/builder/scout para razonamiento (clasificación, scoring, copy).
- **Container `biz-hunter-cron`** — cron de Linux clásico que dispara los scripts según `infra/crontab`.
- **Container `hermes-biz`** — gateway Telegram (uso futuro: comandos `/biz status` bidireccionales).
- **SQLite** (`data/opportunities.db`) — fuente de verdad del pipeline.
- **Cloudflare Pages** (free) — hosting de landings de MVPs.
- **n8n + Postgres VPS** — waitlist signups via webhook (sin servicios externos, reúsa infra Convertix). Setup en `n8n/SETUP.md`.
- **Docker Compose** — todo orquestado, portable Mac → VPS sin cambios.

## Setup local (Mac)

### 1. Configurar `.env`

```bash
cd ~/Documents/Claude\ Code/biz-hunter
cp .env.example .env   # rellena ANTHROPIC_API_KEY, TELEGRAM_*, CF_*, N8N_WEBHOOK_*
python3 scripts/init_db.py
```

### 2. Arrancar stack

```bash
docker compose up -d
docker compose logs -f cron     # cron container
docker compose logs -f hermes   # gateway Telegram (opcional)
```

### 3. Smoke test (run manual de cada script)

```bash
# Desde el host (con venv local):
.venv/bin/python scripts/scout.py        # fetch fuentes + clasifica + insert raw
.venv/bin/python scripts/validator.py    # scorea raw → validated/vetoed
.venv/bin/python scripts/builder.py      # top-3 → genera landing → CF Pages
.venv/bin/python scripts/tester.py       # mide signups via webhook n8n
.venv/bin/python scripts/reporter.py     # digest Telegram

# O desde el container cron:
docker exec biz-hunter-cron python /opt/biz-hunter/scripts/scout.py
```

### 4. Cron ya activo

`infra/crontab` ya está montado en el container `biz-hunter-cron`:

| Script | Schedule |
|---|---|
| scout.py | `0 */6 * * *` (cada 6h) |
| validator.py | `30 1,13 * * *` (12h, offset 30min) |
| builder.py | `0 3 * * *` (3am) |
| tester.py | `0 7 * * *` (7am) |
| reporter.py | `0 8 * * *` (8am) |

## Tests offline

```bash
python3 -m pytest tests/ -v
```

(No requieren Claude API ni red — verifican esquema BD, consistencia entre skills/cron y validez de las reglas.)

## Costes estimados

Asumiendo volumen target (10-20 opps nuevas/6h, 3 MVPs/día):

| Componente | Coste/mes |
|---|---|
| Claude API (Sonnet 4.6 mayoría, Haiku para scout) | ~$30-60 |
| Cloudflare Pages | $0 (free tier holgado) |
| n8n + Postgres (VPS) | $0 (ya pagado en Convertix) |
| VPS futuro (5€ Hetzner) | 5€ |
| **Total** | **~$35-65/mes** |

Cap de gasto Claude: configurable en https://console.anthropic.com (Settings → Usage → Limits).

## Privacidad

- Landings sin marca propia, en subdominios opacos `*.biz-hunter.pages.dev`.
- `<meta name="robots" content="noindex,nofollow">` hasta validar tracción.
- Las opps no se publican en ningún sitio — solo viven en tu BD local + tu Telegram.

## Migración a VPS

Cuando quieras pasarlo al VPS de Convertix:

```bash
# En el VPS:
cd /opt
git clone <este-repo> biz-hunter
cd biz-hunter
cp /path/to/.env .  # copia el .env del Mac
docker compose up -d
```

Sin cambios de código. La red docker es independiente, no choca con `seo-intelligence-tool`.

## Estructura

```
biz-hunter/
├── docker-compose.yml      Hermes + LiteLLM
├── litellm-config.yaml     failover providers
├── strategy/
│   └── hunting-rules.md    criterios scoring + vetos + umbrales
├── skills/                 5 skills custom (Markdown + Python embebido)
│   ├── opportunity-scout/
│   ├── opportunity-validator/
│   ├── mvp-builder/
│   ├── mvp-tester/
│   └── reporter/
├── cron/
│   └── jobs.json           schedule de las 5 skills
├── data/
│   ├── opportunities.db    SQLite — fuente de verdad
│   ├── mvps/               1 carpeta por MVP (HTML + meta)
│   └── reports/            digests HTML diarios
├── scripts/
│   ├── init_db.py
│   └── deploy_landing.py   Cloudflare Pages wrapper
└── tests/
    └── test_scoring.py     tests offline
```
