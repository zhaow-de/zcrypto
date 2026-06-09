from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

import typer

from cli.data.binance import BinanceSource
from cli.data.pipeline import PipelineError, download_pipeline
from cli.data.verify import verify_dataset

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date_arg(name: str, value: str) -> dt.date:
    if not _ISO_RE.match(value):
        raise typer.BadParameter(f"{name} must be YYYY-MM-DD, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as e:
        raise typer.BadParameter(f"{name} is not a real calendar date: {value!r}") from e


def _from_callback(value: str | None) -> dt.date | None:
    if value is None:
        return None
    return _parse_date_arg("--from", value)


def _to_callback(value: str | None) -> dt.date | None:
    if value is None:
        return None
    return _parse_date_arg("--to", value)


data_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Prepare a Qlib-ready dataset from Binance spot klines.",
)


@data_app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """`zcrypto data` — bare invocation prints this group's help and exits."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@data_app.command("verify")
def verify_cmd(
    out_dir: Path = typer.Argument(..., help="Dataset directory to validate.", exists=True, file_okay=False),
    silent: bool = typer.Option(False, "--silent", help="Print nothing; convey result via exit code only."),
) -> None:
    """Re-validate an existing dataset against `index.json` and all invariants."""
    report = verify_dataset(out_dir)
    if not silent:
        if report.ok:
            typer.echo(f"OK — {out_dir} validates clean.")
        else:
            typer.echo(f"FAIL — {len(report.problems)} problem(s) in {out_dir}:")
            for p in report.problems:
                typer.echo(f"  - {p}")
    raise typer.Exit(code=0 if report.ok else 1)


@data_app.command("download")
def download_cmd(
    out_dir: Path = typer.Argument(..., help="Dataset directory (created if absent).", file_okay=False),
    pairs_file: Path = typer.Argument(..., help="Plain-text file: one Binance symbol per line.", exists=True, dir_okay=False),
    interval: str = typer.Option("1d", "--interval", help="Kline interval (only 1d supported)."),
    from_date: Optional[str] = typer.Option(  # noqa: UP007 (Typer needs Optional[X] not X | None)
        "2020-01-01",
        "--from",
        callback=_from_callback,
        help="ISO date YYYY-MM-DD.",
    ),
    to_date: Optional[str] = typer.Option(
        None,
        "--to",
        callback=_to_callback,
        help="ISO date YYYY-MM-DD (default: yesterday UTC).",
    ),
) -> None:
    """Fetch Binance spot klines and write/append a Qlib-ready dataset."""
    # Callbacks already validated and parsed; cast to dt.date (the callback returns dt.date | None).
    fd: dt.date = from_date if isinstance(from_date, dt.date) else dt.date(2020, 1, 1)  # type: ignore[assignment]
    td: dt.date = to_date if isinstance(to_date, dt.date) else (dt.date.today() - dt.timedelta(days=1))  # type: ignore[assignment]
    try:
        download_pipeline(out_dir, pairs_file, interval, fd, td, source=BinanceSource())
    except PipelineError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"OK — dataset at {out_dir} now reaches {td}.")
