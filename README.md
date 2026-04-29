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

- **Hermes Agent** (NousResearch) — orquestador, skills, cron, gateway Telegram, subagentes paralelos.
- **Claude API** (Anthropic) directo + **LiteLLM** como failover a OpenRouter free.
- **SQLite** (`data/opportunities.db`) — fuente de verdad del pipeline.
- **Cloudflare Pages** (free) — hosting de landings de MVPs.
- **Supabase Free** — waitlist signups (tabla `waitlist_signups` con anon insert + RLS).
- **Docker Compose** — todo orquestado, portable Mac → VPS sin cambios.

## Setup local (Mac)

### 1. Build de la imagen Hermes

Asumiendo que tienes el repo de Hermes Agent vecino:

```bash
cd ~/Documents/Claude\ Code/hermes-agent
docker build -t hermes-agent:local .
```

### 2. Configurar este proyecto

```bash
cd ~/Documents/Claude\ Code/biz-hunter
cp .env.example .env   # rellena ANTHROPIC_API_KEY, TELEGRAM_*, CF_*, SUPABASE_*
python3 scripts/init_db.py
```

### 3. Arrancar stack

```bash
docker compose up -d
docker compose logs -f hermes
```

### 4. Smoke test (manual antes de activar cron)

```bash
docker exec -it hermes-biz hermes session new
# Dentro de la session:
/opportunity-scout
/opportunity-validator
/mvp-builder
/mvp-tester
/reporter
```

### 5. Activar cron

```bash
docker exec -it hermes-biz sh -c "for j in /opt/biz-hunter/cron/jobs.json; do hermes cron load \$j; done"
docker exec -it hermes-biz hermes cron list
```

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
| Supabase | $0 (free tier 50k MAU, 500MB DB) |
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
