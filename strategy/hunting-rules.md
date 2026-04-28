# Reglas del Biz Hunter

Este archivo define los **criterios duros de scoring**, **vetos** y **umbrales** que rigen las skills `opportunity-validator`, `mvp-builder` y `mvp-tester`. Editable por el user — los cambios aplican en la siguiente ejecución del cron.

---

## Filosofía

- **Cero o muy baja inversión**: lo que no se monta con < 30€/mes hard cost no entra.
- **Time-to-MVP corto**: si no se puede tener algo público en menos de 24h, NO entra.
- **Path a monetización claro**: aunque sea "ads de AdSense" o "waitlist → preorder Gumroad", tiene que estar dibujado.
- **Diferenciación posible**: si el SERP está saturado de competidores fuertes con backlinks viejos, descarta (a menos que haya un ángulo único).
- **Anti-marketing trampa**: no perseguimos hype efímero (ej. "ChatGPT wrappers"); buscamos pain points reales con demanda persistente.

---

## Scoring (0-100)

5 sub-scores de 0 a 20:

### 1. Demanda (0-20)
- 20: search volume > 10k/mes O hilo Reddit con 500+ upvotes en últimos 30 días.
- 15: 1k-10k búsquedas/mes O hilo con 100+ upvotes.
- 10: 100-1k búsquedas O comentarios recurrentes en foros.
- 5: pocos signals pero coherentes.
- 0: invención del LLM sin datos.

### 2. Competencia (0-20)
- 20: 0-3 soluciones existentes, ninguna pulida.
- 15: 4-10 soluciones, calidad media.
- 10: SERP top 10 con soluciones decentes pero hueco visible.
- 5: muy saturado, hay que tener ángulo único.
- 0: imposible diferenciar.

### 3. Capital required (0-20)
- 20: cero coste fijo (todo en free tier).
- 15: < 10€/mes hard cost.
- 10: 10-30€/mes.
- 5: 30-100€/mes (rojo, casi descarta).
- 0: requiere inversión inicial > 100€ o stock físico.

### 4. Time-to-MVP (0-20)
- 20: landing + waitlist en < 4h, tool funcional en < 8h.
- 15: < 24h para versión funcional.
- 10: 1-3 días.
- 5: 1 semana.
- 0: > 1 semana.

### 5. Monetization (0-20)
- 20: SaaS recurrente claro 9-29€/mes O producto digital 19€+.
- 15: AdSense + content site con tráfico orgánico viable.
- 10: affiliate (Amazon, productos digitales).
- 5: donations / patreon / unclear.
- 0: sin path a monetización.

**Score total** = suma de los 5. Umbral mínimo `validated`: **60/100**.
Score que activa MVP funcional (no solo landing): **80/100**.

---

## Vetos hard (van a `status=vetoed`, no se reintentan)

- **MLM** o estructuras piramidales.
- **Dropship Aliexpress / Temu**: márgenes mierda + UX cliente terrible.
- **Crypto pump-and-dump / shitcoins** (DeFi serio sí entra).
- **Contenido para adultos** o NSFW.
- **Médico / legal sin licencia** (consejo profesional regulado).
- **Apuestas / casinos online**.
- **Wrappers triviales de ChatGPT** sin valor añadido (UI bonita pero sin moat ni nicho).
- **Réplicas exactas de competidores** sin ángulo diferencial.
- **Productos físicos con stock** (logística, devoluciones, capital).

---

## Verticals soportados

| Vertical | Características | MVP típico |
|---|---|---|
| `microsaas` | Herramienta web SaaS para nicho B2B/B2C. | Landing → tool funcional simple → Stripe checkout. |
| `content_seo` | Web de contenido, monetización ads/affiliate. | Landing → 5-10 artículos seed → AdSense. |
| `digital_product` | Ebook, plantilla, curso corto, prompt pack. | Landing → preorder Gumroad. |
| `newsletter` | Newsletter especializada en nicho. | Landing → Beehiiv/Substack waitlist. |

---

## Umbrales del tester

- **Landing simple** (score 60-79): ≥ 5 signups en primeras 72h → `traction`.
- **Tool funcional** (score 80+): ≥ 3 signups + ≥ 1 uso del tool en primeras 72h → `traction`.
- **Tiempo de gracia**: 14 días de espera tras `mvp_live`. Si no llega a `traction` → `abandoned`.

---

## Configuración volumen

- Scout: target 10-20 oportunidades nuevas por ejecución (cada 6h).
- Validator: procesa todo el backlog `raw` cada 12h.
- Builder: top-3 por score por día.
- Reporter: digest diario 8am + push inmediato si nueva tracción.

---

## Cómo modificar

Edita este archivo y haz `docker compose restart hermes` para que las skills lo recarguen. Las skills leen este markdown en cada ejecución (no se cachea).
