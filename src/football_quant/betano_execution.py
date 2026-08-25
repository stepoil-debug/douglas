from __future__ import annotations

import itertools
import json
import math
from collections import Counter
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
TARGET_CENTER = 1.68
MIN_KICKOFF_GAP_SECONDS = 2 * 60 * 60
MAX_LEGS_PER_FIXTURE_IN_PAIR_POOL = 5
MIN_NEW_LEG_PROBABILITY = 0.78
MIN_NEW_LEG_SCORE = 80.0
MIN_PAIR_COMBINED_PROBABILITY = 0.68
MIN_SINGLE_PROBABILITY = 0.70
MIN_BOOKMAKER_COUNT = 5

# Historical audit: RESULT lagged the goals family and MODEL+MARKET was the
# weakest signal source. New/untested stat families remain eligible, but do not
# receive an artificial bonus before enough settlement history exists.
FAMILY_BONUS = {"GOALS": 2.5, "CORNERS": 1.0, "CARDS": 0.5, "SHOTS": 0.0, "RESULT": -4.0}
MAX_CLUSTER_LEGS = {"GOALS_UNDER": 2, "RESULT": 1}


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
    guard = leg.get("quality_guard") or {}
    if guard and guard.get("accepted") is False:
        return None
    probability = float(leg.get("model_probability") or 0)
    quality_score = float(leg.get("quality_score") or leg.get("score") or 0)
    books = int(leg.get("bookmaker_count") or 0)
    if probability < MIN_NEW_LEG_PROBABILITY or quality_score < MIN_NEW_LEG_SCORE or books < MIN_BOOKMAKER_COUNT:
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


def _risk_cluster(leg: dict[str, Any]) -> str:
    family = _family(leg)
    if family == "GOALS":
        metric = str(leg.get("settlement_metric") or "")
        op = str(leg.get("settlement_operator") or "")
        if metric == "goals" and op == "under":
            return "GOALS_UNDER"
        if metric == "goals" and op == "over":
            return "GOALS_OVER"
        if metric == "btts":
            return "GOALS_BTTS"
    if family == "RESULT":
        return "RESULT"
    return family


def _quality_score(leg: dict[str, Any]) -> float:
    return float(leg.get("quality_score") or leg.get("score") or 0)


def _quality(legs: list[dict[str, Any]], total: float) -> tuple[float, str]:
    probabilities = [float(leg.get("model_probability") or 0) for leg in legs]
    scores = [_quality_score(leg) for leg in legs]
    min_probability = min(probabilities)
    combined = math.prod(probabilities)
    avg_score = sum(scores) / len(scores)
    if min_probability >= 0.84 and min(scores) >= 84:
        tier, bonus = "STRICT", 7.0
    elif min_probability >= 0.80 and min(scores) >= 82:
        tier, bonus = "STRONG", 3.5
    else:
        tier, bonus = "SCREENED", 0.0
    family_bonus = sum(FAMILY_BONUS.get(_family(leg), 0.0) for leg in legs) / len(legs)
    cluster_penalty = 2.0 if any(_risk_cluster(leg) == "GOALS_UNDER" for leg in legs) else 0.0
    rating = avg_score + combined * 30 + bonus + family_bonus - abs(total - TARGET_CENTER) * 3 - cluster_penalty
    return rating, tier


