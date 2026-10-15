import logging
import os
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
import typer
from rich.console import Console
from rich.table import Table

from flanews import __version__, pipeline
from flanews.config import get_settings
from flanews.edition import resolve_edition
from flanews.models import Edition, Newsletter
from flanews.render.renderer import render
from flanews.report import ProblemCollector, RunReport
from flanews.send.recipients import publish_latest_edition, resolve_recipients
from flanews.send.resend_sender import (
    UNSUBSCRIBE_PLACEHOLDER,
    ResendSender,
    SendError,
    build_subject,
)
from flanews.stats.espn import ESPNStatsClient
from flanews.stats.table import standings_window
from flanews.summarizer.client import LLMError

logger = logging.getLogger("flanews.run")

app = typer.Typer(help="Urubu News CLI", no_args_is_help=True)

EditionOption = Annotated[Literal["monday", "friday", "auto"], typer.Option(help="Edition kind")]
DateOption = Annotated[
    datetime | None,
    typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: today)"),
]


@app.callback()
def main() -> None:
    """Urubu News CLI root callback."""


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


@app.command()
def preview(
    edition: EditionOption = "auto",
    date: DateOption = None,
    out: Annotated[
        Path | None, typer.Option(help="HTML output path (default: out/preview-<date>.html)")
    ] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the HTML in the browser")
    ] = False,
) -> None:
    """Build the full newsletter without sending it and save HTML and text."""
    _setup_logging()
    resolved = _resolve(edition, date)
    settings = get_settings()
    newsletter = pipeline.build_newsletter(resolved, settings)
    html, text = render(
        newsletter, unsubscribe_url=pipeline.unsubscribe_url(settings), logo_url=_logo(settings)
    )

    html_path = out or Path("out") / f"preview-{resolved.end:%Y-%m-%d}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    html_path.with_suffix(".txt").write_text(text, encoding="utf-8")
    typer.echo(f"Preview saved to {html_path} and {html_path.with_suffix('.txt')}")
    if open_browser:
        webbrowser.open(html_path.resolve().as_uri())


@app.command()
def run(
    edition: EditionOption = "auto",
    date: DateOption = None,
) -> None:
    """Build, render, save to out/ and send the newsletter (respects DRY_RUN)."""
    _setup_logging()
    resolved = _resolve(edition, date)
    settings = get_settings()
    report = RunReport(edition=resolved.label, outcome="interrompida")
    try:
        llm = pipeline.get_llm_client(settings)
    except LLMError:
        llm = None  # build_newsletter logs the failure and keeps the stats sections

    with ProblemCollector() as problems:
        try:
            newsletter = pipeline.build_newsletter(resolved, settings, llm=llm, report=report)
            _fill_report(report, newsletter)
            if pipeline.is_empty(newsletter):
                report.outcome = "nada para enviar (sem notícias e sem partida)"
                typer.echo(f"Nada para enviar em {resolved.label}: sem notícias e sem partida.")
                raise typer.Exit(code=1)

            # The page link only shows up once subscriptions are live (API token configured).
            subscribe = settings.PUBLIC_URL.rstrip("/") if settings.SUBSCRIBERS_API_TOKEN else None
            html, text = render(
                newsletter,
                unsubscribe_url=UNSUBSCRIBE_PLACEHOLDER,
                subscribe_url=subscribe,
                logo_url=_logo(settings),
            )
            mailto = pipeline.unsubscribe_url(settings)
            html_path = Path("out") / f"newsletter-{resolved.end:%Y-%m-%d}.html"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html.replace(UNSUBSCRIBE_PLACEHOLDER, mailto), encoding="utf-8")
            html_path.with_suffix(".txt").write_text(
                text.replace(UNSUBSCRIBE_PLACEHOLDER, mailto), encoding="utf-8"
            )

            resolved_recipients = resolve_recipients(settings)
            recipients = resolved_recipients.recipients
            report.recipients = len(recipients)
            report.subscribers = resolved_recipients.from_api
            subject = build_subject(newsletter)
            try:
                ids = ResendSender.from_settings(settings).send(subject, html, text, recipients)
            except SendError as e:
                report.outcome = f"falha no envio: {e}"
                typer.echo(f"Falha no envio: {e}")
                raise typer.Exit(code=2) from e
            if ids and settings.SUBSCRIBERS_API_TOKEN:
                try:
                    publish_latest_edition(settings, subject, html, text)
                except httpx.HTTPError as e:
                    logger.warning(
                        "Could not publish the latest edition for new subscribers: %s", e
                    )
            noun = "destinatário" if len(ids) == 1 else "destinatários"
            status = f"enviada para {len(ids)} {noun}" if ids else "não enviada (DRY_RUN)"
            report.outcome = status
            typer.echo(f"{resolved.label}: {status}; cópia em {html_path}")
        finally:
            usage = getattr(llm, "usage", None)
            if usage is not None:
                report.llm_calls = usage.calls
                report.input_tokens = usage.input_tokens
                report.output_tokens = usage.output_tokens
            report.problems = problems.messages
            _publish_report(report)


def _logo(settings) -> str:
    """Header logo, served by the subscription page."""
    return settings.PUBLIC_URL.rstrip("/") + "/static/logo-email.png"


def _fill_report(report: RunReport, newsletter: Newsletter) -> None:
    report.topics = [t.title for t in newsletter.topics]
    report.learn_more = len(newsletter.learn_more)
    report.around_brazil = len(newsletter.around_brazil)
    report.has_match = newsletter.last_match is not None
    report.has_next_match = newsletter.next_match is not None
    report.has_standings = bool(newsletter.standings)


def _publish_report(report: RunReport) -> None:
    """Print the run summary and, on GitHub Actions, add it to the job summary page."""
    markdown = report.to_markdown()
    typer.echo(markdown)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(markdown)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _resolve(edition: str, date: datetime | None) -> Edition:
    settings = get_settings()
    now = date.replace(hour=12) if date else None
    return resolve_edition(edition, now=now, tz_name=settings.TIMEZONE)  # type: ignore[arg-type]


if __name__ == "__main__":
    app()
