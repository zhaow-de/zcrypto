from importlib.metadata import version
from pathlib import Path
from typing import Optional

import typer

from cli.logging import configure

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"zcrypto v{version('zcrypto')} (with pyqlib-{version('pyqlib')})")
        raise typer.Exit()


def _log_level_callback(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
    upper = value.upper()
    if upper not in _VALID_LEVELS:
        raise typer.BadParameter(f"must be one of {', '.join(sorted(_VALID_LEVELS))}, got {value!r}")
    return upper


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_: bool = typer.Option(
        None,
        "-v",
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the application version and exit.",
    ),
    log: Optional[Path] = typer.Option(
        None,
        "-l",
        "--log",
        help="Append JSONL logs to this file. If unset, plain-text logs go to stdout.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        callback=_log_level_callback,
        # Eager so `--log-level TRACE --version` errors at parse time instead of being swallowed by --version's eager exit.
        is_eager=True,
        case_sensitive=False,
        help="Log threshold. One of DEBUG, INFO, WARNING, ERROR.",
    ),
) -> None:
    configure(log, log_level)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


from cli.example.command import example

app.command(name="example")(example)

from cli.experiment.command import experiment

app.command(name="experiment")(experiment)

from cli.data.command import data_app

app.add_typer(data_app, name="data")


if __name__ == "__main__":
    app()
