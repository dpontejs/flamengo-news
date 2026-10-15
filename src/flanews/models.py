from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Article(BaseModel):
    """Normalized article metadata and extracted content."""

    url: str
    title: str
    source: str
    published_at: datetime
    summary_hint: str | None = None
    content: str | None = None
    # flamengo: main news; saiba_mais: other Flamengo sports; brasil: Brazilian football
    section: Literal["flamengo", "saiba_mais", "brasil"] = "flamengo"
    category: str | None = None


class Brief(BaseModel):
    """Short item for the "Saiba mais" and "Brasil afora" sections."""

    title: str
    summary: str
    url: str
    source: str
    category: str | None = None


class Topic(BaseModel):
    """Grouped news topic summarized by LLM."""

    title: str
    summary: str
    articles: list[Article] = Field(default_factory=list)
    importance: int = 1


class MatchEvent(BaseModel):
    """Event occurring during a match (goal, card, substitution)."""

    minute: int
    extra_minute: int | None = None
    team: str
    player: str
    type: str
    detail: str | None = None


class MatchStats(BaseModel):
    """Detailed statistics and info of a completed match."""

    fixture_id: int
    competition: str
    date: datetime
    home: str
    away: str
    home_goals: int
    away_goals: int
    venue: str | None = None
    home_logo: str | None = None
    away_logo: str | None = None
    events: list[MatchEvent] = Field(default_factory=list)
    statistics: dict[str, tuple[str, str]] = Field(default_factory=dict)
    lineups: dict[str, list[str]] = Field(default_factory=dict)
    # team -> [(category in pt-BR, player, value)]
    leaders: dict[str, list[tuple[str, str, str]]] = Field(default_factory=dict)


class NextMatch(BaseModel):
    """Information about the upcoming match."""

    opponent: str
    competition: str
    date: datetime
    venue: str | None = None
    is_home: bool = True
    opponent_logo: str | None = None


class StandingRow(BaseModel):
    """Single row in a league standing table."""

    position: int
    team: str
    points: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_diff: int
    goals_for: int = 0
    goals_against: int = 0
    is_flamengo: bool = False


class FormResult(BaseModel):
    """Flamengo's result in a recent match, from Flamengo's point of view."""

    result: Literal["V", "E", "D"]
    opponent: str
    score: str
    competition: str
    date: datetime


class PlayerRanking(BaseModel):
    """A Flamengo player's position in a league leaderboard."""

    category: str
    player: str
    position: int
    value: int


class TeamMoment(BaseModel):
    """Recent form, league campaign and player rankings."""

    form: list[FormResult] = Field(default_factory=list)
    standing: StandingRow | None = None
    gap: str | None = None
    rankings: list[PlayerRanking] = Field(default_factory=list)


class Edition(BaseModel):
    """Newsletter edition temporal window and description."""

    kind: Literal["monday", "friday", "auto"]
    start: datetime
    end: datetime
    label: str


class Newsletter(BaseModel):
    """Full newsletter content ready for rendering and dispatch."""

    edition: Edition
    intro: str
    headline: str = ""
    analysis: str = ""
    moment: TeamMoment | None = None
    topics: list[Topic] = Field(default_factory=list)
    learn_more: list[Brief] = Field(default_factory=list)
    around_brazil: list[Brief] = Field(default_factory=list)
    last_match: MatchStats | None = None
    next_match: NextMatch | None = None
    standings: list[StandingRow] = Field(default_factory=list)
