import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from premailer import Premailer

from flanews.models import MatchEvent, Newsletter, StandingRow
from flanews.stats.table import standings_window

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
FLAMENGO_CREST = "https://a.espncdn.com/i/teamlogos/soccer/500/819.png"
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
SOURCE_LABELS = {
    "ge": "ge",
    "flamengo_oficial": "Site oficial",
    "google_news": "Google News",
}


def source_label(source: str) -> str:
    """Human-readable source: 'google_news:O GLOBO' -> 'O GLOBO'."""
    prefix, _, outlet = source.partition(":")
    return outlet or SOURCE_LABELS.get(prefix, prefix)


def _when(value: datetime) -> str:
    return f"{WEEKDAYS[value.weekday()]}, {value:%d/%m} às {value:%H:%M}"


def _minute(event: MatchEvent) -> str:
    extra = f"+{event.extra_minute}" if event.extra_minute else ""
    return f"{event.minute}'{extra}"


def _performance(row: StandingRow) -> str:
    """Share of possible points won, e.g. 64 of 90 -> '71%'."""
    if row.played == 0:
        return "-"
    return f"{round(100 * row.points / (3 * row.played))}%"


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html.j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(source=source_label, when=_when, minute=_minute, performance=_performance)
    return env


_env = _environment()


def render(
    newsletter: Newsletter,
    unsubscribe_url: str | None = None,
    subscribe_url: str | None = None,
) -> tuple[str, str]:
    """Render the newsletter as (html with inlined CSS, plain text)."""
    context = {
        "n": newsletter,
        "crest": FLAMENGO_CREST,
        "standings": standings_window(newsletter.standings),
        "unsubscribe_url": unsubscribe_url,
        "subscribe_url": subscribe_url,
    }
    html = _env.get_template("newsletter.html.j2").render(**context)
    text = _env.get_template("newsletter.txt.j2").render(**context)
    inlined = Premailer(
        html,
        keep_style_tags=False,
        remove_classes=True,
        cssutils_logging_level=logging.CRITICAL,
    ).transform()
    # premailer drops the doctype, which some clients need for standards mode.
    return "<!doctype html>\n" + inlined, text.strip() + "\n"
