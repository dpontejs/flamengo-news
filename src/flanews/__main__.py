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
from flanews.edition import edition_from_slot, resolve_match_edition
from flanews.models import Edition, Newsletter
from flanews.render.announcement import parse_announcement, render_announcement
from flanews.render.renderer import render
from flanews.report import ProblemCollector, RunReport
from flanews.schedule import LABELS, TZ, Fixture, Slot, label_of, plan
from flanews.schedule import due as due_slot
from flanews.send.recipients import (
    LatestEdition,
    latest_edition,
    publish_latest_edition,
    resolve_recipients,
)
from flanews.send.resend_sender import (
    UNSUBSCRIBE_PLACEHOLDER,
    ResendSender,
    SendError,
    build_subject,
)
from flanews.stats.espn import ESPNStatsClient, StatsUnavailable
from flanews.stats.table import standings_window
from flanews.summarizer.client import LLMError

logger = logging.getLogger("flanews.run")

app = typer.Typer(help="Urubu News CLI", no_args_is_help=True)

EditionOption = Annotated[
    Literal["auto", "pre", "post", "news"],
    typer.Option(help="Edition kind; auto = the one the match calendar has due now"),
]
NoteOption = Annotated[
    str | None, typer.Option(help='Announcement shown in a "Novidades" box (manual sends)')
]
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
    note: NoteOption = None,
) -> None:
    """Build the full newsletter without sending it and save HTML and text."""
    _setup_logging()
    resolved = _resolve(edition, date)
    settings = get_settings()
    newsletter = pipeline.build_newsletter(
        resolved, settings, published_topics=_published_topics(settings)
    )
    html_path = out or Path("out") / f"preview-{resolved.end:%Y-%m-%d}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html, text = render(
        newsletter,
        unsubscribe_url=pipeline.unsubscribe_url(settings),
        logo_url=_logo(settings),
        note=note,
    )

    html_path.write_text(html, encoding="utf-8")
    html_path.with_suffix(".txt").write_text(text, encoding="utf-8")
    typer.echo(f"Preview saved to {html_path} and {html_path.with_suffix('.txt')}")
    if open_browser:
        webbrowser.open(html_path.resolve().as_uri())


@app.command()
def due() -> None:
    """Print the edition due now as "kind<TAB>YYYY-MM-DD<TAB>label", or nothing."""
    _setup_logging()
    settings = get_settings()
    now = _now()
    try:
        fixtures = _fixtures(settings, now)
    except StatsUnavailable as e:
        logger.error("Calendar unavailable, nothing is due: %s", e)
        return
    latest = _latest(settings)
    sent_at, sent_label = (
        (latest.published_at, label_of(latest.subject)) if latest else (None, None)
    )
    slot = due_slot(plan(fixtures, now, sent_at, sent_label), now)
    if slot is not None:
        typer.echo(f"{slot.kind}\t{slot.send_at:%Y-%m-%d}\t{slot.label}")


@app.command()
def run(
    edition: EditionOption = "auto",
    date: DateOption = None,
    skip_if_sent: Annotated[
        bool,
        typer.Option(
            "--skip-if-sent", help="Do nothing if the page already has this edition (retries)"
        ),
    ] = False,
    note: NoteOption = None,
) -> None:
    """Build, render, save to out/ and send the newsletter (respects DRY_RUN)."""
    _setup_logging()
    resolved = _resolve(edition, date)
    settings = get_settings()
    report = RunReport(edition=resolved.label, outcome="interrompida")
    if skip_if_sent and _already_sent(settings, resolved.label):
        report.outcome = "já enviada por outro disparo"
        typer.echo(f"{resolved.label}: já enviada, nada a fazer.")
        _publish_report(report)
        return
    try:
        llm = pipeline.get_llm_client(settings)
    except LLMError:
        llm = None  # build_newsletter logs the failure and keeps the stats sections

    with ProblemCollector() as problems:
        try:
            newsletter = pipeline.build_newsletter(
                resolved,
                settings,
                llm=llm,
                report=report,
                published_topics=_published_topics(settings),
            )
            _fill_report(report, newsletter)
            if resolved.kind == "post" and newsletter.last_match is None:
                report.outcome = "não enviada: partida não encerrada"
                typer.echo(f"{resolved.label}: partida não encerrada, nada a enviar.")
                return
            if pipeline.is_empty(newsletter):
                report.outcome = "nada para enviar (sem notícias e sem partida)"
                typer.echo(f"Nada para enviar em {resolved.label}: sem notícias e sem partida.")
                raise typer.Exit(code=1)

            # The page link only shows up once subscriptions are live (API token configured).
            subscribe = settings.PUBLIC_URL.rstrip("/") if settings.SUBSCRIBERS_API_TOKEN else None

            def render_edition(note: str | None) -> tuple[str, str]:
                return render(
                    newsletter,
                    unsubscribe_url=UNSUBSCRIBE_PLACEHOLDER,
                    subscribe_url=subscribe,
                    logo_url=_logo(settings),
                    note=note,
                )

            html, text = render_edition(note)
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
            # The page keeps the plain edition: new subscribers get no stale announcement.
            plain_subject = build_subject(newsletter)
            subject = f"Novidades! {plain_subject}" if note else plain_subject
            try:
                ids = ResendSender.from_settings(settings).send(subject, html, text, recipients)
            except SendError as e:
                report.outcome = f"falha no envio: {e}"
                typer.echo(f"Falha no envio: {e}")
                raise typer.Exit(code=2) from e
            if ids and settings.SUBSCRIBERS_API_TOKEN:
                try:
                    plain_html, plain_text = render_edition(None) if note else (html, text)
                    publish_latest_edition(settings, plain_subject, plain_html, plain_text)
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


