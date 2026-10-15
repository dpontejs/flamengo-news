import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from dateutil.parser import isoparse

from flanews.collectors.base import DEFAULT_TIMEOUT
from flanews.models import MatchEvent, MatchStats, NextMatch, StandingRow

logger = logging.getLogger(__name__)

ESPN_SITE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/soccer"
# ESPN's WAF rejects the collectors' User-Agent (the "(+contato@...)" part) with 403.
ESPN_USER_AGENT = "flanews/0.1"

LEAGUES = {
    "bra.1": "Brasileirão",
    "conmebol.libertadores": "Libertadores",
    "bra.copa_do_brazil": "Copa do Brasil",
}

# ESPN stat name -> pt-BR label, in display order.
STAT_LABELS = {
    "possessionPct": "Posse de bola",
    "totalShots": "Finalizações",
    "shotsOnTarget": "Finalizações no gol",
    "wonCorners": "Escanteios",
    "foulsCommitted": "Faltas",
    "offsides": "Impedimentos",
    "saves": "Defesas",
    "totalPasses": "Passes",
    "accuratePasses": "Passes certos",
    "yellowCards": "Cartões amarelos",
    "redCards": "Cartões vermelhos",
}

EVENT_TYPES = {
    "yellow-card": "yellow_card",
    "red-card": "red_card",
    "substitution": "substitution",
}

CLOCK_PATTERN = re.compile(r"(\d+)'(?:\+(\d+))?")


class ESPNStatsClient:
    """Match data for Flamengo from ESPN's public (undocumented) API.

    Every public method degrades to None/[] on network or format errors, so the
    newsletter can still be sent without the stats section.
    """

    def __init__(
        self,
        team_id: int = 819,
        client: httpx.Client | None = None,
        tz_name: str = "America/Sao_Paulo",
    ) -> None:
        self.team_id = str(team_id)
        self._client = client or httpx.Client(
            headers={"User-Agent": ESPN_USER_AGENT}, timeout=DEFAULT_TIMEOUT
        )
        self.tz = ZoneInfo(tz_name)

    def get_last_match(self, start: datetime, end: datetime) -> MatchStats | None:
        """Most recent completed match whose kickoff falls in [start, end]."""
        candidates: list[tuple[datetime, str, dict]] = []
        for league in LEAGUES:
            for event in self._schedule(league, {"season": str(end.year)}):
                competition = event["competitions"][0]
                kickoff = isoparse(event["date"])
                if competition["status"]["type"]["completed"] and start <= kickoff <= end:
                    candidates.append((kickoff, league, event))
        if not candidates:
            return None

        _, league, event = max(candidates, key=lambda c: c[0])
        try:
            summary = self._get(f"{ESPN_SITE_URL}/{league}/summary", {"event": event["id"]})
            return self._parse_match(summary, league)
        except Exception as e:
            logger.warning("Failed to load ESPN match %s: %s", event["id"], e)
            return None

    def get_next_match(self, now: datetime) -> NextMatch | None:
        """Earliest scheduled match after `now` in any tracked competition."""
        upcoming: list[tuple[datetime, str, dict]] = []
        for league in LEAGUES:
            for event in self._schedule(league, {"fixture": "true"}):
                kickoff = isoparse(event["date"])
                if kickoff > now:
                    upcoming.append((kickoff, league, event))
        if not upcoming:
            return None

        kickoff, league, event = min(upcoming, key=lambda u: u[0])
        competition = event["competitions"][0]
        ours = next(c for c in competition["competitors"] if c["team"]["id"] == self.team_id)
        theirs = next(c for c in competition["competitors"] if c is not ours)
        return NextMatch(
            opponent=theirs["team"]["displayName"],
            competition=LEAGUES[league],
            date=kickoff.astimezone(self.tz),
            venue=(competition.get("venue") or {}).get("fullName"),
            is_home=ours["homeAway"] == "home",
            opponent_logo=_logo(theirs["team"]),
        )

    def get_standings(self, league: str = "bra.1") -> list[StandingRow]:
        """League table; for group competitions only Flamengo's group."""
        try:
            data = self._get(f"{ESPN_STANDINGS_URL}/{league}/standings")
            groups = [child["standings"]["entries"] for child in data.get("children", [])]
            entries = next(
                (g for g in groups if any(e["team"]["id"] == self.team_id for e in g)), []
            )
            rows = [self._parse_standing(entry) for entry in entries]
        except Exception as e:
            logger.warning("Failed to load ESPN standings for %s: %s", league, e)
            return []
        return sorted(rows, key=lambda r: r.position)

    def _get(self, url: str, params: dict[str, str] | None = None) -> dict:
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _schedule(self, league: str, params: dict[str, str]) -> list[dict]:
        url = f"{ESPN_SITE_URL}/{league}/teams/{self.team_id}/schedule"
        try:
            return self._get(url, params).get("events", [])
        except Exception as e:
            logger.warning("Failed to load ESPN schedule for %s: %s", league, e)
            return []

    def _parse_match(self, summary: dict, league: str) -> MatchStats:
        header = summary["header"]["competitions"][0]
        sides = {c["homeAway"]: c for c in header["competitors"]}
        home, away = sides["home"], sides["away"]

        stats_by_team = {
            team["team"]["id"]: {s["name"]: s["displayValue"] for s in team["statistics"]}
            for team in summary["boxscore"]["teams"]
        }
        home_stats = stats_by_team.get(home["team"]["id"], {})
        away_stats = stats_by_team.get(away["team"]["id"], {})
        statistics = {
            label: (_format_stat(name, home_stats[name]), _format_stat(name, away_stats[name]))
            for name, label in STAT_LABELS.items()
            if name in home_stats and name in away_stats
        }

        lineups = {
            roster["team"]["displayName"]: [
                player["athlete"]["displayName"]
                for player in roster.get("roster", [])
                if player.get("starter")
            ]
            for roster in summary.get("rosters", [])
        }

        return MatchStats(
            fixture_id=int(summary["header"]["id"]),
            competition=LEAGUES[league],
            date=isoparse(header["date"]).astimezone(self.tz),
            home=home["team"]["displayName"],
            away=away["team"]["displayName"],
            home_goals=int(home["score"]),
            away_goals=int(away["score"]),
            venue=(summary.get("gameInfo", {}).get("venue") or {}).get("fullName"),
            home_logo=_logo(home["team"]),
            away_logo=_logo(away["team"]),
            events=[e for e in map(_parse_event, summary.get("keyEvents", [])) if e],
            statistics=statistics,
            lineups=lineups,
        )

    def _parse_standing(self, entry: dict) -> StandingRow:
        stats = {s["name"]: s.get("value") for s in entry["stats"]}
        return StandingRow(
            position=int(stats["rank"]),
            team=entry["team"]["displayName"],
            points=int(stats["points"]),
            played=int(stats["gamesPlayed"]),
            won=int(stats["wins"]),
            drawn=int(stats["ties"]),
            lost=int(stats["losses"]),
            goals_diff=int(stats["pointDifferential"]),
            is_flamengo=entry["team"]["id"] == self.team_id,
        )


