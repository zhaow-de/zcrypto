from __future__ import annotations

import tempfile
from importlib.resources import as_file, files
from pathlib import Path

import typer

from cli.example.config import TEST

_LABELS = [
    ("strategy_absolute", "Strategy return (net, absolute)"),
    ("excess_return_with_cost", "Excess vs ETH (net of costs)"),
    ("excess_return_without_cost", "Excess vs ETH (gross)"),
]


def example(
    show_data: bool = typer.Option(
        False,
        "--show-data/--no-show-data",
        help="Print the head of the prepared feature frame.",
    ),
) -> None:
    """Run a small offline Qlib ETH-USD strategy backtest demo."""
    # Deferred so `zcrypto --version` and help stay fast (importing qlib is ~1s).
    from cli.example.dataset import build_provider
    from cli.example.workflow import run_experiment

    with tempfile.TemporaryDirectory(prefix="zcrypto-example-") as tmp:
        tmp_path = Path(tmp)
        data_ref = files("cli.example").joinpath("data", "crypto_ohlcv.csv.gz")
        with as_file(data_ref) as csv_path:
            provider_uri = build_provider(csv_path, tmp_path / "qlib_data")
        exp_uri = (tmp_path / "mlruns").as_uri()
        metrics = run_experiment(provider_uri, exp_uri, show_data=show_data)

    _render(metrics)


def _render(metrics: dict) -> None:
    typer.echo(f"Backtest test window {TEST[0]} .. {TEST[1]}")
    for key, label in _LABELS:
        m = metrics[key]
        typer.echo(f"\n{label}:")
        typer.echo(f"  annualized_return : {m['annualized_return']:+.4f}")
        typer.echo(f"  information_ratio : {m['information_ratio']:+.4f}")
        typer.echo(f"  max_drawdown      : {m['max_drawdown']:+.4f}")
