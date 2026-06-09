from __future__ import annotations

from pathlib import Path

import typer

from cli.data.verify import verify_dataset

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
