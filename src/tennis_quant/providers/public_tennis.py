from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from tennis_quant.domain import Match, Player

SACKMANN_URL = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def player_aliases(full_name: str) -> set[str]:
    words = _norm(full_name).split()
    if len(words) < 2:
        return {_norm(full_name)}
    first_initial = words[0][0]
    aliases = {_norm(full_name)}
    for width in range(1, min(4, len(words) - 1) + 1):
        surname = " ".join(words[-width:])
        aliases.add(f"{surname} {first_initial}")
    return aliases


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _stable_match_id(record: dict[str, Any]) -> str:
    raw = str(record.get("match_link") or "").strip()
    if not raw:
        raw = "|".join(
            str(record.get(k) or "")
            for k in ("match_date", "league_name", "home_team", "away_team")
        )
    return "oh-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def odds_home_away(record: dict[str, Any]) -> dict[str, Any]:
    home: dict[str, float] = {}
    away: dict[str, float] = {}
    rows = record.get("match_winner_market", []) or []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        blocked = {str(x) for x in (row.get("blocked_outcomes") or [])}
        book = str(row.get("bookmaker_name") or f"book-{idx + 1}")
        try:
            p1 = float(row.get("player_1"))
            p2 = float(row.get("player_2"))
        except (TypeError, ValueError):
            continue
        if p1 > 1 and "player_1" not in blocked:
            home[book] = p1
        if p2 > 1 and "player_2" not in blocked:
            away[book] = p2
    return {"Home/Away": {"Home": home, "Away": away}}


def _score_winner(record: dict[str, Any]) -> str | None:
    try:
        home = int(str(record.get("home_score") or "").strip())
        away = int(str(record.get("away_score") or "").strip())
    except ValueError:
        return None
    if home > away:
        return "First Player"
    if away > home:
        return "Second Player"
    return None


def _set_count_from_score(score: Any) -> str | None:
    text = str(score or "").strip()
    if not text:
        return None
    left = right = 0
    for token in text.split():
        token = token.strip().replace("RET", "").replace("W/O", "")
        match = re.match(r"^(\d+)-(\d+)", token)
        if not match:
            continue
        a, b = int(match.group(1)), int(match.group(2))
        if a > b:
            left += 1
        elif b > a:
            right += 1
    if left + right == 0:
        return None
    return f"{left} - {right}"


