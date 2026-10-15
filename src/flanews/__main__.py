import logging
from datetime import datetime
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from flanews import __version__, pipeline
from flanews.edition import resolve_edition

app = typer.Typer(help="Flamengo News CLI", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Flamengo News CLI root callback."""


@app.command()
def version() -> None:
    """Print the flanews version."""
    typer.echo(f"flanews v{__version__}")


@app.command()
def collect(
    edition: Annotated[
        Literal["monday", "friday", "auto"], typer.Option(help="Edition kind")
    ] = "auto",
    date: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: today)"),
    ] = None,
) -> None:
    """Collect the edition's articles and print them as a table."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    resolved = resolve_edition(edition, now=date.replace(hour=12) if date else None)
    articles = pipeline.collect_articles(resolved)

    table = Table(title=f"{resolved.label} ({len(articles)} artigos)")
    table.add_column("Fonte")
    table.add_column("Data")
    table.add_column("Título")
    for article in articles:
        table.add_row(article.source, article.published_at.strftime("%d/%m %H:%M"), article.title)
    Console(width=160).print(table)


if __name__ == "__main__":
    app()
