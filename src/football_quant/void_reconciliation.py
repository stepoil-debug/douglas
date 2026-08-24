from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

from .settlement import DASHBOARD, HISTORY, TZ, build_management, dump, load, now

# Betano football same-day rule: postponed/cancelled/interrupted events that are
# not completed on the originally scheduled day are void. In a multiple, the
# void leg is neutral (odd 1.00) and the remaining legs continue.
PAST_DAY_VOID_STATUSES = {"PST", "CANC", "ABD", "INT", "SUSP"}
FINAL_TICKET_STATUSES = {"GREEN", "RED", "VOID"}


def _board_date(payload: dict[str, Any], path: Path) -> date | None:
    raw = str(payload.get("board_date") or path.stem)
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _should_void_past_leg(leg: dict[str, Any]) -> bool:
    status = str(leg.get("status") or "PENDING").upper()
    if status != "PENDING":
        return False

    fixture_status = str(leg.get("fixture_status") or "").upper()
    if fixture_status in PAST_DAY_VOID_STATUSES:
        return True

    # When the fixture disappears from the original-date endpoint after the day
    # has passed, it has not been completed on the scheduled day. This matches
    # the same-day void rule used by the simulated Betano settlement.
    reason = str(leg.get("result_reason") or "").casefold()
    return "não localizada" in reason or "nao localizada" in reason


def _recalculate_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    result = dict(ticket)
    legs = [dict(leg) for leg in ticket.get("legs") or []]
    result["legs"] = legs
    statuses = [str(leg.get("status") or "PENDING").upper() for leg in legs]

    if any(status == "RED" for status in statuses):
        result["status"] = "RED"
    elif any(status in {"PENDING", "MANUAL"} for status in statuses):
        result["status"] = "PENDING" if any(status == "PENDING" for status in statuses) else "MANUAL"
    elif statuses and all(status in {"GREEN", "VOID"} for status in statuses):
        result["status"] = "GREEN" if any(status == "GREEN" for status in statuses) else "VOID"
    else:
        result["status"] = "PENDING"

    if result["status"] in FINAL_TICKET_STATUSES:
        original_odd = float(result.get("original_total_odd") or result.get("total_odd") or 1.0)
        result.setdefault("original_total_odd", round(original_odd, 2))

        if result["status"] == "GREEN":
            effective = math.prod(
                1.0 if str(leg.get("status") or "").upper() == "VOID" else float(leg.get("odd") or 1.0)
                for leg in legs
            )
            effective = round(effective, 2)
            result["settled_total_odd"] = effective
            result["total_odd"] = effective
        elif result["status"] == "VOID":
            result["settled_total_odd"] = 1.0
            result["total_odd"] = 1.0

        result["settled_at"] = now().isoformat()
    return result


def reconcile_history() -> tuple[int, int]:
    today = now().date()
    changed_days = 0
    voided_legs = 0

    for path in sorted(HISTORY.glob("????-??-??.json")):
        try:
            payload = load(path)
        except Exception:
            continue

        board_day = _board_date(payload, path)
        if board_day is None or board_day >= today:
            continue

        changed = False
        tickets: list[dict[str, Any]] = []
        for ticket in payload.get("tickets") or []:
            ticket_copy = dict(ticket)
            legs: list[dict[str, Any]] = []
            ticket_changed = False

            for raw_leg in ticket.get("legs") or []:
                leg = dict(raw_leg)
                if _should_void_past_leg(leg):
                    leg["status"] = "VOID"
                    leg["settled_at"] = now().isoformat()
                    leg["settlement_void_rule"] = "BETANO_SAME_DAY"
                    fixture_status = str(leg.get("fixture_status") or "sem status")
                    leg["result_reason"] = (
                        f"VOID: partida não concluída no dia originalmente programado "
                        f"({fixture_status}); seleção neutralizada com odd 1,00."
                    )
                    voided_legs += 1
                    ticket_changed = True
                legs.append(leg)

            ticket_copy["legs"] = legs
            if ticket_changed:
                ticket_copy = _recalculate_ticket(ticket_copy)
                changed = True
            tickets.append(ticket_copy)

        if not changed:
            continue

        payload["tickets"] = tickets
        payload["approved"] = tickets
        payload["settlement"] = {
            **(payload.get("settlement") or {}),
            "checked_at": now().isoformat(),
            "green": sum(1 for t in tickets if str(t.get("status") or "").upper() == "GREEN"),
            "red": sum(1 for t in tickets if str(t.get("status") or "").upper() == "RED"),
            "void": sum(1 for t in tickets if str(t.get("status") or "").upper() == "VOID"),
            "pending": sum(1 for t in tickets if str(t.get("status") or "").upper() in {"PENDING", "MANUAL"}),
            "complete": bool(tickets) and all(str(t.get("status") or "").upper() in FINAL_TICKET_STATUSES for t in tickets),
            "void_rule": "BETANO_SAME_DAY",
        }
        dump(path, payload)
        changed_days += 1

    # Keep the dashboard current board untouched unless it is one of the days
    # reconciled above. The management simulation is always rebuilt from history.
    dump(DASHBOARD / "management.json", build_management())
    return changed_days, voided_legs


def main() -> int:
    changed_days, voided_legs = reconcile_history()
    print(f"Void reconciliation: changed_days={changed_days}; voided_legs={voided_legs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
