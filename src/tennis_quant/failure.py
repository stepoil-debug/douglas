from __future__ import annotations

from typing import Any


def classify_postmortem(snapshot: dict[str, Any], actual: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rule-based V1 post-mortem. It records hypotheses, never rewrites the frozen prediction."""
    tags: list[str] = []
    evidence: list[str] = []
    disagreement = float(snapshot.get("disagreement_pp", 0))
    data_quality = float(snapshot.get("data_quality", 0))
    edge = float(snapshot.get("edge_pp", 0))

    if disagreement >= 10:
        tags.append("ERR-UNC")
        evidence.append("High model disagreement before the match")
    if data_quality < 0.7:
        tags.append("ERR-DAT")
        evidence.append("Prediction used incomplete contextual data")
    if edge < 5:
        tags.append("ERR-MKT")
        evidence.append("Thin model edge versus market consensus")

    if actual:
        if actual.get("retired"):
            tags.append("ERR-INJ")
            evidence.append("Match ended with retirement/physical event")
        if actual.get("adverse_market_move_pp", 0) >= 5:
            tags.append("ERR-MKT")
            evidence.append("Meaningful adverse closing-line movement")

    if not tags:
        tags.append("ERR-RND")
        evidence.append("No structural failure identified; preserve as normal sports variance")

    return {"tags": sorted(set(tags)), "evidence": evidence, "status": "HYPOTHESIS_ONLY"}
