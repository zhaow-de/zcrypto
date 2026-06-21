"""Walk-forward holdout: pure period splitter + periodic-retraining runner.

`build_wf_periods` is the pure (no-qlib) splitter. `run_walkforward_holdout` is the
qlib-backed runner: for each walk-forward period it fits a fresh LightGBM booster on
the period's train range, predicts the period, backtests it, and stitches the
per-period daily report_df into one continuous holdout — the drop-in replacement for
`scaffold.run_experiment`'s single-fit holdout when `recipe.wf_enabled` is true.
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

import pandas as pd

from cli.data.index import compute_sha256
from cli.experiment.cache import ensure_cache_fresh, record_fingerprint
from cli.experiment.recipes.base import Recipe
from cli.logging import get_logger

logger = get_logger("experiment.walkforward")


def build_wf_periods(
    train_start: str,
    test_start: str,
    test_end: str,
    *,
    freq: str = "quarter",
    window: str = "expanding",
    rolling_years: int = 3,
    purge_days: int = 0,
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Split the holdout window into walk-forward retrain periods.

    Parameters
    ----------
    train_start:
        Earliest date of training data (ISO YYYY-MM-DD).
    test_start:
        First date of the holdout / predict window (inclusive).
    test_end:
        Last date of the holdout / predict window (inclusive, clamped).
    freq:
        Granularity of each period — ``"quarter"`` or ``"year"``.
    window:
        ``"expanding"`` keeps train_start fixed; ``"rolling"`` sets
        train_start = predict_start − rolling_years.
    rolling_years:
        Look-back length for rolling window (ignored when expanding).
    purge_days:
        Gap days between train_end and predict_start.
        train_end = predict_start − (purge_days + 1).

    Returns
    -------
    list of ((train_start, train_end), (predict_start, predict_end))
        All dates as ISO ``YYYY-MM-DD`` strings.
    """
    ts_start = pd.Timestamp(test_start)
    ts_end = pd.Timestamp(test_end)

    # Build the sequence of predict periods by iterating calendar periods.
    pd_freq = "Q" if freq == "quarter" else "Y"
    first_period = pd.Period(ts_start, freq=pd_freq)
    last_period = pd.Period(ts_end, freq=pd_freq)

    periods: list[tuple[tuple[str, str], tuple[str, str]]] = []
    p = first_period
    while p <= last_period:
        predict_start = max(pd.Timestamp(p.start_time.date()), ts_start)
        predict_end_raw = pd.Timestamp(p.end_time.date())
        predict_end = min(predict_end_raw, ts_end)

        gap = pd.Timedelta(days=purge_days + 1)
        train_end = predict_start - gap

        if window == "rolling":
            eff_train_start = predict_start - pd.DateOffset(years=rolling_years)
        else:
            eff_train_start = pd.Timestamp(train_start)

        periods.append(
            (
                (eff_train_start.strftime("%Y-%m-%d"), train_end.strftime("%Y-%m-%d")),
                (predict_start.strftime("%Y-%m-%d"), predict_end.strftime("%Y-%m-%d")),
            )
        )
        p += 1

    return periods


