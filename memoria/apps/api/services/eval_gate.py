from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.services.pipeline import Pipeline, heuristic_gatekeeper, heuristic_policy


def load_gold_set() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / "gold_set.json"
    return json.loads(path.read_text())


async def run_gate_eval(pipeline: Pipeline) -> dict[str, Any]:
    rows = load_gold_set()
    matrix: dict[str, dict[str, int]] = {}
    tp_never = fn_never = 0

    for row in rows:
        text = row["text"]
        acl = {"mode": "normal", "active_scope": ["self"], "off_record": False, "tier_override": None}
        if "off the record" in text.lower():
            acl["off_record"] = True
        if "private" in text.lower() and "that's private" in text.lower():
            acl["tier_override"] = "personal"

        gk = await pipeline.run_gatekeeper("eval", "eval", text, "USER", True, acl)
        if not gk.get("tier"):
            gk = heuristic_gatekeeper(text)
        pol = await pipeline.run_policy(gk, acl, text)
        if not pol.get("action"):
            pol = heuristic_policy(gk, acl, text)

        pred_tier = pol.get("tier") or gk.get("tier") or "knowledge"
        expect_tier = row["expect_tier"]
        matrix.setdefault(expect_tier, {})
        matrix[expect_tier][pred_tier] = matrix[expect_tier].get(pred_tier, 0) + 1

        stored = pol.get("action") in ("write", "rewrite", "quarantine") and bool(
            pol.get("store_text")
        )
        if expect_tier == "never":
            if pred_tier == "never" and not stored:
                tp_never += 1
            else:
                fn_never += 1

    never_recall = tp_never / (tp_never + fn_never) if (tp_never + fn_never) else 1.0
    return {
        "matrix": matrix,
        "never_recall": never_recall,
        "tp_never": tp_never,
        "fn_never": fn_never,
        "total": len(rows),
    }