@app.command()
def announce(
    source: Annotated[Path, typer.Argument(help="Markdown file: '# subject', then paragraphs")],
) -> None:
    """Send a one-off e-mail to every recipient (respects DRY_RUN); the page is left as is."""
    _setup_logging()
    settings = get_settings()
    announcement = parse_announcement(source.read_text(encoding="utf-8"))
    subscribe = settings.PUBLIC_URL.rstrip("/") if settings.SUBSCRIBERS_API_TOKEN else None
    html, text = render_announcement(
        announcement,
        unsubscribe_url=UNSUBSCRIBE_PLACEHOLDER,
        subscribe_url=subscribe,
        logo_url=_logo(settings),
    )
    mailto = pipeline.unsubscribe_url(settings)
    html_path = Path("out") / f"{source.stem}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html.replace(UNSUBSCRIBE_PLACEHOLDER, mailto), encoding="utf-8")
    html_path.with_suffix(".txt").write_text(
        text.replace(UNSUBSCRIBE_PLACEHOLDER, mailto), encoding="utf-8"
    )
    recipients = resolve_recipients(settings).recipients
    # Not published to the page: the schedule and new subscribers only see real editions.
    try:
        ids = ResendSender.from_settings(settings).send(
            announcement.subject, html, text, recipients
        )
    except SendError as e:
        typer.echo(f"Falha no envio: {e}")
        raise typer.Exit(code=2) from e
    noun = "destinatário" if len(ids) == 1 else "destinatários"
    status = f"enviado para {len(ids)} {noun}" if ids else "não enviado (DRY_RUN)"
    typer.echo(
        f"{announcement.subject}: {status} ({len(recipients)} na lista); cópia em {html_path}"
    )


def _already_sent(settings, label: str) -> bool:
    """Whether the page's latest edition is this one; unknown counts as not sent."""
    if not settings.SUBSCRIBERS_API_TOKEN:
        return False
    try:
        edition = latest_edition(settings)
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Could not check whether the edition was already sent: %s", e)
        return False
    return edition is not None and f"— {label}" in edition.subject


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
    """`auto`: the slot due now (none: exit 0); a kind: its slot on `date` (default today)."""
    settings = get_settings()
    now = _now()
    try:
        fixtures = _fixtures(settings, now)
    except StatsUnavailable as e:
        typer.echo(f"Agenda da ESPN indisponível: {e}")
        raise typer.Exit(code=0 if edition == "auto" else 1) from e
    latest = _latest(settings)
    if edition == "auto":
        sent_at, sent_label = (
            (latest.published_at, label_of(latest.subject)) if latest else (None, None)
        )
        slot = due_slot(plan(fixtures, now, sent_at, sent_label), now)
        if slot is None:
            typer.echo("Nenhuma edição agendada agora.")
            raise typer.Exit(code=0)
        return edition_from_slot(slot)
    day = date.date() if date else now.date()
    last_sent = latest.published_at if latest else None
    resolved = resolve_match_edition(edition, day, fixtures, last_sent)  # type: ignore[arg-type]
    if resolved is None:
        typer.echo(f"Nenhuma edição {LABELS[edition]} prevista em {day:%d/%m/%Y}.")
        raise typer.Exit(code=1)
    return resolved


def _due(fixtures: list[Fixture], now: datetime, latest: LatestEdition | None) -> Slot | None:
    """The slot due now, planned from the real last send (and its label, against reschedules)."""
    if latest is None:
        return due_slot(plan(fixtures, now, None), now)
    return due_slot(plan(fixtures, now, latest.published_at, label_of(latest.subject)), now)


def _now() -> datetime:
    return datetime.now(TZ)


def _fixtures(settings, now: datetime) -> list[Fixture]:
    client = ESPNStatsClient(team_id=settings.FLAMENGO_TEAM_ID, tz_name=settings.TIMEZONE)
    return client.get_fixtures(now)


def _published_topics(settings) -> list[str]:
    """Topics of the edition already sent, so the model does not repeat them."""
    latest = _latest(settings)
    return latest.topic_titles if latest else []


def _latest(settings) -> LatestEdition | None:
    """The page's latest edition (subject, send time); unknown (no token, page down) is None."""
    if not settings.SUBSCRIBERS_API_TOKEN:
        return None
    try:
        return latest_edition(settings)
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Could not read the latest edition, planning without it: %s", e)
        return None


if __name__ == "__main__":
    app()
