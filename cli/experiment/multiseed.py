"""Multi-seed holdout runner + pure metric aggregation and separation utilities.

The aggregation helpers (``summarize_seed_metrics``, ``separation``) are pure —
numpy/stdlib only. ``run_holdout_seeds`` (and its ``_holdout_*`` seams) fits the
holdout once per seed and aggregates the per-seed metrics; its qlib imports are
deferred INSIDE the functions so importing this module stays qlib-free.
"""

from __future__ import annotations

import contextlib
import math
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from cli.logging import get_logger

logger = get_logger("experiment.multiseed")


def summarize_seed_metrics(per_seed: list[dict]) -> dict:
    """Aggregate per-seed metric dicts into per-metric distribution stats.

    Args:
        per_seed: list of per-seed metric dicts. Only scalar metric values (``ending_value``,
            ``sharpe``, ``psr``, ``max_drawdown``, ``ls_sharpe``, ``ls_ending``) are summarized;
            non-scalar fields (e.g. the ``daily_long`` / ``daily_ls`` Series) are skipped.

    Returns:
        ``{metric: {"mean": float, "std": float, "min": float, "max": float, "n": int}}``
        Std uses sample std (ddof=1) for n > 1, 0.0 for n == 1.
    """
    if not per_seed:
        return {}
    metrics = list(per_seed[0].keys())
    result = {}
    for m in metrics:
        first = per_seed[0][m]
        # Skip non-scalar fields (e.g. pandas Series carrying daily return series).
        if not isinstance(first, (int, float)):
            continue
        # A degenerate window (e.g. a fully gated-to-cash regime arm) yields a constant return
        # series -> Sharpe/PSR are 0/0 = nan/inf, which crashes statistics.stdev. Map any
        # non-finite metric to 0.0 (an all-cash window has no risk-adjusted edge).
        vals = [v if math.isfinite(v) else 0.0 for v in (d[m] for d in per_seed)]
        n = len(vals)
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if n > 1 else 0.0
        result[m] = {"mean": mean, "std": std, "min": min(vals), "max": max(vals), "n": n}
    return result


def separation(a: dict, b: dict, metric: str = "sharpe") -> dict:
    """Measure whether recipe *a*'s distribution is separated from *b*'s beyond seed noise.

    Args:
        a: summary dict from :func:`summarize_seed_metrics` for recipe a.
        b: summary dict from :func:`summarize_seed_metrics` for recipe b.
        metric: the metric key to compare (default ``"sharpe"``).

    Returns:
        ``{"mean_gap": float, "pooled_std": float, "z": float}``
        where ``z = mean_gap / pooled_std`` (positive → a above b).
        Divide-by-zero guard: pooled_std == 0 and mean_gap != 0 → z = inf;
        pooled_std == 0 and mean_gap == 0 → z = 0.0.
    """
    std_a = a[metric]["std"]
    std_b = b[metric]["std"]
    mean_gap = a[metric]["mean"] - b[metric]["mean"]
    pooled_std = math.sqrt((std_a**2 + std_b**2) / 2)
    if pooled_std == 0.0:
        z = float("inf") if mean_gap != 0.0 else 0.0
    else:
        z = mean_gap / pooled_std
    return {"mean_gap": mean_gap, "pooled_std": pooled_std, "z": z}


@dataclass
class _HoldoutContext:
    """One-time qlib state reused across the N seed fits.

    ``infer_feat`` / ``learn_feat`` / ``learn_label`` are the materialized Alpha158
    feature/label matrices over ``[train_start..test_end]`` (built once); ``train_dates``
    / ``predict_dates`` are the train / holdout date sets. ``_cm`` is the open
    cwd-isolation + qlib-session contextmanager (closed by :func:`run_holdout_seeds`).
    """

    infer_feat: object
    learn_feat: object
    learn_label: object
    train_dates: set
    predict_dates: set
    _cm: object  # ExitStack kept open across the seed loop; closed in run_holdout_seeds
    fwd_ret: object = field(default=None)  # 1-day-forward $close-return Series (datetime, instrument); for the L/S spread


