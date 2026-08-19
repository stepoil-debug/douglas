from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient, ApiFootballError

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
HISTORY = ROOT / "data" / "football" / "history"
INITIAL_BANKROLL = 100.0
FIXED_STAKE = 10.0
FINAL_STATUSES = {"FT", "AET", "PEN"}
VOID_STATUSES = {"CANC", "ABD"}
STAT_METRICS = {"corner_kicks", "yellow_cards", "total_shots", "shots_on_goal"}


def now() -> datetime:
    return datetime.now(TZ)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _resolve_api_key() -> str:
    for name in ("API_FOOTBALL_KEY", "API_SPORTS_KEY", "FOOTBALL_API_KEY", "APISPORTS_KEY", "EFOOTBAL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _fixture_map(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            fixture_id = int((row.get("fixture") or {}).get("id"))
        except (TypeError, ValueError):
            continue
        result[fixture_id] = row
    return result


def _regular_score(fixture: dict[str, Any]) -> tuple[int, int] | None:
    score = fixture.get("score") or {}
    fulltime = score.get("fulltime") or {}
    home = fulltime.get("home")
    away = fulltime.get("away")
    if home is None or away is None:
        goals = fixture.get("goals") or {}
        home = goals.get("home")
        away = goals.get("away")
    try:
        return int(home), int(away)
    except (TypeError, ValueError):
        return None


def _team_side(selection: str, home_team: str, away_team: str) -> str | None:
    sel = _normalize(selection)
    home = _normalize(home_team)
    away = _normalize(away_team)
    if home and home in sel:
        return "home"
    if away and away in sel:
        return "away"
    if sel in {"home", "1"} or sel.startswith("mandante:"):
        return "home"
    if sel in {"away", "2"} or sel.startswith("visitante:"):
        return "away"
    return None


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _stat_key(stat_type: Any) -> str | None:
    name = _normalize(stat_type)
    if name in {"corner kicks", "corners", "corner kick"}:
        return "corner_kicks"
    if name in {"yellow cards", "yellow card"}:
        return "yellow_cards"
    if name in {"total shots", "shots total"}:
        return "total_shots"
    if name in {"shots on goal", "shots on target", "shot on goal"}:
        return "shots_on_goal"
    return None


def _statistics_map(fixture: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    teams = fixture.get("teams") or {}
    home_id = (teams.get("home") or {}).get("id")
    away_id = (teams.get("away") or {}).get("id")
    home_name = _normalize((teams.get("home") or {}).get("name"))
    away_name = _normalize((teams.get("away") or {}).get("name"))
    result: dict[str, dict[str, float]] = {"home": {}, "away": {}}

    for row in rows:
        team = row.get("team") or {}
        team_id = team.get("id")
        team_name = _normalize(team.get("name"))
        side = None
        if home_id is not None and team_id == home_id:
            side = "home"
        elif away_id is not None and team_id == away_id:
            side = "away"
        elif home_name and team_name == home_name:
            side = "home"
        elif away_name and team_name == away_name:
            side = "away"
        if side is None:
            continue
        for stat in row.get("statistics") or []:
            key = _stat_key(stat.get("type"))
            value = _numeric(stat.get("value"))
            if key and value is not None:
                result[side][key] = value
    return result


def _line_from_selection(selection: str) -> tuple[str, float] | None:
    text = _normalize(selection).replace(",", ".")
    match = re.search(r"\b(mais de|menos de|over|under)\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    operator = "over" if match.group(1) in {"mais de", "over"} else "under"
    return operator, float(match.group(2))


def _evaluate_total(value: float, operator: str, line: float) -> bool:
    return value > line if operator == "over" else value < line


def _market_family(leg: dict[str, Any]) -> str:
    explicit = str(leg.get("market_family") or "").upper()
    if explicit:
        return explicit
    market = _normalize(leg.get("market"))
    if "corner" in market or "escante" in market:
        return "CORNERS"
    if "card" in market or "cart" in market:
        return "CARDS"
    if "shot" in market or "chute" in market:
        return "SHOTS"
    if "goal" in market or "gol" in market or "ambas" in market:
        return "GOALS"
    return "RESULT"


def _requires_stats(leg: dict[str, Any]) -> bool:
    return str(leg.get("settlement_metric") or "") in STAT_METRICS


def settle_leg(
    leg: dict[str, Any],
    fixture: dict[str, Any] | None,
    statistics: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    settled = dict(leg)
    if fixture is None:
        settled["status"] = "PENDING"
        settled["result_reason"] = "Partida ainda não localizada na atualização de resultados."
        return settled

    fixture_info = fixture.get("fixture") or {}
    status_short = str((fixture_info.get("status") or {}).get("short") or "").upper()
    settled["fixture_status"] = status_short

    if status_short in VOID_STATUSES:
        settled["status"] = "VOID"
        settled["settled_at"] = now().isoformat()
        settled["result_reason"] = f"Partida {status_short}; retirada da simulação até regra específica da casa."
        return settled
    if status_short not in FINAL_STATUSES:
        settled["status"] = "PENDING"
        settled["result_reason"] = f"Partida ainda não encerrada ({status_short or 'sem status'})."
        return settled

    score = _regular_score(fixture)
    if score is None:
        settled["status"] = "MANUAL"
        settled["result_reason"] = "Partida encerrada, mas o placar regulamentar não foi retornado pela API."
        return settled

    home_goals, away_goals = score
    settled["result_score"] = f"{home_goals}-{away_goals}"
    settled["settled_at"] = now().isoformat()
    home_team = str(leg.get("home_team") or "")
    away_team = str(leg.get("away_team") or "")
    market = _normalize(leg.get("market"))
    selection = _normalize(leg.get("selection"))
    total = home_goals + away_goals
    won: bool | None = None
    reason = ""

    # New deterministic metadata path used by the multi-market engine.
    metric = str(leg.get("settlement_metric") or "")
    operator = str(leg.get("settlement_operator") or "")
    scope = str(leg.get("settlement_scope") or "match")
    line_value = leg.get("settlement_line")

    if metric == "btts":
        both_scored = home_goals > 0 and away_goals > 0
        won = both_scored if operator == "yes" else not both_scored
        reason = f"Ambas marcam: {'sim' if both_scored else 'não'} no placar {home_goals}-{away_goals}."
    elif metric == "goals" and operator in {"over", "under"} and line_value is not None:
        line = float(line_value)
        won = _evaluate_total(float(total), operator, line)
        reason = f"Total de gols: {total}; linha {operator} {line:g}."
    elif metric in STAT_METRICS:
        if not statistics:
            settled["status"] = "MANUAL"
            settled["result_reason"] = "Partida encerrada; aguardando estatísticas oficiais do mercado para conferência automática."
            return settled
        side_values = statistics.get(scope) or {}
        if scope == "match":
            home_value = (statistics.get("home") or {}).get(metric)
            away_value = (statistics.get("away") or {}).get(metric)
            if home_value is None or away_value is None:
                settled["status"] = "MANUAL"
                settled["result_reason"] = f"Estatística {metric} ainda não disponível para os dois times."
                return settled
            observed = float(home_value) + float(away_value)
        else:
            observed_raw = side_values.get(metric)
            if observed_raw is None:
                settled["status"] = "MANUAL"
                settled["result_reason"] = f"Estatística {metric} ainda não disponível para {scope}."
                return settled
            observed = float(observed_raw)
        if operator not in {"over", "under"} or line_value is None:
            settled["status"] = "MANUAL"
            settled["result_reason"] = "Mercado estatístico sem linha determinística cadastrada."
            return settled
        line = float(line_value)
        won = _evaluate_total(observed, operator, line)
        settled["result_stat_value"] = observed
        reason = f"{leg.get('market')}: resultado {observed:g}; linha {operator} {line:g}."

    # Legacy result markets remain supported.
    elif "vencedor" in market or market in {"match winner", "1x2", "winner"}:
        side = _team_side(str(leg.get("selection") or ""), home_team, away_team)
        if side == "home":
            won = home_goals > away_goals
        elif side == "away":
            won = away_goals > home_goals
        reason = f"Vencedor em 90 min: {home_team} {home_goals} x {away_goals} {away_team}."
    elif "dupla chance" in market or "double chance" in market:
        if selection in {"home/draw", "home or draw", "1x", "1 or x"}:
            won = home_goals >= away_goals
        elif selection in {"draw/away", "away/draw", "draw or away", "away or draw", "x2", "x or 2"}:
            won = away_goals >= home_goals
        else:
            side = _team_side(str(leg.get("selection") or ""), home_team, away_team)
            if side == "home" and ("empate" in selection or "draw" in selection):
                won = home_goals >= away_goals
            elif side == "away" and ("empate" in selection or "draw" in selection):
                won = away_goals >= home_goals
        reason = f"Dupla chance conferida no placar {home_goals}-{away_goals}."
    elif "ambas marcam" in market or "both teams to score" in market or "btts" in market:
        both_scored = home_goals > 0 and away_goals > 0
        if selection in {"sim", "yes"}:
            won = both_scored
        elif selection in {"não", "nao", "no"}:
            won = not both_scored
        reason = f"Ambas marcam: {'sim' if both_scored else 'não'} no placar {home_goals}-{away_goals}."
    elif "total de gols" in market or "goals" in market or "over/under" in market:
        parsed = _line_from_selection(str(leg.get("selection") or ""))
        if parsed:
            op, line = parsed
            won = _evaluate_total(float(total), op, line)
            reason = f"Total de gols: {total}; linha {op} {line:g}."
    elif "gol da equipe" in market or "team total" in market:
        side = _team_side(str(leg.get("selection") or ""), home_team, away_team)
        if side == "home":
            won = home_goals >= 1
            reason = f"{home_team} marcou {home_goals} gol(s)."
        elif side == "away":
            won = away_goals >= 1
            reason = f"{away_team} marcou {away_goals} gol(s)."

    if won is None:
        settled["status"] = "MANUAL"
        settled["result_reason"] = "Mercado ainda não possui regra automática de conferência."
    else:
        settled["status"] = "GREEN" if won else "RED"
        settled["result_reason"] = reason
    return settled


def settle_ticket(
    ticket: dict[str, Any],
    fixtures: dict[int, dict[str, Any]],
    stats_by_fixture: dict[int, dict[str, dict[str, float]]] | None = None,
) -> dict[str, Any]:
    copy = dict(ticket)
    stats_by_fixture = stats_by_fixture or {}
    legs: list[dict[str, Any]] = []
    for raw in ticket.get("legs") or []:
        try:
            fixture_id = int(raw.get("fixture_id"))
        except (TypeError, ValueError):
            fixture_id = 0
        legs.append(settle_leg(raw, fixtures.get(fixture_id), stats_by_fixture.get(fixture_id)))
    copy["legs"] = legs
    statuses = [str(leg.get("status") or "PENDING").upper() for leg in legs]
    if any(status == "RED" for status in statuses):
        copy["status"] = "RED"
    elif any(status in {"PENDING", "MANUAL"} for status in statuses):
        copy["status"] = "PENDING" if any(status == "PENDING" for status in statuses) else "MANUAL"
    elif statuses and all(status in {"GREEN", "VOID"} for status in statuses):
        copy["status"] = "GREEN" if any(status == "GREEN" for status in statuses) else "VOID"
    else:
        copy["status"] = "PENDING"
    if copy["status"] in {"GREEN", "RED", "VOID"}:
        copy["settled_at"] = now().isoformat()
    return copy


def history_summary() -> dict[str, Any]:
    tickets_resolved = tickets_green = tickets_red = legs_resolved = legs_green = legs_red = 0
    by_market: dict[str, dict[str, Any]] = {}
    for path in HISTORY.glob("????-??-??.json"):
        try:
            data = load(path)
        except Exception:
            continue
        for ticket in data.get("tickets") or []:
            status = str(ticket.get("status") or "").upper()
            if status == "GREEN":
                tickets_resolved += 1
                tickets_green += 1
            elif status == "RED":
                tickets_resolved += 1
                tickets_red += 1
            for leg in ticket.get("legs") or []:
                family = _market_family(leg)
                bucket = by_market.setdefault(family, {"resolved": 0, "green": 0, "red": 0, "accuracy": None})
                leg_status = str(leg.get("status") or "").upper()
                if leg_status == "GREEN":
                    legs_resolved += 1
                    legs_green += 1
                    bucket["resolved"] += 1
                    bucket["green"] += 1
                elif leg_status == "RED":
                    legs_resolved += 1
                    legs_red += 1
                    bucket["resolved"] += 1
                    bucket["red"] += 1
    for bucket in by_market.values():
        resolved = int(bucket["resolved"])
        bucket["accuracy"] = (int(bucket["green"]) / resolved) if resolved else None
    return {
        "resolved": legs_resolved,
        "hits": legs_green,
        "misses": legs_red,
        "accuracy": (legs_green / legs_resolved) if legs_resolved else None,
        "tickets_resolved": tickets_resolved,
        "tickets_hit": tickets_green,
        "tickets_miss": tickets_red,
        "ticket_accuracy": (tickets_green / tickets_resolved) if tickets_resolved else None,
        "by_market": by_market,
    }


def _ticket_profit(ticket: dict[str, Any], stake: float) -> float | None:
    status = str(ticket.get("status") or "").upper()
    odd = float(ticket.get("total_odd") or 0)
    if status == "GREEN":
        return round(stake * max(0.0, odd - 1.0), 2)
    if status == "RED":
        return -round(stake, 2)
    if status == "VOID":
        return 0.0
    return None


def _strategy_base(name: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "initial_bankroll": INITIAL_BANKROLL,
        "fixed_stake": FIXED_STAKE,
        "bankroll": INITIAL_BANKROLL,
        "available_bankroll": INITIAL_BANKROLL,
        "profit": 0.0,
        "roi": 0.0,
        "bets": 0,
        "resolved": 0,
        "greens": 0,
        "reds": 0,
        "pending": 0,
        "open_exposure": 0.0,
        "history": [],
    }


def _apply_bet(strategy: dict[str, Any], date: str, ticket: dict[str, Any], label: str) -> None:
    stake = FIXED_STAKE
    status = str(ticket.get("status") or "PENDING").upper()
    profit = _ticket_profit(ticket, stake)
    record = {
        "date": date,
        "ticket_id": ticket.get("ticket_id"),
        "label": label,
        "odd": ticket.get("total_odd"),
        "estimated_probability": ticket.get("estimated_probability"),
        "stake": stake,
        "status": status,
        "profit": profit,
    }
    strategy["bets"] += 1
    if profit is None:
        strategy["pending"] += 1
        strategy["open_exposure"] += stake
    else:
        strategy["resolved"] += 1
        strategy["profit"] = round(float(strategy["profit"]) + profit, 2)
        strategy["bankroll"] = round(INITIAL_BANKROLL + float(strategy["profit"]), 2)
        if status == "GREEN":
            strategy["greens"] += 1
        elif status == "RED":
            strategy["reds"] += 1
    strategy["history"].append(record)


def build_management() -> dict[str, Any]:
    all_three = _strategy_base(
        "Mão fixa • 3 bilhetes",
        "R$10 em cada um dos 3 bilhetes oficiais do dia. Exposição diária máxima: R$30.",
    )
    safest = _strategy_base(
        "Entrada mais segura",
        "R$10 somente no bilhete com maior probabilidade estimada do dia. Exposição diária máxima: R$10.",
    )
    daily: list[dict[str, Any]] = []

    for path in sorted(HISTORY.glob("????-??-??.json")):
        try:
            data = load(path)
        except Exception:
            continue
        tickets = list(data.get("tickets") or [])
        if not tickets or not (data.get("ticket_lock") or {}).get("locked"):
            continue
        date = str(data.get("board_date") or path.stem)
        for ticket in tickets[:3]:
            _apply_bet(all_three, date, ticket, "Todos os 3")
        safest_ticket = max(
            tickets[:3],
            key=lambda row: (float(row.get("estimated_probability") or 0), float(row.get("score") or 0)),
        )
        _apply_bet(safest, date, safest_ticket, "Mais segura")
        daily.append({
            "date": date,
            "tickets": [
                {
                    "ticket_id": t.get("ticket_id"),
                    "odd": t.get("total_odd"),
                    "probability": t.get("estimated_probability"),
                    "status": t.get("status"),
                }
                for t in tickets[:3]
            ],
            "safest_ticket_id": safest_ticket.get("ticket_id"),
        })

    for strategy in (all_three, safest):
        strategy["available_bankroll"] = round(float(strategy["bankroll"]) - float(strategy["open_exposure"]), 2)
        total_staked_resolved = float(strategy["resolved"]) * FIXED_STAKE
        strategy["roi"] = round((float(strategy["profit"]) / total_staked_resolved * 100), 2) if total_staked_resolved else 0.0
        strategy["accuracy"] = round((float(strategy["greens"]) / float(strategy["resolved"]) * 100), 2) if strategy["resolved"] else None

    return {
        "updated_at": now().isoformat(),
        "initial_bankroll": INITIAL_BANKROLL,
        "fixed_stake": FIXED_STAKE,
        "strategies": {"all_three": all_three, "safest_only": safest},
        "daily": daily,
        "notes": [
            "Simulação educacional; não executa apostas nem movimenta dinheiro real.",
            "GREEN/RED usa placar e estatísticas oficiais da API-Football para os mercados suportados.",
            "Gols, escanteios, cartões amarelos, chutes e chutes no alvo possuem conferência automática quando a API fornece a estatística final.",
        ],
    }


def pending_dates(max_dates: int) -> list[str]:
    dates: list[str] = []
    for path in sorted(HISTORY.glob("????-??-??.json"), reverse=True):
        try:
            data = load(path)
        except Exception:
            continue
        tickets = data.get("tickets") or []
        if not tickets:
            continue
        if any(str(ticket.get("status") or "PENDING").upper() in {"PENDING", "MANUAL"} for ticket in tickets):
            dates.append(str(data.get("board_date") or path.stem))
        if len(dates) >= max_dates:
            break
    return dates


def _needed_statistics_fixtures(
    tickets: list[dict[str, Any]],
    fixtures: dict[int, dict[str, Any]],
) -> set[int]:
    needed: set[int] = set()
    for ticket in tickets:
        for leg in ticket.get("legs") or []:
            if not _requires_stats(leg):
                continue
            if str(leg.get("status") or "PENDING").upper() not in {"PENDING", "MANUAL"}:
                continue
            try:
                fixture_id = int(leg.get("fixture_id"))
            except (TypeError, ValueError):
                continue
            fixture = fixtures.get(fixture_id)
            if not fixture:
                continue
            short = str((((fixture.get("fixture") or {}).get("status") or {}).get("short") or "")).upper()
            if short in FINAL_STATUSES:
                needed.add(fixture_id)
    return needed


def settle_date(client: ApiFootballClient, date: str) -> dict[str, Any] | None:
    path = HISTORY / f"{date}.json"
    if not path.exists():
        return None
    payload = load(path)
    fixtures = _fixture_map(client.fixtures_by_date(date))
    raw_tickets = list(payload.get("tickets") or [])

    stats_by_fixture: dict[int, dict[str, dict[str, float]]] = {}
    for fixture_id in sorted(_needed_statistics_fixtures(raw_tickets, fixtures)):
        try:
            rows = client.fixture_statistics(fixture_id)
        except ApiFootballError:
            rows = []
        if rows:
            stats_by_fixture[fixture_id] = _statistics_map(fixtures[fixture_id], rows)

    tickets = [settle_ticket(ticket, fixtures, stats_by_fixture) for ticket in raw_tickets]
    payload["tickets"] = tickets
    payload["approved"] = tickets
    payload["settlement"] = {
        "checked_at": now().isoformat(),
        "green": sum(1 for t in tickets if str(t.get("status") or "").upper() == "GREEN"),
        "red": sum(1 for t in tickets if str(t.get("status") or "").upper() == "RED"),
        "pending": sum(1 for t in tickets if str(t.get("status") or "").upper() in {"PENDING", "MANUAL"}),
        "complete": bool(tickets) and all(str(t.get("status") or "").upper() in {"GREEN", "RED", "VOID"} for t in tickets),
        "statistics_fixtures_checked": len(stats_by_fixture),
    }
    dump(path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle InvestBet football tickets and rebuild simulated bankrolls")
    parser.add_argument("--max-dates", type=int, default=3)
    args = parser.parse_args()

    key = _resolve_api_key()
    if not key:
        print("API-Football key not configured; management rebuilt without new settlement.")
        dump(DASHBOARD / "management.json", build_management())
        return 0

    client = ApiFootballClient(key)
    dates = pending_dates(max(1, min(args.max_dates, 7)))
    updated: dict[str, dict[str, Any]] = {}
    for date in dates:
        try:
            payload = settle_date(client, date)
        except ApiFootballError as exc:
            print(f"Settlement failed for {date}: {exc}")
            continue
        if payload:
            updated[date] = payload

    summary = history_summary()
    for date, payload in updated.items():
        payload["history_summary"] = summary
        dump(HISTORY / f"{date}.json", payload)

    current_path = DASHBOARD / "data.json"
    if current_path.exists():
        current = load(current_path)
        current_date = str(current.get("board_date") or "")
        if current_date in updated:
            refreshed = updated[current_date]
            refreshed["history_summary"] = summary
            dump(current_path, refreshed)
        else:
            current["history_summary"] = summary
            dump(current_path, current)

    management = build_management()
    dump(DASHBOARD / "management.json", management)
    print(f"Settlement checked {len(dates)} date(s); API requests={client.request_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
