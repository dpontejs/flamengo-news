import typer

from flanews import __version__

app = typer.Typer(help="Flamengo News CLI", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Flamengo News CLI root callback."""


@app.command()
def version() -> None:
    """Print the flanews version."""
    typer.echo(f"flanews v{__version__}")


if __name__ == "__main__":
    app()