def _holdout_context(recipe, data_dir, deterministic):
    """Initialize qlib once and materialize the holdout feature matrices.

    Mirrors ``walkforward.run_walkforward_holdout``'s cwd-isolation + ``qlib.init``
    pattern: enters a throwaway CWD (qlib's FileLock + git-probe run relative to it),
    inits qlib over *data_dir*, runs the redis/cache preflight, and materializes the
    Alpha158 features once over the single holdout "period" (train=``segments['train']``,
    predict=``segments['test']``). The returned context is reused across all N seeds; the
    cwd/qlib session stays open until :func:`run_holdout_seeds` closes ``ctx._cm``.

    ``deterministic`` is accepted for seam-signature symmetry (the brief's monkeypatch
    stubs this exact signature) but isn't used here — qlib.init / materialization don't
    depend on it; determinism is applied per-seed via ``_lgb_params`` in ``_light_holdout``.
    """
    import qlib
    from qlib.constant import REG_US

    from cli.experiment.cache import ensure_cache_fresh
    from cli.experiment.cpcv import _materialize_span, _split_xy
    from cli.experiment.scaffold import redis_preflight

    data_dir = Path(data_dir).resolve()
    redis_preflight()
    ensure_cache_fresh(data_dir, refresh=False)

    train_start, train_end = recipe.segments["train"]
    predict_start, predict_end = recipe.segments["test"]

    # ExitStack keeps the cwd-isolation + qlib session OPEN across the seed loop while
    # staying exception-safe: any failure during init/materialize below unwinds the whole
    # stack here (no leaked tempdir / dangling chdir); on success the stack becomes ctx._cm,
    # closed by run_holdout_seeds. Same cwd-isolation rationale as walkforward.run_*.
    stack = contextlib.ExitStack()
    try:
        cwd_tmp = stack.enter_context(tempfile.TemporaryDirectory(prefix="zcrypto-holdout-cwd-"))
        stack.enter_context(contextlib.chdir(cwd_tmp))

        qlib.init(
            provider_uri=str(data_dir),
            region=REG_US,
            expression_cache="DiskExpressionCache",
            dataset_cache="DiskDatasetCache",
            logging_config=None,
        )
        logger.info("holdout-seeds-init", extra={"provider_uri": str(data_dir)})

        # One "period" spans train=segments['train'], predict=segments['test'] (cf. walkforward).
        infer_df, learn_df = _materialize_span(recipe, train_start, predict_end)
        infer_feat, _ = _split_xy(infer_df)
        learn_feat, learn_label = _split_xy(learn_df)

        train_dates = {d for d in learn_feat.index.get_level_values(0).unique() if train_start <= str(d.date()) <= train_end}
        predict_dates = {d for d in infer_feat.index.get_level_values(0).unique() if predict_start <= str(d.date()) <= predict_end}

        from qlib.data import D

        predict_close = D.features(list(recipe.universe), ["$close"], start_time=predict_start, end_time=predict_end, freq="day")[
            "$close"
        ]
        wide_close = predict_close.unstack(level="instrument")
        fwd_ret = (wide_close.shift(-1) / wide_close - 1.0).stack(future_stack=True)
        fwd_ret.index.names = ["datetime", "instrument"]
    except BaseException:
        stack.close()
        raise

    return _HoldoutContext(
        infer_feat=infer_feat,
        learn_feat=learn_feat,
        learn_label=learn_label,
        train_dates=train_dates,
        predict_dates=predict_dates,
        _cm=stack,
        fwd_ret=fwd_ret,
    )


def _fit_predict(recipe, x_tr, y_tr, x_pe, *, seed, deterministic):
    """Fit the recipe's model on the train matrices and predict the holdout rows.

    LGBM (``model_config["class"] == "LGBModel"``) uses the existing per-seed bagging-RNG path
    verbatim (the multi-seed determinism contract). Any other model is treated as an sklearn-style
    regressor: imported from ``model_config["module_path"]`` and fit/predicted on the raw matrices
    (deterministic models simply yield identical predictions across seeds).
    """
    import numpy as np

    mc = recipe.model_config
    if mc["class"] == "LGBModel":
        import lightgbm as lgb

        from cli.experiment.cpcv import _lgb_params

        params, num_boost_round = _lgb_params(recipe, seed=seed, deterministic=deterministic)
        booster = lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)
        return booster.predict(x_pe.values)

    import importlib

    cls = getattr(importlib.import_module(mc["module_path"]), mc["class"])
    model = cls(**mc.get("kwargs", {}))
    model.fit(x_tr.values, y_tr.values)
    return np.asarray(model.predict(x_pe.values))


def _light_holdout(recipe, *, seed, deterministic, ctx):
    """Fit one LightGBM booster (varying only the bagging RNG via *seed*) and backtest.

    The light single-fit holdout factored out of ``walkforward.run_walkforward_holdout``'s
    per-period block: train on ``ctx.train_dates`` → predict ``ctx.predict_dates`` →
    qlib ``backtest()`` → return the daily ``report_df`` and the prediction ``signal``.
    Reuses the materialized matrices in *ctx*, so qlib.init / materialize happen once across the N seeds.
    """
    import pandas as pd
    from qlib.backtest import backtest

    from cli.experiment.cpcv import _rows_on
    from cli.experiment.scaffold import exchange_kwargs, strategy_config_with_signal

    x_tr = _rows_on(ctx.learn_feat, ctx.train_dates)
    y_tr = _rows_on(ctx.learn_label, ctx.train_dates)
    x_pe = _rows_on(ctx.infer_feat, ctx.predict_dates)
    signal = pd.Series(
        _fit_predict(recipe, x_tr, y_tr, x_pe, seed=seed, deterministic=deterministic),
        index=x_pe.index,
    ).sort_index()
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
    return pmd[pmd_key][0], signal


