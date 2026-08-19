from __future__ import annotations

import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
HISTORY = ROOT / "data" / "football" / "history"
BETANO_URL = "https://www.betano.bet.br/sport/futebol/jogos-de-hoje/"
MIN_ODD = 1.50
MAX_ODD = 2.00
TARGET = 3
TARGET_CENTER = 1.72
FAMILY_BONUS = {"GOALS": 3.5, "CORNERS": 3.0, "CARDS": 2.0, "SHOTS": 1.5, "RESULT": 0.0}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _betano_odd(leg: dict[str, Any]) -> float | None:
    for name, value in (leg.get("bookmaker_quotes") or {}).items():
        if str(name).strip().casefold() == "betano":
            try:
                odd = float(value)
            except (TypeError, ValueError):
                return None
            return odd if odd > 1.0 else None
    return None


def _execution_leg(leg: dict[str, Any]) -> dict[str, Any] | None:
    odd = _betano_odd(leg)
    if odd is None:
        return None
    copy = dict(leg)
    copy["odd"] = round(odd, 2)
    copy["bookmaker"] = "Betano"
    copy["execution_bookmaker"] = "Betano"
    copy["execution_url"] = BETANO_URL
    copy.setdefault("status", "PENDING")
    return copy


def _family(leg: dict[str, Any]) -> str:
    explicit = str(leg.get("market_family") or "").upper()
    if explicit:
        return explicit
    market = str(leg.get("market") or "").casefold()
    if "gol" in market or "goal" in market or "ambas" in market:
        return "GOALS"
    if "escante" in market or "corner" in market:
        return "CORNERS"
    if "cart" in market or "card" in market:
        return "CARDS"
    if "chute" in market or "shot" in market:
        return "SHOTS"
    return "RESULT"


def _quality(legs: list[dict[str, Any]], total: float) -> tuple[float, str]:
    probabilities = [float(leg.get("model_probability") or 0) for leg in legs]
    scores = [float(leg.get("score") or 0) for leg in legs]
    min_probability = min(probabilities)
    combined = math.prod(probabilities)
    avg_score = sum(scores) / len(scores)
    model_market = all(str(leg.get("signal_source") or "") == "MODEL+MARKET" for leg in legs)
    if model_market and min_probability >= 0.73:
        tier, bonus = "STRICT", 6.0
    elif min_probability >= 0.69:
        tier, bonus = "STRONG", 3.0
    else:
        tier, bonus = "CONSENSUS", 0.0
    family_bonus = sum(FAMILY_BONUS.get(_family(leg), 0.0) for leg in legs) / len(legs)
    rating = avg_score + combined * 24 + bonus + family_bonus - abs(total - TARGET_CENTER) * 3
    return rating, tier


def _ticket(ticket_id: int, legs: list[dict[str, Any]], total: float, tier: str) -> dict[str, Any]:
    estimated = math.prod(float(leg.get("model_probability") or 0) for leg in legs)
    score = sum(float(leg.get("score") or 0) for leg in legs) / len(legs)
    families = sorted({_family(leg) for leg in legs})
    return {
        "ticket_id": f"B{ticket_id}",
        "profile": "CONSERVADOR" if ticket_id == 1 else "EQUILIBRADO" if ticket_id == 2 else "SELETIVO",
        "quality_tier": tier,
        "bookmaker": "Betano",
        "total_odd": round(total, 2),
        "estimated_probability": round(estimated, 4),
        "score": round(score, 1),
        "market_families": families,
        "legs": legs,
        "status": "PENDING",
        "reason": "Bilhete multimercado Betano com partidas exclusivas; gols, escanteios, cartões, chutes e resultado competem pelo melhor score.",
        "execution": {
            "ready": True,
            "bookmaker": "Betano",
            "url": BETANO_URL,
            "total_odd": round(total, 2),
            "mode": "OPEN_AND_COPY",
        },
    }


def _signature(legs: list[dict[str, Any]]) -> tuple[tuple[Any, str, str], ...]:
    return tuple(sorted((leg.get("fixture_id"), str(leg.get("market") or ""), str(leg.get("selection") or "")) for leg in legs))


def _portfolio_has_unique_fixtures(tickets: list[dict[str, Any]]) -> bool:
    used: set[Any] = set()
    for ticket in tickets:
        legs = ticket.get("legs") or []
        if not legs:
            return False
        local: set[Any] = set()
        for leg in legs:
            fixture_id = leg.get("fixture_id")
            if fixture_id is None:
                return False
            if fixture_id in local:
                return False
            local.add(fixture_id)
        if local & used:
            return False
        used.update(local)
    return True