def _ticket(ticket_id: int, legs: list[dict[str, Any]], total: float, tier: str) -> dict[str, Any]:
    estimated = math.prod(float(leg.get("model_probability") or 0) for leg in legs)
    score = sum(_quality_score(leg) for leg in legs) / len(legs)
    families = sorted({_family(leg) for leg in legs})
    clusters = sorted({_risk_cluster(leg) for leg in legs})
    return {
        "ticket_id": f"B{ticket_id}",
        "profile": "CONSERVADOR" if ticket_id == 1 else "EQUILIBRADO" if ticket_id == 2 else "SELETIVO",
        "quality_tier": tier,
        "bookmaker": "Betano",
        "total_odd": round(total, 2),
        "estimated_probability": round(estimated, 4),
        "score": round(score, 1),
        "market_families": families,
        "risk_clusters": clusters,
        "legs": legs,
        "status": "PENDING",
        "reason": (
            "Bilhete accuracy-first: pernas filtradas por forma recente, histórico GREEN/RED, "
            "consenso de casas, score mínimo, diversificação de risco e intervalo mínimo de 2 horas."
        ),
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
            if fixture_id is None or fixture_id in local:
                return False
            local.add(fixture_id)
        if local & used:
            return False
        used.update(local)
    return True


def _kickoff_timestamp(leg: dict[str, Any]) -> float | None:
    raw = str(leg.get("kickoff_iso") or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _unique_fixture_times(legs: list[dict[str, Any]]) -> list[float] | None:
    by_fixture: dict[Any, float] = {}
    for leg in legs:
        fixture_id = leg.get("fixture_id")
        if fixture_id is None:
            return None
        ts = _kickoff_timestamp(leg)
        if ts is None:
            return None
        previous = by_fixture.get(fixture_id)
        if previous is not None and abs(previous - ts) > 60:
            return None
        by_fixture[fixture_id] = ts
    return list(by_fixture.values())


def _times_are_spaced(times: list[float], extra_times: list[float] | None = None) -> bool:
    values = list(times) + list(extra_times or [])
    for left, right in itertools.combinations(values, 2):
        if abs(left - right) < MIN_KICKOFF_GAP_SECONDS:
            return False
    return True


def _legs_have_required_spacing(legs: list[dict[str, Any]], used_times: list[float] | None = None) -> bool:
    times = _unique_fixture_times(legs)
    return times is not None and _times_are_spaced(times, used_times)


def _portfolio_has_required_spacing(tickets: list[dict[str, Any]]) -> bool:
    all_legs = [leg for ticket in tickets for leg in (ticket.get("legs") or [])]
    return bool(all_legs) and _legs_have_required_spacing(all_legs)


def _pair_pool(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    counts: dict[Any, int] = {}
    for leg in legs:
        fixture_id = leg.get("fixture_id")
        current = counts.get(fixture_id, 0)
        if current >= MAX_LEGS_PER_FIXTURE_IN_PAIR_POOL:
            continue
        counts[fixture_id] = current + 1
        pool.append(leg)
    return pool


def _candidate_cluster_ok(candidate_legs: list[dict[str, Any]], portfolio_clusters: Counter[str]) -> bool:
    clusters = [_risk_cluster(leg) for leg in candidate_legs]
    # The 24/08 failure mode was two independent unders inside the same ticket.
    if clusters.count("GOALS_UNDER") > 1:
        return False
    proposed = portfolio_clusters.copy()
    proposed.update(clusters)
    for cluster, cap in MAX_CLUSTER_LEGS.items():
        if proposed[cluster] > cap:
            return False
    return True


def _candidate_probability_ok(candidate_legs: list[dict[str, Any]]) -> bool:
    probabilities = [float(leg.get("model_probability") or 0) for leg in candidate_legs]
    if not probabilities:
        return False
    combined = math.prod(probabilities)
    if len(candidate_legs) == 1:
        return probabilities[0] >= MIN_SINGLE_PROBABILITY
    return min(probabilities) >= 0.80 and combined >= MIN_PAIR_COMBINED_PROBABILITY


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

    legs.sort(key=lambda row: (-_quality_score(row), -float(row.get("model_probability") or 0)))
    candidates: list[tuple[float, list[dict[str, Any]], float, str]] = []

    for leg in legs:
        total = float(leg["odd"])
        if MIN_ODD <= total <= MAX_ODD and _candidate_probability_ok([leg]) and _quality_score(leg) >= 84:
            rating, tier = _quality([leg], total)
            candidates.append((rating, [leg], total, tier))

    pair_pool = _pair_pool(legs)
    for left, right in itertools.combinations(pair_pool, 2):
        if left.get("fixture_id") == right.get("fixture_id"):
            continue
        if not _legs_have_required_spacing([left, right]):
            continue
        candidate_legs = [left, right]
        if not _candidate_probability_ok(candidate_legs):
            continue
        if not _candidate_cluster_ok(candidate_legs, Counter()):
            continue
        avg_score = (_quality_score(left) + _quality_score(right)) / 2
        if avg_score < 82:
            continue
        total = float(left["odd"]) * float(right["odd"])
        if not (MIN_ODD <= total <= MAX_ODD):
            continue
        rating, tier = _quality(candidate_legs, total)
        candidates.append((rating, candidate_legs, total, tier))

    candidates.sort(key=lambda item: -item[0])

    # Every ticket already shown in a partial board is immutable. The new run
    # may only append B2/B3; it cannot replace a published ticket.
    frozen = [dict(ticket) for ticket in (payload.get("previous_published_tickets") or [])][:TARGET]
    selected: list[dict[str, Any]] = list(frozen)
    seen: set[tuple[tuple[Any, str, str], ...]] = {_signature(ticket.get("legs") or []) for ticket in frozen}
    used_fixtures: set[Any] = {
        leg.get("fixture_id") for ticket in frozen for leg in (ticket.get("legs") or []) if leg.get("fixture_id") is not None
    }
    used_kickoff_times = _unique_fixture_times([leg for ticket in frozen for leg in (ticket.get("legs") or [])]) or []
    cluster_counts: Counter[str] = Counter(
        _risk_cluster(leg) for ticket in frozen for leg in (ticket.get("legs") or [])
    )
    used_ticket_ids = {str(ticket.get("ticket_id") or "") for ticket in frozen}

    def next_ticket_number() -> int | None:
        for number in range(1, TARGET + 1):
            if f"B{number}" not in used_ticket_ids:
                return number
        return None

    for _, candidate_legs, total, tier in candidates:
        if len(selected) >= TARGET:
            break
        sig = _signature(candidate_legs)
        if sig in seen:
            continue
        fixtures = {leg.get("fixture_id") for leg in candidate_legs}
        if None in fixtures or not fixtures or fixtures & used_fixtures:
            continue
        if not _legs_have_required_spacing(candidate_legs, used_kickoff_times):
            continue
        if not _candidate_cluster_ok(candidate_legs, cluster_counts):
            continue
        number = next_ticket_number()
        if number is None:
            break
        ticket = _ticket(number, candidate_legs, total, tier)
        selected.append(ticket)
        used_ticket_ids.add(f"B{number}")
        seen.add(sig)
        used_fixtures.update(fixtures)
        candidate_times = _unique_fixture_times(candidate_legs) or []
        used_kickoff_times.extend(candidate_times)
        cluster_counts.update(_risk_cluster(leg) for leg in candidate_legs)

    selected.sort(key=lambda row: str(row.get("ticket_id") or ""))
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
    payload["kickoff_spacing"] = {
        "enabled": True,
        "minimum_minutes": 120,
        "valid": _portfolio_has_required_spacing(tickets),
        "rule": "Every selected fixture must start at least 120 minutes apart from every other selected fixture.",
    }
    payload["accuracy_target"] = {
        "daily_goal": "at least 2 GREEN among 3 published tickets",
        "guaranteed": False,
        "min_new_leg_probability": MIN_NEW_LEG_PROBABILITY,
        "min_pair_combined_probability": MIN_PAIR_COMBINED_PROBABILITY,
        "min_new_leg_score": MIN_NEW_LEG_SCORE,
        "min_bookmaker_count": MIN_BOOKMAKER_COUNT,
        "portfolio_cluster_caps": MAX_CLUSTER_LEGS,
    }
    payload["publication_lock"] = {
        "published_ids": [ticket.get("ticket_id") for ticket in tickets],
        "immutable": True,
        "reason": "Todo bilhete que aparece no painel fica congelado; análises posteriores só podem acrescentar IDs ainda não publicados.",
    }
    payload["board_status"] = "READY" if len(tickets) == TARGET else ("PARTIAL" if tickets else "NO_TICKETS")
    payload["strict_tickets"] = sum(1 for ticket in tickets if ticket.get("quality_tier") == "STRICT")
    payload["model_version"] = "football-accuracy-betano-v6"
    market_analysis = payload.setdefault("market_analysis", {})
    market_analysis["execution_bookmaker"] = "Betano"
    market_analysis["selected_families"] = {
        family: sum(1 for ticket in tickets for leg in (ticket.get("legs") or []) if _family(leg) == family)
        for family in ("GOALS", "CORNERS", "CARDS", "SHOTS", "RESULT")
    }
    market_analysis["risk_cluster_exposure"] = dict(cluster_counts := Counter(
        _risk_cluster(leg) for ticket in tickets for leg in (ticket.get("legs") or [])
    ))

    current_lock = payload.get("ticket_lock") or {}
    if len(tickets) == TARGET and not current_lock.get("locked"):
        payload["ticket_lock"] = {
            "locked": True,
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "reason": "3 bilhetes oficiais accuracy-first congelados para auditoria e settlement.",
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
    status["kickoff_spacing_minutes"] = 120
    status["kickoff_spacing_valid"] = bool(payload["kickoff_spacing"]["valid"])
    status["multi_market"] = True
    status["accuracy_first"] = True
    status["ticket_lock"] = bool((payload.get("ticket_lock") or {}).get("locked"))
    status["publication_immutable"] = True
    if len(tickets) == TARGET:
        status["status"] = "SUCCESS"
        status["message"] = "3 bilhetes publicados com filtros accuracy-first; publicação congelada e meta operacional de 2 GREEN/3 monitorada."
    elif tickets:
        status["status"] = "SUCCESS"
        status["message"] = f"{len(tickets)}/3 bilhetes passaram os filtros reforçados; o motor não reduz qualidade para completar a meta."
    else:
        status["status"] = "SUCCESS"
        status["message"] = "Nenhum bilhete atingiu simultaneamente os novos filtros de acurácia, odd, espaçamento e diversificação."
    _dump(status_path, status)

    print(
        f"Betano accuracy-first tickets: {len(tickets)}/{TARGET}; "
        f"exclusive={status['fixture_exclusivity']}; spacing={status['kickoff_spacing_valid']}; locked={status['ticket_lock']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
