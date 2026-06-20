"""`zcrypto experiment` — run a recipe and write a predict-ready run bundle."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

# Light import (base.py only pulls importlib/dataclasses/pathlib) — kept at module
# level so tests can monkeypatch `cli.experiment.command.resolve_recipe`, and so the
# unknown-recipe path never touches qlib/redis.
from cli.config import ConfigError, load_config, resolve_data_dir
from cli.experiment.caveats import EXPERIMENT_CAVEATS, PIT_MARKER, POINT_IN_TIME, SURVIVORSHIP_MARKER
from cli.experiment.recipes.base import resolve_recipe, with_pit_universe


def experiment(
    recipe_name: str = typer.Option(
        "skeleton",
        "--recipe",
        help="Recipe name to run (see cli/experiment/recipes).",
    ),
    data_dir: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--data-dir",
        help="Qlib provider directory. Defaults to [zcrypto].data_dir in zcrypto.toml.",
    ),
    out: Path = typer.Option(
        Path("runs"),
        "--out",
        help="Root directory for run bundles; the bundle lands at <out>/<recipe>/<UTC timestamp>.",
    ),
    svg: bool = typer.Option(
        False,
        "--svg/--no-svg",
        help="Also render report.svg (requires kaleido).",
    ),
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache/--no-refresh-cache",
        help="Force-wipe qlib's on-disk feature/dataset cache before the run.",
    ),
    quick: bool = typer.Option(
        False,
        "--quick/--no-quick",
        help="Skip CPCV; run only the single train→backtest holdout (today's fast path).",
    ),
    open_report: bool = typer.Option(
        None,
        "--open/--no-open",
        help="Open report.html in a browser when done. Defaults to on only when stdout is a TTY.",
    ),
    seeds: int = typer.Option(
        1,
        "--seeds",
        help="Number of seeds for the holdout distribution. When >1, runs the holdout N times (seeds 1…N) and writes holdout_seeds.json.",
        min=1,
    ),
    deterministic: bool = typer.Option(
        False,
        "--deterministic/--no-deterministic",
        help="Run in fully deterministic mode (seed=1, LightGBM force_row_wise). Reproduces the same result on repeated runs.",
    ),
    pit_universe: bool = typer.Option(
        False,
        "--pit-universe/--no-pit-universe",
        help="Expand the recipe's universe to point-in-time membership (adds the ever-top-25 "
        "delisted/faded majors) for a survivorship-free run. Default off.",
    ),
    fees_only: bool = typer.Option(
        False,
        "--fees-only/--no-fees-only",
        help="Use the fees-only cost model (raw fee_preset, no slippage/maker-fill) instead of the "
        "default calibrated realistic costs. The A/B baseline for the execution-cost re-measure.",
    ),
) -> None:
    """Run a recipe end-to-end and write a predict-ready run bundle."""
    # Deferred so `zcrypto --help`/`--version` stay fast (qlib import is ~1s) and
    # the unknown-recipe path below never needs redis/qlib.
    import dataclasses
    import json
    import shutil
    import subprocess
    from datetime import datetime, timezone
    from importlib.metadata import PackageNotFoundError, version

    from cli.experiment.report import build_report, write_report
    from cli.experiment.stats import psr
    from cli.experiment.trades import trade_summary, trades_from_positions
    from cli.logging import get_logger

    logger = get_logger("experiment.command")

    try:
        recipe = resolve_recipe(recipe_name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    logger.info("recipe-resolved", extra={"recipe": recipe.name})
    if pit_universe:
        recipe = with_pit_universe(recipe)
    caveats = [POINT_IN_TIME] if pit_universe else EXPERIMENT_CAVEATS
    marker = PIT_MARKER if pit_universe else SURVIVORSHIP_MARKER
    if fees_only:
        recipe = dataclasses.replace(recipe, fees_only=True)
    cost_model = "fees-only (no slippage/maker-fill)" if fees_only else "realistic (calibrated slippage + maker-fill)"

    try:
        data_dir = resolve_data_dir(data_dir, load_config()).resolve()
    except ConfigError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if open_report is None:
        open_report = sys.stdout.isatty()

    created = datetime.now(timezone.utc)
    bundle = out / recipe.name / created.strftime("%Y%m%dT%H%M%SZ")
    bundle.mkdir(parents=True, exist_ok=True)

    # Resolve seed: only set under --deterministic (preserves today's default behavior byte-exactly).
    seed = 1 if deterministic else None

    # --- CPCV (before holdout, skipped under --quick) ------------------------
    cv_result = None
    if not quick:
        from cli.experiment.cpcv import run_cpcv

        cv_result = run_cpcv(recipe, data_dir=data_dir, refresh_cache=refresh_cache, seed=seed, deterministic=deterministic)
        logger.info("cpcv-done", extra={"n_paths": cv_result.meta["n_paths"]})

    # Heavy: imports + runs qlib. Deferred until after the cheap unknown-recipe path.
    from cli.experiment.scaffold import run_experiment

    result = run_experiment(
        recipe, data_dir=data_dir, out_dir=bundle, refresh_cache=refresh_cache, seed=seed, deterministic=deterministic
    )
    logger.info("run-done", extra={"run_id": result.run_id, "ending_value": result.ending_value})

    holdout_returns = result.report_df["return"] - result.report_df["cost"]
    holdout_psr = psr(holdout_returns.to_numpy())

    # --- report.html (+ report.svg) ------------------------------------------
    holdout_sharpe = result.metrics.get("strategy_absolute", {}).get("information_ratio", float("nan"))
    cv_arg = None
    if cv_result is not None:
        cv_arg = {
            "path_sharpes": [p["sharpe"] for p in cv_result.paths],
            "holdout_sharpe": holdout_sharpe,
            "holdout_psr": holdout_psr,
        }
    fig = build_report(result, cv=cv_arg, marker=marker)
    write_report(fig, bundle, svg=svg)

    # --- metrics.json --------------------------------------------------------
    (bundle / "metrics.json").write_text(
        json.dumps(
            {"ending_value": result.ending_value, "account": recipe.account, "metrics": result.metrics},
            indent=2,
        )
    )

    # --- returns.csv (holdout cost-adjusted daily returns; consumed by `zcrypto rank`) ---
    _ret = holdout_returns.rename("ret")
    _ret.index.name = "date"
    _ret.to_csv(bundle / "returns.csv")

    # --- cv_results.json (only when CPCV ran) --------------------------------
    if cv_result is not None:
        # Two Sharpe scales: holdout["sharpe"] is the *annualized* absolute Sharpe (qlib
        # information_ratio); holdout["psr"] is computed on the *per-period daily* returns
        # (PSR carries its own length correction).
        holdout = {
            **{m: result.metrics.get("strategy_absolute", {}).get(m, float("nan")) for m in ("annualized_return", "max_drawdown")},
            "sharpe": holdout_sharpe,  # strategy_absolute IR (cost-adj, rf=0) — matches the CPCV path Sharpes
            "psr": holdout_psr,  # P(true holdout Sharpe > 0), corrected for length + non-normality
            # excess-return-vs-benchmark IR
            "information_ratio": result.metrics.get("excess_return_with_cost", {}).get("information_ratio", float("nan")),
            "ending_value": result.ending_value,
        }
        (bundle / "cv_results.json").write_text(
            json.dumps(
                {
                    "cv": cv_result.meta,
                    "paths": cv_result.paths,
                    "distribution": cv_result.distribution,
                    "rank_ic": cv_result.rank_ic,
                    "holdout": holdout,
                },
                indent=2,
            )
        )

    # --- trades.csv ----------------------------------------------------------
    trades = trades_from_positions(result.positions)
    (bundle / "trades.csv").write_text(trades.to_csv(index=False))

    # --- recipe_snapshot.json ------------------------------------------------
    (bundle / "recipe_snapshot.json").write_text(json.dumps(dataclasses.asdict(recipe), indent=2))

    # --- run_meta.json -------------------------------------------------------
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        git_commit = "unknown"

    def _pkg_version(pkg: str) -> str:
        try:
            return version(pkg)
        except PackageNotFoundError:
            return "unknown"

    run_meta = {
        "recipe": recipe.name,
        "created_at": created.isoformat(),
        "run_id": result.run_id,
        "git_commit": git_commit,
        "python": sys.version,
        "pyqlib": _pkg_version("pyqlib"),
        "lightgbm": _pkg_version("lightgbm"),
        "account": recipe.account,
        "benchmark": recipe.benchmark,
        "fee_preset": recipe.fee_preset,
        "cost_model": {
            "fees_only": recipe.fees_only,
            "impact_cost": recipe.impact_cost,
            "maker_fill_haircut": recipe.maker_fill_haircut,
        },
        "segments": recipe.segments,
        "universe": list(recipe.universe),
        "reference_instruments": list(recipe.reference_instruments),
        "index_fingerprint": result.data_fingerprint,
        "ending_value": result.ending_value,
        "caveats": caveats,
    }
    (bundle / "run_meta.json").write_text(json.dumps(run_meta, indent=2))

    # --- model.pkl -----------------------------------------------------------
    # qlib's R.save_objects(trained_model=model) writes it under
    # <recorder_dir>/artifacts/trained_model. Locate robustly, then copy.
    model_src = result.recorder_dir / "artifacts" / "trained_model"
    if not model_src.exists():
        matches = sorted(result.recorder_dir.glob("artifacts/**/trained_model*"))
        model_src = matches[0] if matches else None
    if model_src is not None and model_src.exists():
        shutil.copy2(model_src, bundle / "model.pkl")
        logger.info("model-copied", extra={"src": str(model_src), "dst": str(bundle / "model.pkl")})
    else:
        logger.warning("model-not-found", extra={"recorder_dir": str(result.recorder_dir)})

    logger.info("bundle-written", extra={"bundle": str(bundle)})

    # --- holdout_seeds.json (only when --seeds N > 1) ------------------------
    if seeds > 1:
        from cli.experiment.multiseed import run_holdout_seeds

        holdout_seeds_result = run_holdout_seeds(recipe, data_dir=data_dir, seeds=seeds, deterministic=deterministic)
        (bundle / "holdout_seeds.json").write_text(json.dumps(holdout_seeds_result, indent=2))
        logger.info("holdout-seeds", extra={"n_seeds": seeds, "summary": holdout_seeds_result["summary"]})

    # --- human summary -------------------------------------------------------
    summary = trade_summary(trades)
    excess = result.metrics.get("excess_return_with_cost", {})

    typer.echo(f"{recipe.account:,.0f} -> {result.ending_value:,.0f} USDT")
    typer.echo(f"  annualized_return : {excess.get('annualized_return', float('nan')):+.4f}")
    typer.echo(f"  max_drawdown      : {excess.get('max_drawdown', float('nan')):+.4f}")
    typer.echo(f"  information_ratio : {excess.get('information_ratio', float('nan')):+.4f}")
    typer.echo(f"  holdout PSR       : {holdout_psr:+.3f}")
    typer.echo(f"  trades            : {summary['total']} ({summary['buys']} buy / {summary['sells']} sell)")
    if cv_result is not None:
        d = cv_result.distribution
        typer.echo(
            f"  CPCV ({cv_result.meta['n_paths']} paths, train+valid): "
            f"Sharpe {d['sharpe_mean']:.2f} ± {d['sharpe_std']:.2f} (worst {d['sharpe_worst']:.2f}) · "
            f"rank-IC {cv_result.rank_ic['mean']:.3f}"
        )
    typer.echo(f"  cost model         : {cost_model}")
    typer.echo(f"⚠ {marker}")
    typer.echo(f"  bundle            : {bundle}")

    if open_report:
        import webbrowser

        webbrowser.open((bundle / "report.html").resolve().as_uri())
