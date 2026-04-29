#!/usr/bin/env python3
"""Opportunity Validator — scorea raw → validated/vetoed.

Flujo:
1. Carga strategy/hunting-rules.md.
2. Aplica vetos hard locales (regex/keyword) sobre title/pain_point — barato.
3. Para las que sobreviven, llama a Claude Sonnet en batches de 8 con scoring
   estructurado (5 sub-scores 0-20).
4. Update BD: score≥60 → status=validated, vetada → status=vetoed.

Cron: cada 12h (offset 30min vs scout).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.db import conn
from lib.llm import ask_json
from lib.notify import send_telegram


RULES = Path(__file__).parent.parent / "strategy" / "hunting-rules.md"
BATCH_SIZE = 8

# Patrones de veto hard (case-insensitive).
HARD_VETO_PATTERNS = {
    "mlm": [r"\bMLM\b", r"multi[- ]level marketing", r"network marketing"],
    "aliexpress_dropship": [r"alibaba", r"aliexpress", r"\btemu\b", r"dropship.*china"],
    "crypto_pump": [r"meme coin", r"shitcoin", r"pump.{0,10}dump", r"\$[A-Z]{3,5} to the moon"],
    "nsfw": [r"\bporn", r"\badult\s+content\b", r"\bnsfw\b", r"onlyfans"],
    "gambling": [r"\bcasino\b", r"betting\s+(?:tips|strategy)", r"sports?\s*book"],
    "physical_inventory": [r"warehouse", r"shipping\s+inventory", r"manufactur(?:e|ing)\s+products"],
}


def load_rules() -> str:
    return RULES.read_text()


def quick_veto(title: str, pain: str) -> list[str]:
    """Veto hard local. Devuelve lista de razones que disparan veto."""
    text = f"{title} {pain}".lower()
    hits = []
    for label, patterns in HARD_VETO_PATTERNS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            hits.append(label)
    return hits


def fetch_raw(c) -> list[dict]:
    cur = c.execute(
        """SELECT id, source, source_url, title, pain_point, vertical, raw_signals
           FROM opportunities
           WHERE status = 'raw'
           ORDER BY discovered_at ASC"""
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def update_score(c, opp_id: int, score: int, reasoning: str, status: str):
    c.execute(
        "UPDATE opportunities SET score=?, score_reasoning=?, status=? WHERE id=?",
        (score, reasoning, status, opp_id),
    )


def update_veto(c, opp_id: int, reasons: list[str]):
    c.execute(
        "UPDATE opportunities SET veto_reasons=?, status='vetoed' WHERE id=?",
        (json.dumps(reasons), opp_id),
    )


SYSTEM = """Eres un analista de oportunidades de negocio low-budget.
Recibes un batch de oportunidades pre-clasificadas. Para CADA UNA, devuelves
un score 0-100 (suma de 5 sub-scores 0-20) siguiendo las reglas que te paso.

Las reglas describen:
- Demanda (0-20): basado en señales de tracción (upvotes, comentarios, search volume implícito).
- Competencia (0-20): tu juicio sobre saturación del nicho.
- Capital required (0-20): si requiere inversión inicial significativa, baja.
- Time-to-MVP (0-20): si se puede montar en horas/días, alta.
- Monetization (0-20): claridad del path a 50€+/mes.

También aplicas vetos hard si detectas:
- MLM, dropship Aliexpress/Temu, crypto pumps, NSFW, médico/legal sin licencia,
  apuestas, productos físicos con stock, wrappers triviales de ChatGPT.

Devuelve SOLO JSON válido sin texto adicional, formato exacto:
{
  "results": [
    {
      "opp_id": <id>,
      "veto": false,
      "veto_reasons": [],
      "sub_scores": {"demand": 0-20, "competition": 0-20, "capital": 0-20, "time_to_mvp": 0-20, "monetization": 0-20},
      "score": 0-100,
      "reasoning": "1-3 frases concisas explicando los sub_scores"
    }
  ]
}
"""


def build_user_prompt(rules: str, batch: list[dict]) -> str:
    parts = [
        "## Reglas de scoring",
        rules,
        "",
        "## Batch a scorear",
        "",
    ]
    for opp in batch:
        signals = json.loads(opp.get("raw_signals") or "{}")
        parts.append(f"### opp_id={opp['id']}")
        parts.append(f"Title: {opp['title']}")
        parts.append(f"Vertical: {opp.get('vertical')}")
        parts.append(f"Pain point: {opp['pain_point']}")
        parts.append(f"Source: {opp['source']}")
        parts.append(f"Signals: ups={signals.get('ups', 0)}, comments={signals.get('num_comments', 0)}")
        excerpt = signals.get("body_excerpt") or ""
        if excerpt:
            parts.append(f"Body excerpt: {excerpt[:400]}")
        parts.append("")
    return "\n".join(parts)


def main() -> int:
    rules = load_rules()
    with conn() as c:
        raws = fetch_raw(c)

    if not raws:
        print("[validator] no raw opps to validate")
        send_telegram("📋 *Validator*: 0 opps raw pendientes.")
        return 0

    print(f"[validator] {len(raws)} raw opps a procesar")

    # Veto local primero
    for_llm = []
    quick_vetoed = 0
    with conn() as c:
        for opp in raws:
            reasons = quick_veto(opp["title"], opp["pain_point"])
            if reasons:
                update_veto(c, opp["id"], reasons)
                quick_vetoed += 1
            else:
                for_llm.append(opp)

    print(f"[validator] vetadas localmente: {quick_vetoed}, a LLM: {len(for_llm)}")

    # Llamadas Claude en batches
    validated = 0
    vetoed_llm = 0
    below_threshold = 0
    errors = 0

    for i in range(0, len(for_llm), BATCH_SIZE):
        batch = for_llm[i : i + BATCH_SIZE]
        user_prompt = build_user_prompt(rules, batch)
        try:
            result = ask_json(SYSTEM, user_prompt, max_tokens=4096)
        except Exception as e:
            print(f"[validator] batch {i // BATCH_SIZE} falló: {e}")
            errors += 1
            continue

        with conn() as c:
            for r in result.get("results", []):
                opp_id = int(r.get("opp_id", 0))
                if not opp_id:
                    continue
                if r.get("veto"):
                    update_veto(c, opp_id, r.get("veto_reasons") or ["llm_veto"])
                    vetoed_llm += 1
                    continue
                score = int(r.get("score", 0))
                reasoning = (r.get("reasoning") or "")[:2000]
                if score >= 60:
                    update_score(c, opp_id, score, reasoning, "validated")
                    validated += 1
                else:
                    update_score(c, opp_id, score, reasoning, "raw")  # se queda raw
                    below_threshold += 1

    msg = (
        f"📋 *Validator run*\n"
        f"Procesadas: {len(raws)}\n"
        f"Validadas (≥60): {validated}\n"
        f"Vetadas local: {quick_vetoed}\n"
        f"Vetadas LLM: {vetoed_llm}\n"
        f"Bajo umbral (siguen raw): {below_threshold}\n"
        f"Errores LLM: {errors}"
    )
    print(msg.replace("*", ""))
    send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
