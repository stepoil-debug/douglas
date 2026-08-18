from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TB = ROOT / 'src' / 'football_quant' / 'ticket_builder.py'
CI = ROOT / '.github' / 'workflows' / 'ci.yml'

text = TB.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected 1 match, found {count}')
    text = text.replace(old, new, 1)

replace_once(
    'TARGET_CENTER = 1.72\n',
    'TARGET_CENTER = 1.72\n\n'
    '# Accuracy / risk controls. Prefer fewer tickets over low-quality exposure.\n'
    'MAX_MODEL_MARKET_GAP = 0.12\n'
    'EXTREME_PROBABILITY_EPSILON = 0.01\n'
    'CUP_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY = 0.80\n'
    'GENERAL_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY = 0.69\n',
    'risk constants',
)

replace_once(
    'LOW_SIGNAL_LEAGUE_TERMS = (\n'
    '    "friendly", "friendlies", "u17", "u18", "u19", "u20", "u21", "reserve",\n'
    '    "youth", "women friendly", "amateur",\n'
    ')\n',
    'LOW_SIGNAL_LEAGUE_TERMS = (\n'
    '    "friendly", "friendlies", "u17", "u18", "u19", "u20", "u21", "reserve",\n'
    '    "youth", "women friendly", "amateur",\n'
    ')\n\n'
    'CUP_TERMS = (\n'
    '    " cup", "cup ", "copa", "taça", "taca", "pokal", "coupe", "coppa",\n'
    '    "beker", "pokalen", "cupa", "kubok",\n'
    ')\n',
    'cup terms',
)

replace_once(
    'def _normal(text: Any) -> str:\n'
    '    return re.sub(r"\\s+", " ", str(text or "").strip().casefold())\n\n',
    'def _normal(text: Any) -> str:\n'
    '    return re.sub(r"\\s+", " ", str(text or "").strip().casefold())\n\n\n'
    'def _is_cup_fixture(fixture: dict[str, Any]) -> bool:\n'
    '    league = fixture.get("league") or {}\n'
    '    name = f" {_normal(league.get(\'name\'))} "\n'
    '    league_type = _normal(league.get("type"))\n'
    '    return league_type == "cup" or any(term in name for term in CUP_TERMS)\n\n',
    'cup detector',
)

replace_once(
    '    return score\n\n\ndef _prediction_parts',
    '    if _is_cup_fixture(fixture):\n'
    '        score -= 1\n'
    '    return score\n\n\ndef _prediction_parts',
    'cup ranking penalty',
)

replace_once(
    '\n\ndef _comparison_strength(prediction: dict[str, Any] | None, side: str) -> float:\n',
    '\n\ndef _prediction_risk_flags(parts: dict[str, Any]) -> list[str]:\n'
    '    probabilities = [float(parts.get(key) or 0.0) for key in ("home", "draw", "away")]\n'
    '    flags: list[str] = []\n'
    '    total = sum(probabilities)\n'
    '    if total and not 0.97 <= total <= 1.03:\n'
    '        flags.append("PROBABILITY_SUM_ANOMALY")\n'
    '    if probabilities and (\n'
    '        min(probabilities) <= EXTREME_PROBABILITY_EPSILON\n'
    '        or max(probabilities) >= 1.0 - EXTREME_PROBABILITY_EPSILON\n'
    '    ):\n'
    '        flags.append("EXTREME_PROBABILITY")\n'
    '    rounded = sorted(round(value, 2) for value in probabilities)\n'
    '    if rounded in ([0.0, 0.5, 0.5], [0.0, 0.0, 1.0]):\n'
    '        flags.append("COARSE_PROBABILITY")\n'
    '    return flags\n\n\n'
    'def _comparison_strength(prediction: dict[str, Any] | None, side: str) -> float:\n',
    'prediction risk flags',
)

replace_once(
    'def _market_only_legs(fixture: dict[str, Any], prices: list[dict[str, Any]]) -> list[dict[str, Any]]:\n'
    '    legs: list[dict[str, Any]] = []\n',
    'def _market_only_legs(fixture: dict[str, Any], prices: list[dict[str, Any]]) -> list[dict[str, Any]]:\n'
    '    legs: list[dict[str, Any]] = []\n'
    '    cup_fixture = _is_cup_fixture(fixture)\n',
    'market cup flag',
)

replace_once(
    '            canonical_market = "Dupla chance"\n'
    '            min_probability = 0.69\n',
    '            canonical_market = "Dupla chance"\n'
    '            min_probability = (\n'
    '                CUP_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY\n'
    '                if cup_fixture\n'
    '                else GENERAL_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY\n'
    '            )\n',
    'cup double chance threshold',
)

