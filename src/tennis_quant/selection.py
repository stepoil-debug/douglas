from __future__ import annotations

from datetime import datetime, timedelta

from tennis_quant.domain import Candidate


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def rejection_reasons(candidate: Candidate, cfg: dict) -> list[str]:
    reasons: list[str] = []
    s = cfg["selection"]
    odd = candidate.selected_market.best_odd
    if odd is None or not (s["min_odd"] <= odd <= s["max_odd"]):
        reasons.append("ODD_OUT_OF_RANGE")
    if candidate.final_probability < s["min_final_probability"]:
        reasons.append("PROBABILITY_TOO_LOW")
    if candidate.edge_pp < s["min_edge_pp"]:
        reasons.append("EDGE_TOO_LOW")
    if candidate.confidence < s["min_confidence"]:
        reasons.append("CONFIDENCE_TOO_LOW")
    if candidate.disagreement_pp > s["max_disagreement_pp"]:
        reasons.append("MODEL_DISAGREEMENT")
    if candidate.data_quality < float(s.get("min_data_quality", 0.0)):
        reasons.append("DATA_QUALITY_TOO_LOW")
    if not bool(s.get("allow_qualification", False)) and _truthy(candidate.match.raw.get("event_qualification")):
        reasons.append("QUALIFICATION_MATCH")
    return reasons


def _quality_key(candidate: Candidate) -> tuple[float, float, float, float, int]:
    return (
        float(candidate.confidence),
        float(candidate.data_quality),
        float(candidate.edge_pp),
        float(candidate.final_probability),
        int(candidate.selected_market.bookmakers),
    )


def _quality_value(candidate: Candidate) -> float:
    """Scalar used only to optimize the operational sequence among already eligible picks."""
    edge = max(-5.0, min(15.0, float(candidate.edge_pp)))
    books = min(10, max(0, int(candidate.selected_market.bookmakers)))
    return (
        float(candidate.confidence)
        + 20.0 * float(candidate.data_quality)
        + 20.0 * float(candidate.final_probability)
        + 0.30 * edge
        + 0.50 * books
    )


def _scheduled_start(candidate: Candidate) -> datetime | None:
    day = str(candidate.match.date or "").strip()
    raw_time = str(candidate.match.time or "").strip()
    if not day or not raw_time:
        return None
    # Live boards use HH:MM. Accept HH:MM:SS defensively.
    clock = raw_time[:5]
    try:
        return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _best_spaced_sequence(
    eligible: list[Candidate],
    max_approved: int,
    min_gap_minutes: int,
    require_known_time: bool,
) -> list[Candidate]:
    if max_approved <= 0:
        return []

    timed: list[tuple[datetime, Candidate]] = []
    untimed: list[Candidate] = []
    for candidate in eligible:
        start = _scheduled_start(candidate)
        if start is None:
            untimed.append(candidate)
        else:
            timed.append((start, candidate))

    timed.sort(key=lambda row: (row[0], -_quality_value(row[1])))
    if not timed:
        if require_known_time:
            return []
        return sorted(untimed, key=_quality_key, reverse=True)[:1]

    gap = timedelta(minutes=max(0, int(min_gap_minutes)))
    n = len(timed)
    starts = [row[0] for row in timed]
    previous: list[int] = []
    for i, start in enumerate(starts):
        j = i - 1
        while j >= 0 and start - starts[j] < gap:
            j -= 1
        previous.append(j)

    cap = min(max_approved, n)
    dp = [[0.0] * (cap + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        weight = _quality_value(timed[i - 1][1])
        prev_row = previous[i - 1] + 1
        for k in range(1, cap + 1):
            skip = dp[i - 1][k]
            take = weight + dp[prev_row][k - 1]
            dp[i][k] = max(skip, take)

    best_k = max(range(cap + 1), key=lambda k: dp[n][k])
    chosen: list[Candidate] = []
    i, k = n, best_k
    while i > 0 and k > 0:
        weight = _quality_value(timed[i - 1][1])
        prev_row = previous[i - 1] + 1
        take = weight + dp[prev_row][k - 1]
        skip = dp[i - 1][k]
        if take > skip + 1e-9:
            chosen.append(timed[i - 1][1])
            i = prev_row
            k -= 1
        else:
            i -= 1

    chosen.reverse()
    return chosen[:max_approved]


def rank_candidates(candidates: list[Candidate], cfg: dict) -> list[Candidate]:
    s = cfg["selection"]
    for candidate in candidates:
        candidate.rank = None
        candidate.status = "REJECTED"
        candidate.reject_reasons = rejection_reasons(candidate, cfg)

    eligible = [c for c in candidates if not c.reject_reasons]
    eligible_by_quality = sorted(eligible, key=_quality_key, reverse=True)

    max_approved = int(s["max_approved"])
    shadow_size = int(s.get("shadow_size", 10))
    min_gap = int(s.get("min_entry_gap_minutes", 210))
    require_known_time = bool(s.get("require_known_start_time", True))

    approved = _best_spaced_sequence(
        eligible_by_quality,
        max_approved=max_approved,
        min_gap_minutes=min_gap,
        require_known_time=require_known_time,
    )
    approved_ids = {id(c) for c in approved}
    approved.sort(key=lambda c: (_scheduled_start(c) or datetime.max, -_quality_value(c)))
    approved_starts = [s for c in approved if (s := _scheduled_start(c)) is not None]

    for idx, candidate in enumerate(approved, 1):
        candidate.rank = idx  # Operational entry order, not merely score rank.
        candidate.status = "APPROVED"
        candidate.reject_reasons = []

    alternatives: list[Candidate] = []
    for candidate in eligible_by_quality:
        if id(candidate) in approved_ids:
            continue
        start = _scheduled_start(candidate)
        if start is None and require_known_time:
            candidate.reject_reasons = ["START_TIME_UNCONFIRMED"]
        elif start is not None and any(abs(start - selected) < timedelta(minutes=min_gap) for selected in approved_starts):
            candidate.reject_reasons = ["TIME_WINDOW_CONFLICT"]
        else:
            candidate.reject_reasons = ["BELOW_TOP_CUTOFF"]
        alternatives.append(candidate)

    for idx, candidate in enumerate(alternatives):
        if idx < shadow_size:
            candidate.status = "SHADOW"
        else:
            candidate.status = "REJECTED"

    approved_set = {id(c) for c in approved}
    shadow_set = {id(c) for c in alternatives[:shadow_size]}
    return sorted(
        candidates,
        key=lambda c: (
            0 if id(c) in approved_set else 1 if id(c) in shadow_set else 2,
            c.rank if c.rank is not None else 999999,
            -float(c.confidence),
        ),
    )
