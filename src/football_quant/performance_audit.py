from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "data" / "football" / "history"
DASHBOARD = ROOT / "dashboard"
OUTPUT = ROOT / "data" / "football" / "performance_audit.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


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


def _selection_key(leg: dict[str, Any]) -> str:
    metric = str(leg.get("settlement_metric") or "").lower()
    op = str(leg.get("settlement_operator") or "").lower()
    line = leg.get("settlement_line")
    scope = str(leg.get("settlement_scope") or "match").lower()
    if metric and op and line is not None:
        return f"{metric}:{scope}:{op}:{float(line):g}"
    return f"{_norm(leg.get('market'))}:{_norm(leg.get('selection'))}"


def _prob_bin(value: Any) -> str:
    try:
        p = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if p >= .90: return ">=90%"
    if p >= .85: return "85-90%"
    if p >= .80: return "80-85%"
    if p >= .75: return "75-80%"
    if p >= .70: return "70-75%"
    return "<70%"


def _score_bin(value: Any) -> str:
    try:
        s = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if s >= 88: return ">=88"
    if s >= 84: return "84-88"
    if s >= 80: return "80-84"
    if s >= 76: return "76-80"
    return "<76"


def _book_bin(value: Any) -> str:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if n >= 8: return "8+"
    if n >= 5: return "5-7"
    if n >= 3: return "3-4"
    return "1-2"


def _bucket() -> dict[str, Any]:
    return {"resolved": 0, "green": 0, "red": 0, "accuracy": None}


def _add(bucket: dict[str, Any], status: str) -> None:
    if status not in {"GREEN", "RED"}:
        return
    bucket["resolved"] += 1
    bucket["green" if status == "GREEN" else "red"] += 1


def _finish(mapping: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for row in mapping.values():
        n = int(row["resolved"])
        row["accuracy"] = round(int(row["green"]) / n, 4) if n else None
    return dict(sorted(mapping.items(), key=lambda item: (-int(item[1]["resolved"]), item[0])))


def build_audit() -> dict[str, Any]:
    groups: dict[str, dict[str, dict[str, Any]]] = {
        key: defaultdict(_bucket) for key in (
            "family", "selection", "league", "country", "signal_source",
            "probability_bin", "score_bin", "bookmaker_depth",
            "ticket_probability_bin", "ticket_leg_count",
        )
    }
    daily: list[dict[str, Any]] = []
    red_legs: list[dict[str, Any]] = []
    resolved_tickets = green_tickets = red_tickets = 0
    resolved_legs = green_legs = red_legs_count = 0

    for path in sorted(HISTORY.glob("????-??-??.json")):
        try:
            data = _load(path)
        except Exception:
            continue
        date = str(data.get("board_date") or path.stem)
        day_green = day_red = day_pending = 0
        for ticket in data.get("tickets") or []:
            ticket_status = str(ticket.get("status") or "").upper()
            if ticket_status == "GREEN":
                resolved_tickets += 1; green_tickets += 1; day_green += 1
            elif ticket_status == "RED":
                resolved_tickets += 1; red_tickets += 1; day_red += 1
            elif ticket_status in {"PENDING", "MANUAL"}:
                day_pending += 1
            if ticket_status in {"GREEN", "RED"}:
                _add(groups["ticket_probability_bin"][_prob_bin(ticket.get("estimated_probability"))], ticket_status)
                _add(groups["ticket_leg_count"][str(len(ticket.get("legs") or []))], ticket_status)

            for leg in ticket.get("legs") or []:
                status = str(leg.get("status") or "").upper()
                if status not in {"GREEN", "RED"}:
                    continue
                resolved_legs += 1
                if status == "GREEN": green_legs += 1
                else: red_legs_count += 1
                keys = {
                    "family": _family(leg),
                    "selection": _selection_key(leg),
                    "league": str(leg.get("league") or "Unknown"),
                    "country": str(leg.get("country") or "Unknown"),
                    "signal_source": str(leg.get("signal_source") or "Unknown"),
                    "probability_bin": _prob_bin(leg.get("model_probability")),
                    "score_bin": _score_bin(leg.get("score")),
                    "bookmaker_depth": _book_bin(leg.get("bookmaker_count")),
                }
                for group, key in keys.items():
                    _add(groups[group][key], status)
                if status == "RED":
                    red_legs.append({
                        "date": date,
                        "ticket_id": ticket.get("ticket_id"),
                        "match": leg.get("match"),
                        "league": leg.get("league"),
                        "country": leg.get("country"),
                        "family": _family(leg),
                        "market": leg.get("market"),
                        "selection": leg.get("selection"),
                        "selection_key": _selection_key(leg),
                        "odd": leg.get("odd"),
                        "model_probability": leg.get("model_probability"),
                        "implied_probability": leg.get("implied_probability"),
                        "score": leg.get("score"),
                        "bookmaker_count": leg.get("bookmaker_count"),
                        "signal_source": leg.get("signal_source"),
                        "result_score": leg.get("result_score"),
                        "result_stat_value": leg.get("result_stat_value"),
                        "result_reason": leg.get("result_reason"),
                    })
        if day_green or day_red or day_pending:
            daily.append({
                "date": date, "green": day_green, "red": day_red, "pending": day_pending,
                "hit_target_2_of_3": day_green >= 2,
            })

    completed_days = [d for d in daily if d["pending"] == 0 and d["green"] + d["red"] > 0]
    days_hit_target = sum(1 for d in completed_days if d["hit_target_2_of_3"])
    result = {
        "summary": {
            "tickets_resolved": resolved_tickets,
            "tickets_green": green_tickets,
            "tickets_red": red_tickets,
            "ticket_accuracy": round(green_tickets / resolved_tickets, 4) if resolved_tickets else None,
            "legs_resolved": resolved_legs,
            "legs_green": green_legs,
            "legs_red": red_legs_count,
            "leg_accuracy": round(green_legs / resolved_legs, 4) if resolved_legs else None,
            "completed_days": len(completed_days),
            "days_with_at_least_2_green": days_hit_target,
            "daily_target_rate": round(days_hit_target / len(completed_days), 4) if completed_days else None,
        },
        "daily": daily,
        "groups": {name: _finish(mapping) for name, mapping in groups.items()},
        "red_legs": red_legs,
    }
    return result


def main() -> int:
    audit = build_audit()
    _dump(OUTPUT, audit)
    _dump(DASHBOARD / "performance_audit.json", audit)
    print(json.dumps(audit["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
