"""Bolão: score bets on Flamengo's matches, kept next to the subscribers in the same SQLite.

Scores are always from Flamengo's side (Flamengo goals, opponent goals). Points are computed when
read, never stored, so a result sent twice cannot count twice.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flanews.models import BolaoSummary, RankRow
from flanews.web.store import normalize

TZ = ZoneInfo("America/Sao_Paulo")
TOP = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS bolao_matches (
    match_id TEXT PRIMARY KEY,
    opponent TEXT NOT NULL,
    flamengo_home INTEGER NOT NULL,
    kickoff TEXT NOT NULL,
    fla_goals INTEGER,
    opp_goals INTEGER
);
CREATE TABLE IF NOT EXISTS bolao_bets (
    email TEXT NOT NULL,
    match_id TEXT NOT NULL,
    fla_goals INTEGER NOT NULL,
    opp_goals INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (email, match_id)
);
CREATE TABLE IF NOT EXISTS bolao_players (
    email TEXT PRIMARY KEY,
    nickname TEXT NOT NULL UNIQUE COLLATE NOCASE
);
"""

Score = tuple[int, int]


@dataclass(frozen=True)
class BolaoMatch:
    match_id: str
    opponent: str
    flamengo_home: bool
    kickoff: datetime
    fla_goals: int | None
    opp_goals: int | None

    @property
    def result(self) -> Score | None:
        return None if self.fla_goals is None else (self.fla_goals, self.opp_goals)


def _outcome(score: Score) -> int:
    return (score[0] > score[1]) - (score[0] < score[1])


def points(bet: Score, result: Score) -> int:
    """Exact 5; right winner and goal difference 3; right outcome 2 (a wrong draw too); else 0."""
    if bet == result:
        return 5
    if _outcome(bet) != _outcome(result):
        return 0
    if _outcome(result) != 0 and bet[0] - bet[1] == result[0] - result[1]:
        return 3
    return 2


def _unique_best(scored: list[tuple[tuple, str]]) -> str | None:
    """The name with the highest key, or None when nobody or more than one has it."""
    if not scored:
        return None
    best = max(key for key, _ in scored)
    names = [name for key, name in scored if key == best]
    return names[0] if len(names) == 1 else None


class BolaoStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(SCHEMA)

    def _run(self, sql: str, *params: object) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute(sql, params).fetchall()

    def upsert_match(
        self, match_id: str, opponent: str, flamengo_home: bool, kickoff: datetime
    ) -> None:
        self._run(
            "INSERT INTO bolao_matches (match_id, opponent, flamengo_home, kickoff)"
            " VALUES (?, ?, ?, ?) ON CONFLICT (match_id) DO UPDATE SET"
            " opponent = excluded.opponent, flamengo_home = excluded.flamengo_home,"
            " kickoff = excluded.kickoff",
            match_id,
            opponent,
            int(flamengo_home),
            kickoff.isoformat(),
        )

    def match(self, match_id: str) -> BolaoMatch | None:
        rows = self._run(
            "SELECT match_id, opponent, flamengo_home, kickoff, fla_goals, opp_goals"
            " FROM bolao_matches WHERE match_id = ?",
            match_id,
        )
        if not rows:
            return None
        mid, opponent, home, kickoff, fla, opp = rows[0]
        return BolaoMatch(mid, opponent, bool(home), datetime.fromisoformat(kickoff), fla, opp)

    def is_open(self, match_id: str, now: datetime) -> bool:
        match = self.match(match_id)
        return match is not None and now < match.kickoff

    def nickname(self, email: str) -> str | None:
        rows = self._run("SELECT nickname FROM bolao_players WHERE email = ?", normalize(email))
        return rows[0][0] if rows else None

    def set_nickname(self, email: str, nickname: str) -> bool:
        """False when another player already uses it (case-insensitive)."""
        try:
            self._run(
                "INSERT INTO bolao_players (email, nickname) VALUES (?, ?)"
                " ON CONFLICT (email) DO UPDATE SET nickname = excluded.nickname",
                normalize(email),
                nickname.strip(),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def place_bet(self, email: str, match_id: str, bet: Score, now: datetime) -> bool:
        """False when the match is unknown or already kicked off."""
        if not self.is_open(match_id, now):
            return False
        self._run(
            "INSERT INTO bolao_bets (email, match_id, fla_goals, opp_goals, updated_at)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT (email, match_id) DO UPDATE SET"
            " fla_goals = excluded.fla_goals, opp_goals = excluded.opp_goals,"
            " updated_at = excluded.updated_at",
            normalize(email),
            match_id,
            bet[0],
            bet[1],
            now.isoformat(),
        )
        return True

    def bet(self, email: str, match_id: str) -> Score | None:
        rows = self._run(
            "SELECT fla_goals, opp_goals FROM bolao_bets WHERE email = ? AND match_id = ?",
            normalize(email),
            match_id,
        )
        return rows[0] if rows else None

    def _bets(self, override: tuple[str, Score] | None = None) -> list[tuple]:
        """(nickname, match_id, kickoff, bet, result) of active players with a nickname."""
        rows = self._run(
            "SELECT p.nickname, b.match_id, m.kickoff, b.fla_goals, b.opp_goals,"
            " m.fla_goals, m.opp_goals"
            " FROM bolao_bets b"
            " JOIN bolao_players p ON p.email = b.email"
            " JOIN subscribers s ON s.email = b.email AND s.status = 'active'"
            " JOIN bolao_matches m ON m.match_id = b.match_id"
            " ORDER BY p.nickname"
        )
        bets = []
        for nickname, match_id, kickoff, bf, bo, rf, ro in rows:
            result = None if rf is None else (rf, ro)
            if override is not None and match_id == override[0]:
                result = override[1]
            bets.append((nickname, match_id, datetime.fromisoformat(kickoff), (bf, bo), result))
        return bets

    def ranking(self, season: int, override: tuple[str, Score] | None = None) -> list[RankRow]:
        """Season (calendar year in Brasília) ranking: points, then exact scores."""
        table: dict[str, list[int]] = {}
        for nickname, _, kickoff, bet, result in self._bets(override):
            if kickoff.astimezone(TZ).year != season:
                continue
            row = table.setdefault(nickname, [0, 0])
            if result is not None:
                row[0] += points(bet, result)
                row[1] += bet == result
        rows = [RankRow(nickname=n, points=p, exact=e) for n, (p, e) in table.items()]
        return sorted(rows, key=lambda r: (-r.points, -r.exact, r.nickname.lower()))

    def summary(self, match_id: str, result: Score, persist: bool) -> BolaoSummary:
        """The match's bolão with this result; persist=False only previews it."""
        if persist:
            self._run(
                "UPDATE bolao_matches SET fla_goals = ?, opp_goals = ? WHERE match_id = ?",
                result[0],
                result[1],
                match_id,
            )
        match = self.match(match_id)
        season = match.kickoff.astimezone(TZ).year
        ranking = self.ranking(season, override=(match_id, result))
        match_bets = [(n, bet) for n, mid, _, bet, _ in self._bets() if mid == match_id]
        real_diff = result[0] - result[1]
        missed = [
            ((abs(bet[0] - bet[1] - real_diff),), n)
            for n, bet in match_bets
            if points(bet, result) == 0
        ]
        return BolaoSummary(
            fla_goals=result[0],
            opp_goals=result[1],
            exact=[n for n, bet in match_bets if bet == result],
            top=ranking[:TOP],
            king=_unique_best([((r.points, r.exact), r.nickname) for r in ranking]),
            cold_foot=_unique_best(missed),
        )