def build_betano_tickets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    seen_legs: set[tuple[Any, str, str]] = set()
    for match in payload.get("all_matches") or []:
        for raw in match.get("eligible_legs") or []:
            execution_leg = _execution_leg(raw)
            if not execution_leg:
                continue
            key = (
                execution_leg.get("fixture_id"),
                str(execution_leg.get("market") or ""),
                str(execution_leg.get("selection") or ""),
            )
            if key in seen_legs:
                continue
            seen_legs.add(key)
            legs.append(execution_leg)

    legs.sort(key=lambda row: (-float(row.get("score") or 0), -float(row.get("model_probability") or 0)))
    candidates: list[tuple[float, list[dict[str, Any]], float, str]] = []

    for leg in legs:
        total = float(leg["odd"])
        if MIN_ODD <= total <= MAX_ODD and float(leg.get("model_probability") or 0) >= 0.54:
            rating, tier = _quality([leg], total)
            candidates.append((rating, [leg], total, tier))

    for left, right in itertools.combinations(legs[:48], 2):
        if left.get("fixture_id") == right.get("fixture_id"):
            continue
        min_probability = min(float(left.get("model_probability") or 0), float(right.get("model_probability") or 0))
        avg_score = (float(left.get("score") or 0) + float(right.get("score") or 0)) / 2
        if min_probability < 0.65 or avg_score < 57:
            continue
        total = float(left["odd"]) * float(right["odd"])
        if not (MIN_ODD <= total <= MAX_ODD):
            continue
        rating, tier = _quality([left, right], total)
        candidates.append((rating, [left, right], total, tier))

    candidates.sort(key=lambda item: -item[0])
    selected: list[dict[str, Any]] = []
    seen: set[tuple[tuple[Any, str, str], ...]] = set()
    used_fixtures: set[Any] = set()

    for _, candidate_legs, total, tier in candidates:
        sig = _signature(candidate_legs)
        if sig in seen:
            continue
        fixtures = {leg.get("fixture_id") for leg in candidate_legs}
        if None in fixtures or not fixtures:
            continue
        if fixtures & used_fixtures:
            continue
        selected.append(_ticket(len(selected) + 1, candidate_legs, total, tier))
        seen.add(sig)
        used_fixtures.update(fixtures)
        if len(selected) >= TARGET:
            break

    assert _portfolio_has_unique_fixtures(selected), "Betano ticket portfolio contains repeated fixture"
    return selected


def main() -> int:
    data_path = DASHBOARD / "data.json"
    status_path = DASHBOARD / "run_status.json"
    payload = _load(data_path)
    lock = payload.get("ticket_lock") or {}
    existing = payload.get("tickets") or []
    existing_valid = len(existing) >= TARGET and _portfolio_has_unique_fixtures(existing)

    if lock.get("locked") and existing_valid:
        tickets = existing
    else:
        if lock.get("locked") and not existing_valid:
            payload["ticket_lock"] = {
                "locked": False,
                "invalidated_at": datetime.now(timezone.utc).isoformat(),
                "reason": "Lock invalidado: havia fixture repetido entre bilhetes. Regeração obrigatória com partidas exclusivas.",
            }
        tickets = build_betano_tickets(payload)

    payload["tickets"] = tickets
    payload["approved"] = tickets
    payload["tickets_ready"] = len(tickets)
    payload["ticket_target"] = TARGET
    payload["bookmakers_used"] = ["Betano"] if tickets else []
    payload["execution_bookmaker"] = "Betano"
    payload["execution_url"] = BETANO_URL
    payload["execution_ready"] = len(tickets) == TARGET
    payload["fixture_exclusivity"] = {
        "enabled": True,
        "rule": "A fixture may appear in only one ticket per daily portfolio",
        "valid": _portfolio_has_unique_fixtures(tickets),
        "unique_fixtures": len({leg.get("fixture_id") for ticket in tickets for leg in (ticket.get("legs") or [])}),
    }
    payload["board_status"] = "READY" if len(tickets) == TARGET else ("PARTIAL" if tickets else "NO_TICKETS")
    payload["strict_tickets"] = sum(1 for ticket in tickets if ticket.get("quality_tier") == "STRICT")
    payload["model_version"] = "football-multimarket-betano-v4-exclusive"
    market_analysis = payload.setdefault("market_analysis", {})
    market_analysis["execution_bookmaker"] = "Betano"
    market_analysis["selected_families"] = {
        family: sum(1 for ticket in tickets for leg in (ticket.get("legs") or []) if _family(leg) == family)
        for family in ("GOALS", "CORNERS", "CARDS", "SHOTS", "RESULT")
    }

    current_lock = payload.get("ticket_lock") or {}
    if len(tickets) == TARGET and not current_lock.get("locked"):
        payload["ticket_lock"] = {
            "locked": True,
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "reason": "3 bilhetes oficiais multimercado congelados; fixtures exclusivos entre B1/B2/B3 para auditoria e settlement.",
        }

    _dump(data_path, payload)
    board_date = str(payload.get("board_date") or "")
    if board_date:
        _dump(HISTORY / f"{board_date}.json", payload)

    status = _load(status_path) if status_path.exists() else {}
    status["tickets_ready"] = len(tickets)
    status["target_tickets"] = TARGET
    status["board_status"] = payload["board_status"]
    status["execution_bookmaker"] = "Betano"
    status["execution_ready"] = len(tickets) == TARGET
    status["fixture_exclusivity"] = bool(payload["fixture_exclusivity"]["valid"])
    status["multi_market"] = True
    status["ticket_lock"] = bool((payload.get("ticket_lock") or {}).get("locked"))
    if len(tickets) == TARGET:
        status["status"] = "SUCCESS"
        status["message"] = "3 bilhetes multimercado Betano publicados; nenhum jogo se repete entre B1, B2 e B3."
    elif tickets:
        status["message"] = f"{len(tickets)}/3 bilhetes multimercado independentes atingiram os filtros; jogos não são repetidos para completar a meta."
    else:
        status["message"] = "Nenhuma combinação multimercado independente na Betano atingiu os filtros e a faixa de odd."
    _dump(status_path, status)

    print(
        f"Betano multi-market tickets: {len(tickets)}/{TARGET}; "
        f"exclusive={status['fixture_exclusivity']}; locked={status['ticket_lock']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
