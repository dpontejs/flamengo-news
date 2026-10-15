import logging
from datetime import datetime
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from flanews import __version__, pipeline
from flanews.config import get_settings
from flanews.edition import resolve_edition
from flanews.models import Edition
from flanews.stats.espn import ESPNStatsClient
from flanews.stats.table import standings_window

app = typer.Typer(help="Flamengo News CLI", no_args_is_help=True)

EditionOption = Annotated[Literal["monday", "friday", "auto"], typer.Option(help="Edition kind")]
DateOption = Annotated[
    datetime | None,
    typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: today)"),
]


@app.callback()
def main() -> None:
    """Flamengo News CLI root callback."""


@app.command()
def version() -> None:
    """Print the flanews version."""
    typer.echo(f"flanews v{__version__}")


@app.command()
def collect(
    edition: EditionOption = "auto",
    date: DateOption = None,
) -> None:
    """Collect the edition's articles and print them as a table."""
    _setup_logging()
    resolved = _resolve(edition, date)
    articles = pipeline.collect_articles(resolved)

    table = Table(title=f"{resolved.label} ({len(articles)} artigos)")
    table.add_column("Fonte")
    table.add_column("Data")
    table.add_column("Título")
    for article in articles:
        table.add_row(article.source, article.published_at.strftime("%d/%m %H:%M"), article.title)
    Console(width=160).print(table)


@app.command()
def stats(
    edition: EditionOption = "auto",
    date: DateOption = None,
) -> None:
    """Print the edition's last match, next match and Brasileirão table."""
    _setup_logging()
    resolved = _resolve(edition, date)
    settings = get_settings()
    client = ESPNStatsClient(team_id=settings.FLAMENGO_TEAM_ID, tz_name=settings.TIMEZONE)
    console = Console(width=120)
    console.rule(resolved.label)

    match = client.get_last_match(resolved.start, resolved.end)
    if match is None:
        console.print("Nenhuma partida finalizada na janela da edição.")
    else:
        console.print(
            f"[bold]{match.home} {match.home_goals} x {match.away_goals} {match.away}[/bold]"
            f" — {match.competition}, {match.date:%d/%m %H:%M}"
            + (f", {match.venue}" if match.venue else "")
        )
        for event in match.events:
            if event.type == "goal":
                extra = f"+{event.extra_minute}" if event.extra_minute else ""
                detail = f" ({event.detail})" if event.detail else ""
                console.print(f"  ⚽ {event.minute}'{extra} {event.player} — {event.team}{detail}")
        if match.statistics:
            table = Table(title="Estatísticas")
            table.add_column(match.home, justify="right")
            table.add_column("")
            table.add_column(match.away)
            for label, (home, away) in match.statistics.items():
                table.add_row(home, label, away)
            console.print(table)

    next_match = client.get_next_match(resolved.end)
    if next_match is None:
        console.print("Próximo jogo: não encontrado.")
    else:
        console.print(
            f"Próximo jogo: {next_match.opponent} ({'casa' if next_match.is_home else 'fora'})"
            f" — {next_match.competition}, {next_match.date:%d/%m %H:%M}"
            + (f", {next_match.venue}" if next_match.venue else "")
        )

    rows = standings_window(client.get_standings("bra.1"))
    if rows:
        table = Table(title="Brasileirão")
        for column in ("#", "Time", "P", "J", "V", "E", "D", "SG"):
            table.add_column(column)
        for r in rows:
            style = "bold red" if r.is_flamengo else None
            values = (r.position, r.team, r.points, r.played, r.won, r.drawn, r.lost, r.goals_diff)
            table.add_row(*map(str, values), style=style)
        console.print(table)


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _resolve(edition: str, date: datetime | None) -> Edition:
    settings = get_settings()
    now = date.replace(hour=12) if date else None
    return resolve_edition(edition, now=now, tz_name=settings.TIMEZONE)  # type: ignore[arg-type]


if __name__ == "__main__":
    app()