def run_walkforward_holdout(
    recipe: Recipe, *, data_dir: Path, refresh_cache: bool = False, seed: int | None = None, deterministic: bool = False
):
    """Periodic-retraining holdout that returns a single-fit-compatible RunResult.

    For each ``build_wf_periods`` period: materialize Alpha158 over
    ``[train_start..predict_end]``, fit a fresh LightGBM booster on the train rows
    (cpcv-style fixed rounds, no early stopping), predict the period's rows, and
    backtest the period via qlib's signal-driven ``backtest()``. The per-period
    ``report_df`` (return/cost/bench) are concatenated, sorted, and de-duplicated
    into one contiguous holdout, from which the same metrics / account_curve /
    benchmark_curve the single-fit path produces are derived.

    Positions are NOT collected: qlib's ``backtest()`` returns
    ``(portfolio_metric_dict, indicator_dict)`` and does not readily expose per-day
    Position snapshots, so the wf RunResult carries empty ``positions`` (and
    ``trades.csv`` is consequently empty for wf runs — the report and ``zcrypto
    rank``/PSR render from report_df / returns.csv, which are fully populated).
    """
    import lightgbm as lgb
    import qlib
    from qlib.backtest import backtest
    from qlib.constant import REG_US
    from qlib.contrib.evaluate import risk_analysis

    # Imported here (not at module top) so the pure splitter above stays qlib-free.
    from cli.experiment.cpcv import _lgb_params, _materialize_span, _rows_on, _split_xy
    from cli.experiment.scaffold import (
        RunResult,
        _context_prices,
        _extract_metrics,
        exchange_kwargs,
        redis_preflight,
        strategy_config_with_signal,
    )

    data_dir = Path(data_dir).resolve()

    redis_preflight()
    ensure_cache_fresh(data_dir, refresh=refresh_cache)

    periods = build_wf_periods(
        recipe.segments["train"][0],
        recipe.segments["test"][0],
        recipe.segments["test"][1],
        freq=recipe.wf_retrain_freq,
        window=recipe.wf_window,
        rolling_years=recipe.wf_rolling_years,
        purge_days=recipe.label_horizon_days,
    )
    logger.info("wf-periods", extra={"recipe": recipe.name, "n_periods": len(periods)})

    params, num_boost_round = _lgb_params(recipe, seed=seed, deterministic=deterministic)

    # Defensive cwd isolation: qlib's FileLock and git-probe run relative to CWD; the wf
    # runner uses no MLflow recorder (it backtests directly, like CPCV).
    with tempfile.TemporaryDirectory(prefix="zcrypto-wf-cwd-") as cwd_tmp, contextlib.chdir(cwd_tmp):
        qlib.init(
            provider_uri=str(data_dir),
            region=REG_US,
            expression_cache="DiskExpressionCache",
            dataset_cache="DiskDatasetCache",
            logging_config=None,
        )
        logger.info("wf-init", extra={"provider_uri": str(data_dir)})

        period_reports: list[pd.DataFrame] = []
        for i, ((train_start, train_end), (predict_start, predict_end)) in enumerate(periods):
            infer_df, learn_df = _materialize_span(recipe, train_start, predict_end)
            infer_feat, _ = _split_xy(infer_df)
            learn_feat, learn_label = _split_xy(learn_df)

            train_dates = {d for d in learn_feat.index.get_level_values(0).unique() if train_start <= str(d.date()) <= train_end}
            predict_dates = {
                d for d in infer_feat.index.get_level_values(0).unique() if predict_start <= str(d.date()) <= predict_end
            }
            x_tr = _rows_on(learn_feat, train_dates)
            y_tr = _rows_on(learn_label, train_dates)
            booster = lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)

            x_pe = _rows_on(infer_feat, predict_dates)
            signal = pd.Series(booster.predict(x_pe.values), index=x_pe.index).sort_index()
            logger.info(
                "wf-period-trained",
                extra={"period": i, "predict": [predict_start, predict_end], "n_train": len(x_tr), "n_predict": len(x_pe)},
            )

            dates = signal.index.get_level_values(0)
            pmd, _ = backtest(
                start_time=dates.min(),
                end_time=dates.max(),
                strategy=strategy_config_with_signal(recipe.strategy_config, signal),
                executor={
                    "class": "SimulatorExecutor",
                    "module_path": "qlib.backtest.executor",
                    "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
                },
                benchmark=recipe.benchmark,
                account=recipe.account,
                exchange_kwargs=exchange_kwargs(recipe),
            )
            pmd_key = "1day" if "1day" in pmd else next(iter(pmd))
            period_reports.append(pmd[pmd_key][0])
            logger.info("wf-period-backtest", extra={"period": i, "n_rows": len(pmd[pmd_key][0])})

        # Stitch the per-period daily reports into one contiguous holdout. Each period's
        # backtest restarts from all-cash (positions are not carried across retrains), so
        # every period boundary has a cold-start seam: a near-flat first day + a re-entry
        # cost, and the prior period's liquidation cost is not charged. This mirrors how
        # CPCV backtests independent paths; metrics stay finite and directionally meaningful.
        report_df = pd.concat(period_reports).sort_index()
        report_df = report_df[~report_df.index.duplicated(keep="first")]

        # Reconstruct the single-fit analysis_df shape from the stitched report so
        # _extract_metrics produces the identical metrics dict (matches PortAnaRecord).
        analysis_df = pd.concat(
            {
                "excess_return_without_cost": risk_analysis(report_df["return"] - report_df["bench"], freq="day"),
                "excess_return_with_cost": risk_analysis(report_df["return"] - report_df["bench"] - report_df["cost"], freq="day"),
            }
        )
        metrics = _extract_metrics(analysis_df, report_df)
        logger.info("wf-metrics", extra={"metrics": metrics})

        account_curve = recipe.account * (1 + report_df["return"]).cumprod()
        benchmark_curve = recipe.account * (1 + report_df["bench"]).cumprod()
        context_prices = _context_prices(recipe)

    record_fingerprint(data_dir)
    data_fingerprint = compute_sha256(data_dir / "index.json")

    ending_value = float(account_curve.iloc[-1])
    logger.info("wf-done", extra={"n_periods": len(periods), "ending_value": ending_value})

    return RunResult(
        metrics=metrics,
        report_df=report_df,
        positions={},  # see docstring: backtest() does not readily expose positions
        analysis_df=analysis_df,
        account_curve=account_curve,
        benchmark_curve=benchmark_curve,
        context_prices=context_prices,
        ending_value=ending_value,
        run_id="walkforward",
        recorder_dir=data_dir,  # no MLflow recorder; downstream model.pkl copy is skipped
        recipe=recipe,
        data_fingerprint=data_fingerprint,
        wf_periods=len(periods),
    )
