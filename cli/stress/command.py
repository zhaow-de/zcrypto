"""`zcrypto stress` — walk-forward OOS validation across annual test windows."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import typer

from cli.config import ConfigError, load_config, resolve_data_dir
from cli.data.index import load_index
from cli.experiment.multiseed import run_holdout_seeds
from cli.experiment.recipes.base import resolve_recipe
from cli.stress.windows import build_oos_windows

_TEST_STARTS = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]
# qlib's SimulatorExecutor peeks calendar[index+1] at the last backtest step, so the last
# window's test_end must NOT be the calendar's final day. Cap data_end this many days before
# the calendar end to leave that tail (the recipes hardcode the same buffer in their test segment).
_BACKTEST_TAIL_BUFFER_DAYS = 2


def stress(
    recipe_name: str = typer.Option("steady", "--recipe", help="Recipe to validate out-of-sample."),
    seeds: int = typer.Option(8, "--seeds", help="Seeds per OOS window (multi-seed holdout).", min=1),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="Qlib provider dir; defaults to zcrypto.toml."),  # noqa: UP007
    out: Path = typer.Option(Path("runs"), "--out", help="Root for stress bundles (<out>/stress/<recipe>/<ts>)."),
) -> None:
    """Roll train→test across annual OOS windows; report per-window long-only vs L/S Sharpe."""
    import json
    from datetime import datetime, timezone

    from cli.logging import get_logger

    logger = get_logger("stress.command")

    try:
        recipe = resolve_recipe(recipe_name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        data_dir = resolve_data_dir(data_dir, load_config()).resolve()
    except ConfigError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    idx = load_index(data_dir)
    if idx is None:
        typer.echo(f"ERROR: no dataset index at {data_dir}", err=True)
        raise typer.Exit(code=1)

    import datetime as _dt

    data_end = (_dt.date.fromisoformat(idx.calendar.to_date) - _dt.timedelta(days=_BACKTEST_TAIL_BUFFER_DAYS)).isoformat()
    windows = build_oos_windows(_TEST_STARTS, data_start=idx.calendar.from_date, data_end=data_end)

    results = []
    for w in windows:
        recipe_w = dataclasses.replace(recipe, segments={"train": w["train"], "valid": w["valid"], "test": w["test"]})
        logger.info("stress-window", extra={"label": w["label"], "train": w["train"], "test": w["test"]})
        res = run_holdout_seeds(recipe_w, data_dir=data_dir, seeds=seeds, deterministic=True)
        s = res["summary"]
        results.append(
            {
                "label": w["label"],
                "train": w["train"],
                "test": w["test"],
                "sharpe_mean": s["sharpe"]["mean"],
                "ls_sharpe_mean": s["ls_sharpe"]["mean"],
                "ls_sharpe_min": s["ls_sharpe"]["min"],
            }
        )

    created = datetime.now(timezone.utc)
    bundle = out / "stress" / recipe.name / created.strftime("%Y%m%dT%H%M%SZ")
    bundle.mkdir(parents=True, exist_ok=True)
    ls_means = [r["ls_sharpe_mean"] for r in results]
    aggregate = {
        "n_windows": len(results),
        "ls_sharpe_windows_positive": sum(1 for v in ls_means if v > 0),
        "ls_sharpe_worst": min(ls_means) if ls_means else None,
        "ls_sharpe_mean_across_windows": (sum(ls_means) / len(ls_means)) if ls_means else None,
    }
    (bundle / "stress_summary.json").write_text(
        json.dumps({"recipe": recipe.name, "seeds": seeds, "windows": results, "aggregate": aggregate}, indent=2)
    )

    typer.echo(f"OOS walk-forward — {recipe.name} ({seeds} seeds/window)")
    typer.echo(f"  {'window':10} {'long-only sharpe':>17} {'ls_sharpe':>11}")
    for r in results:
        typer.echo(f"  {r['label']:10} {r['sharpe_mean']:>17.3f} {r['ls_sharpe_mean']:>11.3f}")
    typer.echo(
        f"  L/S Sharpe: {aggregate['ls_sharpe_windows_positive']}/{aggregate['n_windows']} windows positive; "
        f"worst {aggregate['ls_sharpe_worst']:.3f}; mean {aggregate['ls_sharpe_mean_across_windows']:.3f}"
    )
    typer.echo(f"  bundle: {bundle}")
