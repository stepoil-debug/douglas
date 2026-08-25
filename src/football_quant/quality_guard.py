from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "data" / "football" / "performance_audit.json"
FINAL_STATUSES = {"FT", "AET", "PEN"}

BASE_MIN_PROBABILITY = 0.78
BASE_MIN_SCORE = 80.0
BASE_MIN_BOOKMAKERS = 5


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def load_audit() -> dict[str, Any]:
    if not AUDIT_PATH.exists():
        return {}
    try:
        return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _score(fixture: dict[str, Any]) -> tuple[int, int] | None:
    status = str((((fixture.get("fixture") or {}).get("status") or {}).get("short") or "")).upper()
    if status not in FINAL_STATUSES:
        return None
    score = fixture.get("score") or {}
    ft = score.get("fulltime") or {}
    home, away = ft.get("home"), ft.get("away")
    if home is None or away is None:
        goals = fixture.get("goals") or {}
        home, away = goals.get("home"), goals.get("away")
    try:
        return int(home), int(away)
    except (TypeError, ValueError):
        return None


def build_recent_context(home_rows: list[dict[str, Any]], away_rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: list[int] = []
    for row in list(home_rows) + list(away_rows):
        score = _score(row)
        if score is None:
            continue
        totals.append(score[0] + score[1])
    if not totals:
        return {"sample": 0}
    n = len(totals)
    return {
        "sample": n,
        "avg_total_goals": round(sum(totals) / n, 3),
        "over_1_5_rate": round(sum(1 for x in totals if x > 1.5) / n, 4),
        "over_2_5_rate": round(sum(1 for x in totals if x > 2.5) / n, 4),
        "under_2_5_rate": round(sum(1 for x in totals if x < 2.5) / n, 4),
        "under_3_5_rate": round(sum(1 for x in totals if x < 3.5) / n, 4),
        "under_4_5_rate": round(sum(1 for x in totals if x < 4.5) / n, 4),
        "five_plus_rate": round(sum(1 for x in totals if x >= 5) / n, 4),
        "max_total_goals": max(totals),
    }


def _selection_key(leg: dict[str, Any]) -> str:
    metric = str(leg.get("settlement_metric") or "").lower()
    op = str(leg.get("settlement_operator") or "").lower()
    line = leg.get("settlement_line")
    scope = str(leg.get("settlement_scope") or "match").lower()
    if metric and op and line is not None:
        return f"{metric}:{scope}:{op}:{float(line):g}"
    return f"{_norm(leg.get('market'))}:{_norm(leg.get('selection'))}"


def _family(leg: dict[str, Any]) -> str:
    explicit = str(leg.get("market_family") or "").upper()
    if explicit:
        return explicit
    market = _norm(leg.get("market"))
    if "gol" in market or "goal" in market or "ambas" in market:
        return "GOALS"
    if "corner" in market or "escante" in market:
        return "CORNERS"
    if "card" in market or "cart" in market:
        return "CARDS"
    if "shot" in market or "chute" in market:
        return "SHOTS"
    return "RESULT"


def _half_line(line: Any) -> bool:
    try:
        value = float(line)
    except (TypeError, ValueError):
        return False
    doubled = value * 2.0
    return abs(doubled - round(doubled)) < 1e-8 and int(round(doubled)) % 2 == 1


def _history_bucket(audit: dict[str, Any], group: str, key: str) -> dict[str, Any]:
    return (((audit.get("groups") or {}).get(group) or {}).get(key) or {})


def _empirical_bonus(audit: dict[str, Any], leg: dict[str, Any]) -> tuple[float, list[str], float, float]:
    """Return score bonus, notes and stricter probability/score floors.

    History is used conservatively: tiny samples can add a small bonus, but only
    groups with >=5 resolved observations can materially tighten a threshold.
    """
    bonus = 0.0
    notes: list[str] = []
    min_probability = BASE_MIN_PROBABILITY
    min_score = BASE_MIN_SCORE

    selection = _history_bucket(audit, "selection", _selection_key(leg))
    n = int(selection.get("resolved") or 0)
    acc = selection.get("accuracy")
    if n >= 5 and acc is not None:
        accuracy = float(acc)
        notes.append(f"selection_history={accuracy:.0%}/{n}")
        if accuracy < 0.70:
            min_probability = max(min_probability, 0.86)
            min_score = max(min_score, 85.0)
            bonus -= 5.0
        elif accuracy >= 0.85:
            bonus += 3.0
        elif accuracy >= 0.75:
            bonus += 1.0

    family = _family(leg)
    family_bucket = _history_bucket(audit, "family", family)
    fn = int(family_bucket.get("resolved") or 0)
    facc = family_bucket.get("accuracy")
    if fn >= 8 and facc is not None:
        accuracy = float(facc)
        notes.append(f"family_history={accuracy:.0%}/{fn}")
        if accuracy < 0.67:
            min_probability = max(min_probability, 0.82)
            min_score = max(min_score, 82.0)
            bonus -= 3.0
        elif accuracy >= 0.78:
            bonus += 1.5

    source = str(leg.get("signal_source") or "Unknown")
    source_bucket = _history_bucket(audit, "signal_source", source)
    sn = int(source_bucket.get("resolved") or 0)
    sacc = source_bucket.get("accuracy")
    if sn >= 5 and sacc is not None:
        accuracy = float(sacc)
        notes.append(f"source_history={accuracy:.0%}/{sn}")
        if accuracy < 0.65:
            min_probability = max(min_probability, 0.82)
            min_score = max(min_score, 82.0)
            bonus -= 3.0
        elif accuracy >= 0.78:
            bonus += 1.0

    return bonus, notes, min_probability, min_score


def _recent_goal_requirements(leg: dict[str, Any], recent: dict[str, Any]) -> tuple[bool, float, list[str]]:
    sample = int(recent.get("sample") or 0)
    if sample < 6:
        return True, -1.0, ["recent_sample_small"]
    metric = str(leg.get("settlement_metric") or "")
    if metric != "goals":
        return True, 0.0, []
    op = str(leg.get("settlement_operator") or "")
    line = float(leg.get("settlement_line") or 0)
    five_plus = float(recent.get("five_plus_rate") or 0)
    reasons: list[str] = []
    bonus = 0.0

    if op == "over" and math.isclose(line, 1.5):
        rate = float(recent.get("over_1_5_rate") or 0)
        reasons.append(f"recent_over15={rate:.0%}")
        if rate < 0.70:
            return False, 0.0, reasons + ["recent_over15_below_70"]
        bonus += max(0.0, (rate - 0.70) * 10)
    elif op == "over" and math.isclose(line, 2.5):
        rate = float(recent.get("over_2_5_rate") or 0)
        reasons.append(f"recent_over25={rate:.0%}")
        if rate < 0.65:
            return False, 0.0, reasons + ["recent_over25_below_65"]
        bonus += max(0.0, (rate - 0.65) * 8)
    elif op == "under" and math.isclose(line, 2.5):
        rate = float(recent.get("under_2_5_rate") or 0)
        reasons.extend([f"recent_under25={rate:.0%}", f"recent_5plus={five_plus:.0%}"])
        if rate < 0.75 or five_plus > 0.10:
            return False, 0.0, reasons + ["recent_under25_not_stable"]
        bonus += max(0.0, (rate - 0.75) * 8)
    elif op == "under" and math.isclose(line, 3.5):
        rate = float(recent.get("under_3_5_rate") or 0)
        reasons.extend([f"recent_under35={rate:.0%}", f"recent_5plus={five_plus:.0%}"])
        if rate < 0.75 or five_plus > 0.15:
            return False, 0.0, reasons + ["recent_under35_not_stable"]
        bonus += max(0.0, (rate - 0.75) * 8)
    elif op == "under" and math.isclose(line, 4.5):
        rate = float(recent.get("under_4_5_rate") or 0)
        reasons.extend([f"recent_under45={rate:.0%}", f"recent_5plus={five_plus:.0%}"])
        if rate < 0.85 or five_plus > 0.10:
            return False, 0.0, reasons + ["recent_under45_not_stable"]
        bonus += max(0.0, (rate - 0.85) * 10)
    return True, bonus, reasons


def apply_quality_guard(
    legs: list[dict[str, Any]],
    recent: dict[str, Any],
    audit: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit = audit or {}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in legs:
        leg = dict(raw)
        reasons: list[str] = []
        probability = float(leg.get("model_probability") or 0)
        score = float(leg.get("score") or 0)
        books = int(leg.get("bookmaker_count") or 0)
        family = _family(leg)
        metric = str(leg.get("settlement_metric") or "")
        op = str(leg.get("settlement_operator") or "")
        line = leg.get("settlement_line")
        source = str(leg.get("signal_source") or "")
        risk_flags = set(str(flag) for flag in (leg.get("risk_flags") or []))

        bonus, history_notes, min_probability, min_score = _empirical_bonus(audit, leg)
        reasons.extend(history_notes)

        # Standardize totals to half-point lines. Integer/quarter Asian lines
        # create push/half-win semantics and were contaminating GREEN/RED.
        if metric in {"goals", "corner_kicks", "yellow_cards", "total_shots", "shots_on_goal"} and line is not None:
            if not _half_line(line):
                leg["quality_guard"] = {"accepted": False, "reasons": reasons + ["non_half_line_rejected"]}
                rejected.append(leg)
                continue

        if books < BASE_MIN_BOOKMAKERS:
            reasons.append(f"bookmakers<{BASE_MIN_BOOKMAKERS}")
        if risk_flags & {"MODEL_MARKET_DISAGREEMENT", "EXTREME_PROBABILITY", "COARSE_PROBABILITY"}:
            reasons.append("prediction_risk_flag")

        # Result markets were the weakest family in the audit (63.6%). Keep
        # them only when both probability and score are materially stronger.
        if family == "RESULT":
            min_probability = max(min_probability, 0.82)
            min_score = max(min_score, 82.0)
            if source == "MODEL+MARKET":
                min_probability = max(min_probability, 0.86)
                min_score = max(min_score, 84.0)

        if family == "GOALS" and metric == "goals" and line is not None:
            line_value = float(line)
            if op == "under" and math.isclose(line_value, 4.5):
                min_probability = max(min_probability, 0.84)
                min_score = max(min_score, 84.0)
                if books < 8:
                    reasons.append("under45_requires_8_books")
            elif op == "under" and math.isclose(line_value, 3.5):
                min_probability = max(min_probability, 0.80)
                min_score = max(min_score, 82.0)
            elif op == "under" and math.isclose(line_value, 2.5):
                min_probability = max(min_probability, 0.86)
                min_score = max(min_score, 85.0)
            elif op == "over" and math.isclose(line_value, 1.5):
                min_probability = max(min_probability, 0.80)
                min_score = max(min_score, 80.0)
                bonus += 2.0  # 5/5 GREEN in deterministic audit sample.
            elif op == "over" and math.isclose(line_value, 2.5):
                min_probability = max(min_probability, 0.82)
                min_score = max(min_score, 82.0)
            else:
                min_probability = max(min_probability, 0.84)
                min_score = max(min_score, 84.0)

        if family in {"CORNERS", "CARDS", "SHOTS"}:
            min_probability = max(min_probability, 0.80)
            min_score = max(min_score, 80.0)

        if metric == "btts":
            min_probability = max(min_probability, 0.80)
            min_score = max(min_score, 82.0)

        recent_ok, recent_bonus, recent_notes = _recent_goal_requirements(leg, recent)
        reasons.extend(recent_notes)
        bonus += recent_bonus

        accepted_flag = (
            probability >= min_probability
            and score >= min_score
            and books >= BASE_MIN_BOOKMAKERS
            and not (risk_flags & {"MODEL_MARKET_DISAGREEMENT", "EXTREME_PROBABILITY", "COARSE_PROBABILITY"})
            and recent_ok
            and "under45_requires_8_books" not in reasons
        )
        leg["pre_guard_score"] = round(score, 1)
        leg["quality_score"] = round(score + bonus, 1)
        leg["quality_guard"] = {
            "accepted": accepted_flag,
            "min_probability": round(min_probability, 4),
            "min_score": round(min_score, 1),
            "recent_sample": int(recent.get("sample") or 0),
            "reasons": reasons,
        }
        if accepted_flag:
            accepted.append(leg)
        else:
            if probability < min_probability:
                reasons.append(f"probability_below_{min_probability:.0%}")
            if score < min_score:
                reasons.append(f"score_below_{min_score:g}")
            rejected.append(leg)

    accepted.sort(key=lambda row: (-float(row.get("quality_score") or row.get("score") or 0), -float(row.get("model_probability") or 0)))
    return accepted, rejected
