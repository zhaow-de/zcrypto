from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

import typer

from cli.data.binance import BinanceSource
from cli.data.layout import DatasetPaths
from cli.data.pipeline import PipelineError, backfill_pipeline, delist_pipeline, download_pipeline, rename_pipeline
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
    data_dir: Path = typer.Option(
        Path("data"), "--data-dir", help="Compiled dataset dir to validate (default ./data).", file_okay=False
    ),
    silent: bool = typer.Option(False, "--silent", help="Print nothing; convey result via exit code only."),
) -> None:
    """Re-validate an existing dataset against `index.json` and all invariants."""
    report = verify_dataset(data_dir, fail_on_gap=True)
    if not silent:
        if report.is_empty:
            typer.echo(f"OK — {data_dir} is empty (no dataset to verify).")
        else:
            if report.checks:
                typer.echo(f"Checked {data_dir}:")
                for c in report.checks:
                    typer.echo(f"  [✓] {c}")
            if report.synthetic:
                typer.echo("Synthetic data (NaN price, e.g. rename gap fill):")
                for s in report.synthetic:
                    typer.echo(f"  [i] {s}")
            if report.ok:
                typer.echo(f"OK — {data_dir} validates clean.")
            else:
                typer.echo(f"FAIL — {len(report.problems)} problem(s) in {data_dir}:")
                for p in report.problems:
                    typer.echo(f"  - {p}")
    raise typer.Exit(code=0 if report.ok else 1)


@data_app.command("download")
def download_cmd(
    backup_dir: Path = typer.Argument(..., help="Backup dir (raw/ + snapshots/); created if absent.", file_okay=False),
    pairs_file: Path = typer.Argument(..., help="Plain-text file: one Binance symbol per line.", exists=True, dir_okay=False),
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Compiled dataset dir (default ./data).", file_okay=False),
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Fetch Binance spot klines and write/append a Qlib-ready dataset."""
    # Callbacks already validated and parsed; cast to dt.date (the callback returns dt.date | None).
    fd: dt.date = from_date if isinstance(from_date, dt.date) else dt.date(2020, 1, 1)  # type: ignore[assignment]
    td: dt.date = to_date if isinstance(to_date, dt.date) else (dt.date.today() - dt.timedelta(days=1))  # type: ignore[assignment]
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        download_pipeline(paths, pairs_file, interval, fd, td, source=BinanceSource(), dry_run=dry_run)
    except PipelineError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1) from e
    if not dry_run:
        typer.echo(f"OK — dataset at {data_dir} now reaches {td}.")


@data_app.command("backfill")
def backfill_cmd(
    backup_dir: Path = typer.Argument(..., help="Backup dir (raw/ + snapshots/); created if absent.", file_okay=False),
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Compiled dataset dir (default ./data).", file_okay=False),
    interval: str = typer.Option("1d", "--interval", help="Kline interval (only 1d supported)."),
    arg_to_str: Optional[str] = typer.Option(  # noqa: UP007
        None,
        "--to",
        callback=_to_callback,
        help="ISO date YYYY-MM-DD (default: yesterday UTC).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Extend every TRADING pair in the index to --to (default yesterday UTC)."""
    arg_to: dt.date = arg_to_str if isinstance(arg_to_str, dt.date) else (dt.date.today() - dt.timedelta(days=1))  # type: ignore[assignment]
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        backfill_pipeline(paths, interval, arg_to, BinanceSource(), dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run:
        typer.echo(f"backfill complete: {data_dir}")


@data_app.command("delist")
def delist_cmd(
    backup_dir: Path = typer.Argument(..., help="Backup dir (raw/ + snapshots/); created if absent.", file_okay=False),
    symbol: str = typer.Argument(..., help="Symbol to remove (e.g. BTCUSDT)."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Compiled dataset dir (default ./data).", file_okay=False),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Remove SYMBOL from the dataset."""
    symbol = symbol.upper()
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        delist_pipeline(paths, symbol, dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run:
        typer.echo(f"delist complete: {symbol} removed from {data_dir}")


@data_app.command("rename")
def rename_cmd(
    backup_dir: Path = typer.Argument(..., help="Backup dir (raw/ + snapshots/); created if absent.", file_okay=False),
    old_symbol: str = typer.Argument(..., help="Existing symbol to rename (e.g. MATICUSDT)."),
    new_symbol: str = typer.Argument(..., help="Replacement symbol name (e.g. POLUSDT)."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Compiled dataset dir (default ./data).", file_okay=False),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    """Re-label OLD_SYMBOL to NEW_SYMBOL in the dataset (Variant 1: single rename + synthetic gap fill)."""
    old_symbol = old_symbol.upper()
    new_symbol = new_symbol.upper()
    paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)
    try:
        rename_pipeline(paths, old_symbol, new_symbol, BinanceSource(), dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run:
        typer.echo(f"rename complete: {old_symbol} → {new_symbol} in {data_dir}")