def _logo(team: dict) -> str | None:
    """First crest URL ESPN publishes for the team (schedule uses `logos`, others `logo`)."""
    logos = team.get("logos") or []
    if logos:
        return logos[0].get("href")
    return team.get("logo")


def _format_stat(name: str, value: str) -> str:
    return f"{value}%" if name == "possessionPct" else value


def _parse_event(event: dict) -> MatchEvent | None:
    """Convert an ESPN key event into a MatchEvent; other event kinds are skipped."""
    if event.get("scoringPlay"):
        kind = "goal"
    else:
        kind = EVENT_TYPES.get(event["type"].get("type", ""))
    if kind is None or not event.get("participants"):
        return None

    clock = CLOCK_PATTERN.match(event.get("clock", {}).get("displayValue", ""))
    if clock is None:
        return None
    names = [p["athlete"]["displayName"] for p in event["participants"]]

    detail = None
    if kind == "goal":
        label = event["type"]["text"]
        detail = f"Assistência: {names[1]}" if len(names) > 1 else None
        if label != "Goal":
            detail = label if detail is None else f"{label}; {detail}"
    elif kind == "substitution" and len(names) > 1:
        detail = f"Saiu: {names[1]}"

    return MatchEvent(
        minute=int(clock.group(1)),
        extra_minute=int(clock.group(2)) if clock.group(2) else None,
        team=event["team"]["displayName"],
        player=names[0],
        type=kind,
        detail=detail,
    )
