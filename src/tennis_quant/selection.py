from __future__ import annotations

from tennis_quant.domain import Candidate


def rejection_reasons(candidate: Candidate, cfg: dict) -> list[str]:
    reasons: list[str] = []
    s = cfg["selection"]
    odd = candidate.selected_market.best_odd
    if odd is None or not (s["min_odd"] <= odd <= s["max_odd"]):
        reasons.append("ODD_OUT_OF_RANGE")
    if candidate.final_probability < s["min_final_probability"]:
        reasons.append("PROBABILITY_TOO_LOW")
    if candidate.edge_pp < s["min_edge_pp"]:
        reasons.append("EDGE_TOO_LOW")
    if candidate.confidence < s["min_confidence"]:
        reasons.append("CONFIDENCE_TOO_LOW")
    if candidate.disagreement_pp > s["max_disagreement_pp"]:
        reasons.append("MODEL_DISAGREEMENT")
    return reasons


def rank_candidates(candidates: list[Candidate], cfg: dict) -> list[Candidate]:
    for candidate in candidates:
        candidate.reject_reasons = rejection_reasons(candidate, cfg)
    eligible = [c for c in candidates if not c.reject_reasons]
    eligible.sort(key=lambda c: (c.confidence, c.edge_pp, c.final_probability), reverse=True)

    max_approved = int(cfg["selection"]["max_approved"])
    shadow_size = int(cfg["selection"].get("shadow_size", 10))
    for idx, candidate in enumerate(eligible, 1):
        candidate.rank = idx
        if idx <= max_approved:
            candidate.status = "APPROVED"
        elif idx <= max_approved + shadow_size:
            candidate.status = "SHADOW"
        else:
            candidate.status = "REJECTED"
            candidate.reject_reasons = ["BELOW_TOP_CUTOFF"]
    return sorted(candidates, key=lambda c: (c.rank is None, c.rank or 999999, -c.confidence))