def _holdout_metrics_for_seed(recipe, seed, deterministic, ctx):
    """Per-seed holdout metrics, using the SAME definitions as the single-fit MLflow holdout.

    Builds the seed's ``report_df`` via :func:`_light_holdout`, then derives:
    - ``ending_value`` — ``account * (1 + report_df['return']).cumprod()`` last value;
    - ``sharpe`` — absolute Sharpe = ``risk_analysis(return - cost).information_ratio``
      (== ``scaffold._extract_metrics``'s ``strategy_absolute.information_ratio``);
    - ``max_drawdown`` — from the same ``risk_analysis`` (== ``strategy_absolute.max_drawdown``);
    - ``psr`` — ``stats.psr`` over the cost-adjusted daily returns (the holdout-PSR helper
      used in ``cli/experiment/command.py`` to write ``holdout.psr`` to ``cv_results.json``).
    """
    from qlib.contrib.evaluate import risk_analysis

    from cli.experiment.longshort import long_short_spread
    from cli.experiment.recipes.base import FEE_PRESETS
    from cli.experiment.stats import psr as _psr

    report_df, signal = _light_holdout(recipe, seed=seed, deterministic=deterministic, ctx=ctx)

    cost_adj = report_df["return"] - report_df["cost"]
    abs_df = risk_analysis(cost_adj, freq="day")
    account_curve = recipe.account * (1 + report_df["return"]).cumprod()

    cost_per_side = FEE_PRESETS[recipe.fee_preset][0] + (0.0 if recipe.fees_only else recipe.maker_fill_haircut)
    ls = long_short_spread(signal, ctx.fwd_ret, k=5, cost_per_side=cost_per_side)

    return {
        "ending_value": float(account_curve.iloc[-1]),
        "sharpe": float(abs_df.loc["information_ratio"].iloc[0]),
        "psr": _psr(cost_adj.to_numpy()),
        "max_drawdown": float(abs_df.loc["max_drawdown"].iloc[0]),
        "ls_sharpe": ls["sharpe"],
        "ls_ending": ls["ending"],
        "daily_long": cost_adj,
        "daily_ls": ls["daily"],
    }


def run_holdout_seeds(recipe, *, data_dir, seeds, deterministic=False) -> dict:
    """Fit the holdout *seeds* times (seeds 1…N) and aggregate the per-seed metrics.

    qlib is initialized + the features materialized ONCE (:func:`_holdout_context`);
    each seed varies only the bagging RNG via ``_lgb_params(recipe, seed=k, ...)`` and
    produces a per-seed metric dict (:func:`_holdout_metrics_for_seed`). Returns
    ``{"per_seed": [{seed, ending_value, sharpe, psr, max_drawdown}, …],
    "summary": summarize_seed_metrics(...)}``.
    """
    ctx = _holdout_context(recipe, data_dir, deterministic)
    try:
        per_seed = []
        for k in range(1, seeds + 1):
            metrics = _holdout_metrics_for_seed(recipe, k, deterministic, ctx)
            per_seed.append({"seed": k, **metrics})
            scalar_metrics = {kk: vv for kk, vv in metrics.items() if isinstance(vv, (int, float))}
            logger.info("holdout-seed-done", extra={"seed": k, "metrics": scalar_metrics})
    finally:
        # Monkeypatched test contexts (a bare object()) carry no _cm; guard for them.
        cm = getattr(ctx, "_cm", None)
        if cm is not None:
            cm.close()

    summary = summarize_seed_metrics([{k: v for k, v in d.items() if k != "seed"} for d in per_seed])
    logger.info("holdout-seeds-aggregated", extra={"n_seeds": len(per_seed), "summary": summary})
    return {"per_seed": per_seed, "summary": summary}


def holdout_seeds_json_safe(result: dict) -> dict:
    """JSON-serializable view of :func:`run_holdout_seeds` output for ``holdout_seeds.json``.

    The per-seed rows carry the ``daily_long`` / ``daily_ls`` pandas Series (kept in-memory for the
    paired bootstrap in ``stress``); those are not JSON-serializable and don't belong in the artifact.
    This drops every non-scalar field, leaving the scalar metric distribution (``seed``, ``ending_value``,
    ``sharpe``, ``psr``, ``max_drawdown``, ``ls_sharpe``, ``ls_ending``) and the ``summary`` unchanged.
    """
    return {
        "per_seed": [{k: v for k, v in row.items() if isinstance(v, (int, float))} for row in result["per_seed"]],
        "summary": result["summary"],
    }