old_dc = '''        if price and 1.08 <= float(price["odd"]) <= 1.60:\n            calibrated = _calibrated_probability(dc_model, price, model_weight=0.70)\n            legs.append(_base_leg(\n                fixture, "Dupla chance", selection_label, price, calibrated,\n                f"Vitória/empate do lado mais forte soma {dc_model:.0%} no modelo e foi calibrado pelas odds disponíveis.",\n                max(strength, 0.62),\n            ))\n'''
new_dc = '''        if price and 1.08 <= float(price["odd"]) <= 1.60:\n            market_p, _ = _market_probability(price)\n            prediction_flags = _prediction_risk_flags(parts)\n            risky_cup = _is_cup_fixture(fixture) and bool(prediction_flags)\n            # Do not let coarse/extreme 0/50/50-style feeds become artificial\n            # 95% cup signals when the bookmaker consensus is materially weaker.\n            if not (risky_cup and market_p < CUP_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY):\n                model_weight = 0.70\n                if prediction_flags or abs(dc_model - market_p) > MAX_MODEL_MARKET_GAP:\n                    model_weight = 0.25\n                calibrated = _calibrated_probability(dc_model, price, model_weight=model_weight)\n                legs.append(_base_leg(\n                    fixture, "Dupla chance", selection_label, price, calibrated,\n                    f"Vitória/empate do lado mais forte soma {dc_model:.0%} no modelo; confiança calibrada pelo consenso real das casas.",\n                    max(strength, 0.62),\n                ))\n'''
replace_once(old_dc, new_dc, 'double chance calibration')

pattern = re.compile(
    r'    candidates\.sort\(key=lambda item: -item\[0\]\)\n'
    r'    selected: list\[dict\[str, Any\]\] = \[\]\n'
    r'    seen_sets: set\[tuple\[tuple\[Any, str, str\], \.\.\.\]\] = set\(\)\n'
    r'    fixture_exposure: dict\[Any, int\] = \{\}\n\n'
    r'    def signature\(candidate_legs: list\[dict\[str, Any\]\]\) -> tuple\[tuple\[Any, str, str\], \.\.\.\]:\n'
    r'        return tuple\(sorted\(\(leg\["fixture_id"\], str\(leg\["market"\]\), str\(leg\["selection"\]\)\) for leg in candidate_legs\)\)\n\n'
    r'.*?'
    r'    return selected\n',
    re.S,
)
replacement = '''    candidates.sort(key=lambda item: -item[0])\n    selected: list[dict[str, Any]] = []\n    seen_sets: set[tuple[tuple[Any, str, str], ...]] = set()\n    used_fixtures: set[Any] = set()\n\n    def signature(candidate_legs: list[dict[str, Any]]) -> tuple[tuple[Any, str, str], ...]:\n        return tuple(sorted((leg["fixture_id"], str(leg["market"]), str(leg["selection"])) for leg in candidate_legs))\n\n    # Strict diversification: a fixture can appear in one ticket only.\n    for _, candidate_legs, tier, bookmaker, total in candidates:\n        sig = signature(candidate_legs)\n        if sig in seen_sets:\n            continue\n        fixtures = {leg["fixture_id"] for leg in candidate_legs}\n        if fixtures & used_fixtures:\n            continue\n        selected.append(_ticket_from_legs(len(selected) + 1, candidate_legs, bookmaker, total, tier))\n        seen_sets.add(sig)\n        used_fixtures.update(fixtures)\n        if len(selected) >= target:\n            break\n\n    # Never relax diversification just to fabricate three tickets.\n    return selected\n'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f'ticket diversification block: expected 1 match, found {count}')

replace_once(
    '        "prediction_available": bool(prediction),\n'
    '        "best_market": best_leg,\n',
    '        "prediction_available": bool(prediction),\n'
    '        "prediction_risk_flags": _prediction_risk_flags(parts) if prediction else [],\n'
    '        "best_market": best_leg,\n',
    'risk flags summary',
)

TB.write_text(text, encoding='utf-8')

ci = CI.read_text(encoding='utf-8')
old_ci = """          assert all(len({leg['bookmaker'] for leg in t['legs']}) == 1 for t in tickets)\n          print('3 executable tickets OK')\n"""
new_ci = """          assert all(len({leg['bookmaker'] for leg in t['legs']}) == 1 for t in tickets)\n          fixture_ids = [leg['fixture_id'] for ticket in tickets for leg in ticket['legs']]\n          assert len(fixture_ids) == len(set(fixture_ids)), tickets\n          print('3 executable tickets with exclusive fixtures OK')\n"""
if ci.count(old_ci) != 1:
    raise RuntimeError(f'CI uniqueness assertion: expected 1 match, found {ci.count(old_ci)}')
ci = ci.replace(old_ci, new_ci, 1)
CI.write_text(ci, encoding='utf-8')