class SackmannStore:
    """Static-file ATP history. No API key and no sports API is required."""

    def __init__(self, root: Path, session: requests.Session | None = None):
        self.root = root
        self.cache_dir = root / "data" / "cache" / "sackmann"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.rows_by_year: dict[int, list[dict[str, str]]] = {}
        self.players: dict[str, str] = {}
        self.alias_to_ids: dict[str, set[str]] = defaultdict(set)
        self.latest_rank: dict[str, dict[str, Any]] = {}
        self._profiles: dict[str, dict[str, Any]] = {}

    def _path(self, year: int) -> Path:
        return self.cache_dir / f"atp_matches_{year}.csv"

    def ensure_year(self, year: int) -> list[dict[str, str]]:
        if year in self.rows_by_year:
            return self.rows_by_year[year]
        path = self._path(year)
        refresh = year == date.today().year
        if not path.exists() or refresh:
            response = self.session.get(SACKMANN_URL.format(year=year), timeout=60)
            if response.status_code == 404:
                self.rows_by_year[year] = []
                return []
            response.raise_for_status()
            path.write_bytes(response.content)
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.rows_by_year[year] = rows
        self._index_rows(rows)
        return rows

    def ensure_window(self, start: date, end: date) -> None:
        for year in range(start.year, end.year + 1):
            self.ensure_year(year)

    def _index_rows(self, rows: list[dict[str, str]]) -> None:
        for row in rows:
            tourney_date = str(row.get("tourney_date") or "")
            for side in ("winner", "loser"):
                pid = str(row.get(f"{side}_id") or "").strip()
                name = str(row.get(f"{side}_name") or "").strip()
                if not pid or not name:
                    continue
                self.players[pid] = name
                for alias in player_aliases(name):
                    self.alias_to_ids[alias].add(pid)
                try:
                    place = int(float(row.get(f"{side}_rank") or 0))
                except (TypeError, ValueError):
                    place = 0
                try:
                    points = int(float(row.get(f"{side}_rank_points") or 0))
                except (TypeError, ValueError):
                    points = 0
                current = self.latest_rank.get(pid)
                if place > 0 and (not current or tourney_date >= current.get("date", "")):
                    self.latest_rank[pid] = {"place": place, "points": points, "date": tourney_date}

    def resolve_player(self, display_name: str) -> Player:
        target = _norm(display_name)
        ids = self.alias_to_ids.get(target, set())
        if len(ids) == 1:
            pid = next(iter(ids))
            return Player(pid, self.players.get(pid, display_name))

        target_words = target.split()
        initial = target_words[-1][:1] if len(target_words) > 1 else ""
        candidates: list[tuple[float, str]] = []
        for alias, alias_ids in self.alias_to_ids.items():
            if initial and not alias.endswith(" " + initial):
                continue
            ratio = SequenceMatcher(None, target, alias).ratio()
            if ratio >= 0.82:
                for pid in alias_ids:
                    candidates.append((ratio, pid))
        candidates.sort(reverse=True)
        if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0] + 0.03):
            pid = candidates[0][1]
            return Player(pid, self.players.get(pid, display_name))

        fallback = "name-" + hashlib.sha1(target.encode("utf-8")).hexdigest()[:14]
        return Player(fallback, display_name)

    @staticmethod
    def _row_date(row: dict[str, str]) -> date | None:
        raw = str(row.get("tourney_date") or "")
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None

    def rows_between(self, start: date, end: date) -> list[dict[str, str]]:
        self.ensure_window(start, end)
        output: list[dict[str, str]] = []
        for year in range(start.year, end.year + 1):
            for row in self.rows_by_year.get(year, []):
                d = self._row_date(row)
                if d and start <= d <= end:
                    output.append(row)
        return output

    def _stats_for_side(self, row: dict[str, str], prefix: str, player_key: str) -> list[dict[str, Any]]:
        def pair(name: str, won_col: str, total_col: str) -> dict[str, Any] | None:
            try:
                won = float(row.get(won_col) or 0)
                total = float(row.get(total_col) or 0)
            except (TypeError, ValueError):
                return None
            if total <= 0:
                return None
            return {"player_key": player_key, "stat_name": name, "stat_won": won, "stat_total": total}

        svpt = f"{prefix}_svpt"
        first_in = f"{prefix}_1stIn"
        rows = [
            pair("1st Serve Points Won", f"{prefix}_1stWon", first_in),
            pair("2nd Serve Points Won", f"{prefix}_2ndWon", svpt),
            pair("Break Points Saved", f"{prefix}_bpSaved", f"{prefix}_bpFaced"),
        ]
        try:
            first_won = float(row.get(f"{prefix}_1stWon") or 0)
            second_won = float(row.get(f"{prefix}_2ndWon") or 0)
            total = float(row.get(svpt) or 0)
            if total > 0:
                rows.append({"player_key": player_key, "stat_name": "Service Points Won", "stat_won": first_won + second_won, "stat_total": total})
        except (TypeError, ValueError):
            pass
        return [x for x in rows if x]

    def row_to_match(self, row: dict[str, str]) -> Match:
        winner_key = str(row.get("winner_id") or "")
        loser_key = str(row.get("loser_id") or "")
        winner = Player(winner_key, str(row.get("winner_name") or "Winner"))
        loser = Player(loser_key, str(row.get("loser_name") or "Loser"))
        d = self._row_date(row) or date.today()
        match_num = str(row.get("match_num") or "0")
        tournament = str(row.get("tourney_name") or row.get("tourney_id") or "ATP")
        match_id = "js-" + hashlib.sha1(
            f"{row.get('tourney_id')}|{match_num}|{winner_key}|{loser_key}".encode("utf-8")
        ).hexdigest()[:20]
        stats = self._stats_for_side(row, "w", winner_key) + self._stats_for_side(row, "l", loser_key)
        return Match(
            match_id=match_id,
            date=d.isoformat(),
            time=match_num.zfill(5),
            tournament=tournament,
            event_type="ATP Singles",
            surface=str(row.get("surface") or "") or None,
            player_a=winner,
            player_b=loser,
            status="Finished",
            winner="First Player",
            raw={
                "event_key": match_id,
                "event_date": d.isoformat(),
                "event_final_result": _set_count_from_score(row.get("score")),
                "event_winner": "First Player",
                "first_player_key": winner_key,
                "second_player_key": loser_key,
                "statistics": stats,
                "source": "JeffSackmann/tennis_atp",
            },
        )

    def matches_between(self, start: date, end: date) -> list[Match]:
        return [self.row_to_match(row) for row in self.rows_between(start, end)]

    def player_history(self, player_key: str, start: date, end: date) -> list[Match]:
        matches: list[Match] = []
        for row in self.rows_between(start, end):
            if player_key in {str(row.get("winner_id") or ""), str(row.get("loser_id") or "")}:
                matches.append(self.row_to_match(row))
        return matches

    def h2h(self, a: str, b: str, today: date) -> dict[str, Any]:
        start = today.replace(year=max(1968, today.year - 3))
        rows = self.rows_between(start, today)
        h2h: list[dict[str, Any]] = []
        first: list[dict[str, Any]] = []
        second: list[dict[str, Any]] = []
        for row in reversed(rows):
            match = self.row_to_match(row)
            raw = match.raw
            keys = {match.player_a.key, match.player_b.key}
            if a in keys:
                first.append(raw)
            if b in keys:
                second.append(raw)
            if a in keys and b in keys:
                h2h.append(raw)
        return {"H2H": h2h[:10], "firstPlayerResults": first[:16], "secondPlayerResults": second[:16]}

    def standings(self) -> dict[str, dict[str, Any]]:
        return {pid: {"place": row.get("place"), "points": row.get("points")} for pid, row in self.latest_rank.items()}

    def player_profile(self, player_key: str, year: int) -> dict[str, Any]:
        cache_key = f"{player_key}:{year}"
        if cache_key in self._profiles:
            return self._profiles[cache_key]
        rows = self.ensure_year(year)
        counters: dict[str, int] = defaultdict(int)
        for row in rows:
            winner = str(row.get("winner_id") or "") == player_key
            loser = str(row.get("loser_id") or "") == player_key
            if not (winner or loser):
                continue
            outcome = "won" if winner else "lost"
            counters[f"matches_{outcome}"] += 1
            surface = _norm(row.get("surface"))
            if surface in {"hard", "clay", "grass"}:
                counters[f"{surface}_{outcome}"] += 1
        stats = {
            "type": "Singles",
            "season": str(year),
            "matches_won": counters["matches_won"],
            "matches_lost": counters["matches_lost"],
            "hard_won": counters["hard_won"], "hard_lost": counters["hard_lost"],
            "clay_won": counters["clay_won"], "clay_lost": counters["clay_lost"],
            "grass_won": counters["grass_won"], "grass_lost": counters["grass_lost"],
        }
        payload = {"stats": [stats]}
        self._profiles[cache_key] = payload
        return payload

    def surface_for_tournament(self, league_name: str, year: int) -> str | None:
        rows = self.ensure_year(year)
        target = _norm(re.sub(r"\b(atp|wta|20\d{2})\b", " ", league_name, flags=re.I))
        best: tuple[float, str] | None = None
        for row in rows:
            surface = str(row.get("surface") or "").strip()
            name = _norm(row.get("tourney_name"))
            if not surface or not name:
                continue
            score = SequenceMatcher(None, target, name).ratio()
            if target in name or name in target:
                score += 0.25
            if best is None or score > best[0]:
                best = (score, surface)
        return best[1] if best and best[0] >= 0.58 else None


