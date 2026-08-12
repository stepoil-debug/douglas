from __future__ import annotations

from typing import Any


def classify_postmortem(snapshot: dict[str, Any], actual: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rule-based post-mortem hypotheses without rewriting the frozen prediction.

    The classifier deliberately separates weak/uncertain directional misses from
    genuine market-opposition errors. This avoids learning the wrong lesson from
    rejected, near-coinflip predictions.
    """
    tags: list[str] = []
    evidence: list[str] = []
    disagreement = float(snapshot.get("disagreement_pp", 0) or 0)
    data_quality = float(snapshot.get("data_quality", 0) or 0)
    edge = float(snapshot.get("edge_pp", 0) or 0)
    confidence = float(snapshot.get("confidence", 0) or 0)
    final_probability = float(snapshot.get("final_probability", 0.5) or 0.5)
    signals = snapshot.get("signals") or {}
    market_probability = signals.get("market", snapshot.get("market_probability"))
    surface = snapshot.get("surface") or (snapshot.get("match") or {}).get("surface")

    if confidence < 60 or abs(final_probability - 0.5) < 0.10:
        tags.append("ERR-UNC")
        evidence.append("Prediction was low-confidence or too close to a 50/50 match")

    if disagreement >= 10:
        tags.append("ERR-UNC")
        evidence.append("High model disagreement before the match")

    if not surface or "surface_elo" not in signals:
        tags.append("ERR-SUR")
        evidence.append("Surface context or surface Elo was unavailable in the frozen prediction")

    if data_quality < 0.7:
        tags.append("ERR-DAT")
        evidence.append("Prediction used incomplete contextual data")

    try:
        market = float(market_probability)
    except (TypeError, ValueError):
        market = None
    if market is not None:
        model_side = final_probability - 0.5
        market_side = market - 0.5
        if model_side * market_side < 0 and abs(final_probability - market) >= 0.04:
            tags.append("ERR-MKT")
            evidence.append("Model materially opposed the market direction and lost")

    if actual:
        if actual.get("retired"):
            tags.append("ERR-INJ")
            evidence.append("Match ended with retirement/physical event")
        if actual.get("adverse_market_move_pp", 0) >= 5:
            tags.append("ERR-MKT")
            evidence.append("Meaningful adverse closing-line movement")

    if not tags:
        # A market-aligned favourite can still lose. Do not invent a structural
        # explanation when the pre-match data does not support one.
        tags.append("ERR-RND")
        if edge < 5:
            evidence.append("Market and model did not provide a strong independent edge; normal upset/variance remains plausible")
        else:
            evidence.append("No structural failure identified; preserve as normal sports variance")

    return {"tags": sorted(set(tags)), "evidence": evidence, "status": "HYPOTHESIS_ONLY"}
