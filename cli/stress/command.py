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
from cli.stress.windows import PURGE_DAYS, build_oos_windows

_TEST_STARTS = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]
# qlib's SimulatorExecutor peeks calendar[index+1] at the last backtest step, so the last
# window's test_end must NOT be the calendar's final day. Cap data_end this many days before
# the calendar end to leave that tail (the recipes hardcode the same buffer in their test segment).
_BACKTEST_TAIL_BUFFER_DAYS = 2


def stress(
    recipe_name: str = typer.Option("steady", "--recipe", help="Recipe to validate out-of-sample."),
    null_recipe: str = typer.Option(
        "beta_null", "--null", help="Pre-registered passive-beta null to benchmark against; '' to skip."
    ),
    seeds: int = typer.Option(8, "--seeds", help="Seeds per OOS window (multi-seed holdout).", min=1),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", help="Qlib provider dir; defaults to zcrypto.toml."),  # noqa: UP007
    out: Path = typer.Option(Path("runs"), "--out", help="Root for stress bundles (<out>/stress/<recipe>/<ts>)."),
) -> None:
    """Roll train→test across annual OOS windows; report per-window long-only vs L/S Sharpe."""
    import json
    from datetime import datetime, timezone

    import pandas as pd

    from cli.experiment.stats import deflated_sharpe as _deflated_sharpe
    from cli.experiment.stats import paired_bootstrap_delta_ci
    from cli.experiment.trials import cumulative_sr_trials, recipe_config_hash, register_trial
    from cli.logging import get_logger

    logger = get_logger("stress.command")

    try:
        recipe = resolve_recipe(recipe_name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    # Resolve null recipe if specified.
    use_null = bool(null_recipe)
    null_obj = None
    if use_null:
        try:
            null_obj = resolve_recipe(null_recipe)
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
    purge_days = max(PURGE_DAYS, recipe.label_horizon_days + 2)
    windows = build_oos_windows(_TEST_STARTS, data_start=idx.calendar.from_date, data_end=data_end, purge_days=purge_days)

    results = []
    # Collect candidate daily_long Series across all windows for deflated Sharpe.
    all_cand_daily: list[pd.Series] = []

    for w in windows:
        recipe_w = dataclasses.replace(recipe, segments={"train": w["train"], "valid": w["valid"], "test": w["test"]})
        logger.info("stress-window", extra={"label": w["label"], "train": w["train"], "test": w["test"]})
        res = run_holdout_seeds(recipe_w, data_dir=data_dir, seeds=seeds, deterministic=True)
        s = res["summary"]
        sharpe_mean = s["sharpe"]["mean"]

        # Mean candidate daily_long across seeds (inner join on date index).
        cand_daily_per_seed = [entry["daily_long"] for entry in res["per_seed"]]
        cand_daily = pd.concat(cand_daily_per_seed, axis=1).mean(axis=1)
        all_cand_daily.append(cand_daily)

        row: dict = {
            "label": w["label"],
            "train": w["train"],
            "test": w["test"],
            "sharpe_mean": sharpe_mean,
            "ls_sharpe_mean": s["ls_sharpe"]["mean"],
            "ls_sharpe_min": s["ls_sharpe"]["min"],
        }

        if use_null and null_obj is not None:
            null_w = dataclasses.replace(null_obj, segments={"train": w["train"], "valid": w["valid"], "test": w["test"]})
            logger.info("stress-window-null", extra={"label": w["label"]})
            null_res = run_holdout_seeds(null_w, data_dir=data_dir, seeds=seeds, deterministic=True)
            null_sharpe_mean = null_res["summary"]["sharpe"]["mean"]
            delta_sharpe = sharpe_mean - null_sharpe_mean

            # Mean null daily_long across seeds, then align with candidate on inner join.
            null_daily_per_seed = [entry["daily_long"] for entry in null_res["per_seed"]]
            null_daily = pd.concat(null_daily_per_seed, axis=1).mean(axis=1)

            # Align on shared date index (inner join).
            aligned = pd.concat([cand_daily, null_daily], axis=1, join="inner")
            aligned.columns = ["cand", "null"]
            delta_ci = paired_bootstrap_delta_ci(
                aligned["cand"].to_numpy(),
                aligned["null"].to_numpy(),
                block_len=10,
                seed=0,
            )
            row["null_sharpe_mean"] = null_sharpe_mean
            row["delta_sharpe"] = delta_sharpe
            row["delta_ci"] = {"lo": delta_ci["lo"], "hi": delta_ci["hi"], "se": delta_ci["se"]}

        results.append(row)

    created = datetime.now(timezone.utc)
    bundle = out / "stress" / recipe.name / created.strftime("%Y%m%dT%H%M%SZ")
    bundle.mkdir(parents=True, exist_ok=True)
    ls_means = [r["ls_sharpe_mean"] for r in results]
    aggregate: dict = {
        "n_windows": len(results),
        "ls_sharpe_windows_positive": sum(1 for v in ls_means if v > 0),
        "ls_sharpe_worst": min(ls_means) if ls_means else None,
        "ls_sharpe_mean_across_windows": (sum(ls_means) / len(ls_means)) if ls_means else None,
    }

    if use_null and results and "delta_sharpe" in results[0]:
        deltas = [r["delta_sharpe"] for r in results]
        aggregate["delta_mean_across_windows"] = sum(deltas) / len(deltas)

        # Register trial and compute deflated Sharpe.
        trials_path = out / "trials.jsonl"
        candidate_mean_sharpe = sum(r["sharpe_mean"] for r in results) / len(results)
        register_trial(
            trials_path,
            recipe_name=recipe.name,
            config_hash=recipe_config_hash(recipe),
            sharpe=candidate_mean_sharpe,
            created=created.isoformat(),
        )
        sr_trials = cumulative_sr_trials(trials_path)

        # Pooled candidate daily_long: concatenate across windows.
        pooled_daily = pd.concat(all_cand_daily).sort_index()
        aggregate["deflated_sharpe"] = _deflated_sharpe(pooled_daily.to_numpy(), sr_trials)

    (bundle / "stress_summary.json").write_text(
        json.dumps({"recipe": recipe.name, "seeds": seeds, "windows": results, "aggregate": aggregate}, indent=2)
    )

    typer.echo(f"OOS walk-forward — {recipe.name} ({seeds} seeds/window)")
    typer.echo(f"  {'window':10} {'long-only sharpe':>17} {'ls_sharpe':>11}")
    for r in results:
        line = f"  {r['label']:10} {r['sharpe_mean']:>17.3f} {r['ls_sharpe_mean']:>11.3f}"
        if "delta_sharpe" in r:
            ci = r["delta_ci"]
            line += f"  delta={r['delta_sharpe']:+.3f} [{ci['lo']:+.3f},{ci['hi']:+.3f}]"
        typer.echo(line)
    typer.echo(
        f"  L/S Sharpe: {aggregate['ls_sharpe_windows_positive']}/{aggregate['n_windows']} windows positive; "
        f"worst {aggregate['ls_sharpe_worst']:.3f}; mean {aggregate['ls_sharpe_mean_across_windows']:.3f}"
    )
    if "delta_mean_across_windows" in aggregate:
        typer.echo(f"  delta-vs-null (mean across windows): {aggregate['delta_mean_across_windows']:+.3f}")
    if "deflated_sharpe" in aggregate:
        typer.echo(f"  deflated Sharpe: {aggregate['deflated_sharpe']:.4f}")
    typer.echo(f"  bundle: {bundle}")
