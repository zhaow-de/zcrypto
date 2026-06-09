from __future__ import annotations

import typer

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
