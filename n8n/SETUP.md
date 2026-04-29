# Setup de n8n para biz-hunter

> **Estado actual**: ✅ ya montado en `n8n.convertix.net` via CLI (29-abr-2026).
> Credencial `biz-hunter Postgres` + workflows `biz-hunter: Signup` y `biz-hunter: Count signups` importados y activos.
>
> Esta guía es de referencia/operación: usar si hay que recrear todo o
> migrar a otra instancia n8n.

3 pasos: crear credencial Postgres → importar 2 workflows → activarlos.

## 1. Credencial Postgres en n8n

1. Ve a https://n8n.convertix.net
2. Sidebar izquierda → **Credentials** → **Add credential**
3. Busca **"Postgres"** y selecciona.
4. Rellena:
   - **Credential Name**: `biz-hunter Postgres` (importante, los workflows referencian este nombre)
   - **Host**: `tfm-database-postgres-1` (mismo docker network, n8n y postgres comparten red)
   - **Database**: `biz_hunter`
   - **User**: `tfm_user`
   - **Password**: `tfm_password_segura`
   - **Port**: `5432`
   - **SSL**: `disable`
5. Click **"Save"** → debe decir "Connection tested successfully" en verde.

## 2. Importar workflows

1. Sidebar → **Workflows** → botón **"+"** o **"Add workflow"** arriba a la derecha → menú `⋮` → **"Import from file"**.
2. Selecciona `workflow-signup.json` (en este repo, en `n8n/workflow-signup.json`).
3. Repite para `workflow-count.json`.

Tras importar:
- Cada workflow debe tener un **id de credencial** asignado al Postgres node. Si no, edita el Postgres node de cada uno → "Credential to connect with" → selecciona **"biz-hunter Postgres"**.

## 3. Activar workflows

En cada workflow:
1. Pulsa el toggle **"Active"** arriba a la derecha (gris → verde).
2. Verifica el webhook URL en el primer nodo:
   - Signup: `https://n8n.convertix.net/webhook/biz-hunter/signup`
   - Count: `https://n8n.convertix.net/webhook/biz-hunter/count`

## 4. Test

```bash
# Test signup
curl -X POST https://n8n.convertix.net/webhook/biz-hunter/signup \
  -H "Content-Type: application/json" \
  -d '{"mvp_slug":"test","email":"foo@bar.com"}'
# Esperado: {"success":true,"id":1,"created_at":"..."}

# Test count
curl "https://n8n.convertix.net/webhook/biz-hunter/count?slug=test&hours=24"
# Esperado: {"mvp_slug":"test","hours":24,"signups":1,"last_signup":"..."}
```

## CORS

El webhook node tiene `allowedOrigins: "*"` configurado, n8n maneja OPTIONS preflight automáticamente. Las landings de Cloudflare Pages podrán hacer POST sin bloqueo.

Si alguna vez recibes errores CORS, añadimos un block path-specific al Caddyfile (no necesario por defecto).

## Estructura de la tabla

```sql
CREATE TABLE waitlist_signups (
  id BIGSERIAL PRIMARY KEY,
  mvp_slug TEXT NOT NULL,
  email TEXT NOT NULL,
  meta JSONB,                  -- info adicional opcional
  ip_country TEXT,             -- futuro: detección IP
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_waitlist_slug_created ON waitlist_signups (mvp_slug, created_at DESC);
CREATE INDEX idx_waitlist_email ON waitlist_signups (email);
```

DB: `biz_hunter`. Conexión interna VPS: `tfm-database-postgres-1:5432`.