class PublicTennisProvider:
    """OddsPortal via OddsHarvester + Jeff Sackmann static CSV history."""

    history_source_id = "jeff-sackmann-v1"

    def __init__(self, root: Path):
        self.root = root
        self.sackmann = SackmannStore(root)
        self._day_cache: dict[str, tuple[list[Match], dict[str, Any]]] = {}
        self.source_requests = 0
        self.current_context_date = date.today()

    def _run_scraper(self, target_date: date) -> list[dict[str, Any]]:
        runtime = self.root / "data" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        output = runtime / f"oddsharvester_{target_date.isoformat()}.json"
        if output.exists():
            output.unlink()
        cmd = [
            "oddsharvester", "upcoming",
            "-s", "tennis",
            "-d", target_date.strftime("%Y%m%d"),
            "-m", "match_winner",
            "--headless",
            "--include-started",
            "--timezone", "America/Sao_Paulo",
            "--bookies-filter", "classic",
            "--concurrency", "2",
            "--request-delay", "1.2",
            "-f", "json",
            "-o", str(output),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        self.source_requests += 1
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "unknown OddsHarvester failure")[-1200:]
            raise RuntimeError(f"OddsHarvester failed: {tail}")
        candidates = [output, output.with_suffix(output.suffix + ".json"), Path(str(output) + ".json")]
        actual = next((p for p in candidates if p.exists()), None)
        if not actual:
            return []
        payload = json.loads(actual.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("data", "results", "matches"):
                if isinstance(payload.get(key), list):
                    return payload[key]
            return [payload]
        return payload if isinstance(payload, list) else []

    def _load_day(self, target_date: date) -> tuple[list[Match], dict[str, Any]]:
        key = target_date.isoformat()
        if key in self._day_cache:
            return self._day_cache[key]
        self.current_context_date = target_date
        self.sackmann.ensure_window(date(max(1968, target_date.year - 1), 1, 1), target_date)
        records = self._run_scraper(target_date)
        matches: list[Match] = []
        odds: dict[str, Any] = {}
        now = datetime.now(timezone.utc)
        for record in records:
            if not isinstance(record, dict):
                continue
            league = str(record.get("league_name") or "")
            league_norm = _norm(league)
            if "atp" not in league_norm or any(token in league_norm for token in ("wta", "challenger", "itf", "doubles")):
                continue
            home_name = str(record.get("home_team") or "").strip()
            away_name = str(record.get("away_team") or "").strip()
            if not home_name or not away_name:
                continue
            player_a = self.sackmann.resolve_player(home_name)
            player_b = self.sackmann.resolve_player(away_name)
            kickoff = _parse_utc(record.get("match_date"))
            local = kickoff.astimezone(SAO_PAULO) if kickoff else None
            winner = _score_winner(record)
            status = ""
            if winner:
                status = "Finished"
            elif kickoff and kickoff <= now:
                status = "Started"
            match_id = _stable_match_id(record)
            surface = self.sackmann.surface_for_tournament(league, target_date.year)
            match = Match(
                match_id=match_id,
                date=(local.date().isoformat() if local else target_date.isoformat()),
                time=(local.strftime("%H:%M") if local else ""),
                tournament=league or "ATP",
                event_type="ATP Singles",
                surface=surface,
                player_a=player_a,
                player_b=player_b,
                status=status,
                winner=winner,
                raw={
                    "event_key": match_id,
                    "event_date": (local.date().isoformat() if local else target_date.isoformat()),
                    "event_final_result": (
                        f"{record.get('home_score')} - {record.get('away_score')}" if winner else None
                    ),
                    "event_winner": winner,
                    "first_player_key": player_a.key,
                    "second_player_key": player_b.key,
                    "source": "OddsHarvester/OddsPortal",
                    "source_url": record.get("match_link"),
                },
            )
            matches.append(match)
            odds[match_id] = odds_home_away(record)
        self._day_cache[key] = (matches, odds)
        return matches, odds

    def fixtures(self, target_date: date) -> list[Match]:
        return self._load_day(target_date)[0]

    def odds(self, target_date: date) -> dict[str, Any]:
        return self._load_day(target_date)[1]

    def fixtures_range(self, start: date, end: date) -> list[Match]:
        return self.sackmann.matches_between(start, end)

    def standings(self, tour: str = "ATP") -> dict[str, dict[str, Any]]:
        return self.sackmann.standings()

    def h2h(self, player_a_key: str, player_b_key: str) -> dict[str, Any]:
        return self.sackmann.h2h(player_a_key, player_b_key, self.current_context_date)

    def player_profile(self, player_key: str) -> dict[str, Any]:
        return self.sackmann.player_profile(player_key, self.current_context_date.year)

    def player_history(self, player_key: str, start: date, end: date) -> list[Match]:
        matches = self.sackmann.player_history(player_key, start, end)
        matches.sort(key=lambda m: (m.date, m.time), reverse=True)
        return matches
