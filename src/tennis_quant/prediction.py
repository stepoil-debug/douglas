from __future__ import annotations

from statistics import pstdev


def clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def weighted_probability(signals: dict[str, float], weights: dict[str, float]) -> float:
    available = [(k, v) for k, v in signals.items() if k in weights and v is not None]
    total_weight = sum(weights[k] for k, _ in available)
    if total_weight <= 0:
        return 0.5
    return clamp(sum(v * weights[k] for k, v in available) / total_weight)


def disagreement_pp(signals: dict[str, float]) -> float:
    values = [v for v in signals.values() if v is not None]
    return (pstdev(values) * 100.0) if len(values) > 1 else 0.0


def confidence_score(
    final_probability: float,
    edge_pp: float,
    disagreement: float,
    data_quality: float,
    weights: dict[str, float],
) -> float:
    probability_score = clamp((final_probability - 0.50) / 0.30, 0, 1)
    edge_score = clamp(edge_pp / 15.0, 0, 1)
    agreement_score = clamp(1.0 - disagreement / 20.0, 0, 1)
    components = {
        "probability": probability_score,
        "edge": edge_score,
        "agreement": agreement_score,
        "data_quality": clamp(data_quality, 0, 1),
    }
    total = sum(weights.get(k, 0) for k in components)
    if total <= 0:
        return 0.0
    return 100.0 * sum(components[k] * weights.get(k, 0) for k in components) / total
