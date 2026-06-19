"""Combinatorial purged cross-validation (CPCV) orchestration for the experiment.

Materializes the Alpha158 feature/label matrix once, trains a LightGBM booster
per purged+embargoed split, predicts the held-out rows, stitches predictions into
backtest paths (cli.experiment.cv), backtests each path via qlib's signal-driven
`backtest()`, and aggregates a Sharpe distribution (+ rank-IC).

The holdout run is `scaffold.run_experiment` (unchanged); this module is the CV
layer that runs before it. It uses no MLflow recorder.
"""

from __future__ import annotations

import contextlib
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cli.experiment.cache import ensure_cache_fresh
from cli.experiment.cv import assemble_paths, build_cv_plan
from cli.experiment.recipes.base import Recipe
from cli.experiment.scaffold import exchange_kwargs, handler_config, redis_preflight, strategy_config_with_signal
from cli.logging import get_logger

logger = get_logger("experiment.cpcv")

_METRICS = ["annualized_return", "information_ratio", "max_drawdown"]


@dataclass
class CPCVResult:
    meta: dict  # n_groups, test_groups, n_splits, n_paths, purge_days, embargo_days, span
    paths: list  # [{"path": i, "sharpe": .., "annualized_return": .., "max_drawdown": ..}]
    distribution: dict  # sharpe_mean / sharpe_std / sharpe_median / sharpe_worst
    rank_ic: dict  # mean / std / ir


def _lgb_params(recipe: Recipe) -> tuple[dict, int]:
    """Translate the recipe's LGBModel config into raw lightgbm params + num_boost_round.

    Mirrors qlib.contrib.model.gbdt.LGBModel.__init__: loss -> objective, verbosity
    -1, the rest forwarded; num_boost_round / early_stopping_rounds are pulled out
    (early stopping is intentionally disabled inside CV folds — fixed rounds).
    """
    kw = dict(recipe.model_config.get("kwargs", {}))
    num_boost_round = int(kw.pop("num_boost_round", 1000))
    kw.pop("early_stopping_rounds", None)
    loss = kw.pop("loss", "mse")
    params = {"objective": loss, "verbosity": -1, **kw}
    return params, num_boost_round


def _materialize_span(recipe: Recipe, start: str, end: str):
    """Return (infer_df, learn_df) over ``[start..end]``, MultiIndex (datetime, instrument).

    Uses CS_RAW (multi-level columns) so df["feature"] and df["label"] work.
    infer_df (DK_I): normalized features + label — used for prediction.
    learn_df (DK_L): normalized features + per-day-normalized label, NaN-label rows
    dropped — used for training and rank-IC.

    Leakage precondition: normalization (RobustZScoreNorm) is fit ONCE over the full
    span (fit_start_time..fit_end_time below), which is leakage-free for GBDT models
    because they are invariant to per-feature monotone affine transforms. A future
    linear/NN recipe or a feature-mixing processor would need per-fold normalization
    to stay leakage-free.

    CPCV fits over train+valid; walk-forward (cli.experiment.walkforward) fits over
    each period's [train_start..predict_end] — both go through this one builder.
    """
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.utils import init_instance_by_config

    dataset = init_instance_by_config(
        {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": handler_config(
                    recipe.feature_config,
                    instruments=recipe.universe,
                    start=start,
                    end=end,
                    fit_start=start,
                    fit_end=end,
                    handler_kwargs=recipe.handler_kwargs,
                ),
                "segments": {"all": (start, end)},
            },
        }
    )
    # CS_RAW preserves the MultiIndex columns (feature/*  label/*) so df["feature"] / df["label"] work.
    infer_df = dataset.prepare(segments="all", col_set=DataHandlerLP.CS_RAW, data_key=DataHandlerLP.DK_I)
    learn_df = dataset.prepare(segments="all", col_set=DataHandlerLP.CS_RAW, data_key=DataHandlerLP.DK_L)
    return infer_df, learn_df


def _materialize(recipe: Recipe):
    """CPCV materialization: (infer_df, learn_df) over the train+valid span."""
    return _materialize_span(recipe, recipe.segments["train"][0], recipe.segments["valid"][1])


def _split_xy(df: pd.DataFrame):
    """Split a CS_RAW frame into (feature DataFrame, label Series).

    Alpha158 columns are MultiIndex: top level is "feature" or "label";
    label sub-column is "LABEL0".
    """
    feat = df["feature"]
    label_block = df["label"]
    # label_block is a DataFrame with one column (LABEL0); flatten to Series.
    label = label_block.iloc[:, 0] if isinstance(label_block, pd.DataFrame) else label_block
    return feat, label


def _rows_on(df: pd.DataFrame, dates: set):
    return df[df.index.get_level_values(0).isin(dates)]


def _rank_ic(pred: pd.Series, label: pd.Series) -> float:
    """Mean per-day Spearman rank correlation of pred vs label (NaN-safe)."""
    joined = pd.DataFrame({"p": pred, "y": label}).dropna()
    if joined.empty:
        return float("nan")
    daily = joined.groupby(level=0).apply(lambda g: g["p"].corr(g["y"], method="spearman") if len(g) > 1 else float("nan"))
    return float(daily.mean())


def run_cpcv(recipe: Recipe, *, data_dir: Path, refresh_cache: bool = False) -> CPCVResult:
    import lightgbm as lgb
    import qlib
    from qlib.backtest import backtest
    from qlib.constant import REG_US
    from qlib.contrib.evaluate import risk_analysis

    data_dir = Path(data_dir).resolve()

    redis_preflight()
    ensure_cache_fresh(data_dir, refresh=refresh_cache)

    # Defensive cwd isolation: qlib's FileLock and git-probe run relative to CWD; CPCV uses no MLflow recorder.
    with tempfile.TemporaryDirectory(prefix="zcrypto-cpcv-cwd-") as cwd_tmp, contextlib.chdir(cwd_tmp):
        qlib.init(
            provider_uri=str(data_dir),
            region=REG_US,
            expression_cache="DiskExpressionCache",
            dataset_cache="DiskDatasetCache",
            logging_config=None,
        )
        logger.info("cpcv-init", extra={"provider_uri": str(data_dir)})

        infer_df, learn_df = _materialize(recipe)
        infer_feat, _ = _split_xy(infer_df)
        learn_feat, learn_label = _split_xy(learn_df)

        calendar = sorted(infer_feat.index.get_level_values(0).unique())
        plan = build_cv_plan(
            calendar,
            n_groups=recipe.cv_n_groups,
            test_groups=recipe.cv_test_groups,
            purge_days=recipe.label_horizon_days,
            embargo_days=recipe.feature_lookback_days,
        )
        logger.info(
            "cpcv-start",
            extra={
                "n_groups": plan.n_groups,
                "test_groups": plan.test_groups,
                "n_splits": len(plan.splits),
                "n_paths": plan.n_paths,
            },
        )

        params, num_boost_round = _lgb_params(recipe)
        predictions: dict = {}
        ic_values: list = []
        for i, split in enumerate(plan.splits):
            train_dates, test_dates = set(split.train_dates), set(split.test_dates)
            x_tr = _rows_on(learn_feat, train_dates)
            y_tr = _rows_on(learn_label, train_dates)
            booster = lgb.train(params, lgb.Dataset(x_tr.values, label=y_tr.values), num_boost_round=num_boost_round)

            x_te = _rows_on(infer_feat, test_dates)
            pred = pd.Series(booster.predict(x_te.values), index=x_te.index)
            predictions[i] = pred
            ic_values.append(_rank_ic(pred, _rows_on(learn_label, test_dates)))
            logger.info("split-trained", extra={"split": i, "n_train": len(x_tr), "n_test": len(x_te)})

        paths_pred = assemble_paths(plan, predictions)
        logger.info("paths-assembled", extra={"n_paths": len(paths_pred)})

        path_rows = []
        for j, signal in enumerate(paths_pred):
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
            # The portfolio_metric_dict key is built as "{}{}".format(*Freq.parse(time_per_step));
            # "day" parses to (1, "day") → key "1day". Fall back to first key for safety.
            pmd_key = "1day" if "1day" in pmd else next(iter(pmd))
            report_df = pmd[pmd_key][0]
            ra = risk_analysis(report_df["return"] - report_df["cost"], freq="day")
            m = {k: float(ra.loc[k].iloc[0]) for k in _METRICS}
            path_rows.append(
                {
                    "path": j,
                    "sharpe": m["information_ratio"],
                    "annualized_return": m["annualized_return"],
                    "max_drawdown": m["max_drawdown"],
                }
            )
            logger.info("path-backtest", extra={"path": j, "sharpe": m["information_ratio"]})

    sharpes = [r["sharpe"] for r in path_rows]
    ics = pd.Series([v for v in ic_values if not math.isnan(v)], dtype="float64")
    distribution = {
        "sharpe_mean": float(pd.Series(sharpes).mean()),
        "sharpe_std": float(pd.Series(sharpes).std()),
        "sharpe_median": float(pd.Series(sharpes).median()),
        "sharpe_worst": float(min(sharpes)),
    }
    rank_ic = {
        "mean": float(ics.mean()) if not ics.empty else float("nan"),
        "std": float(ics.std()) if not ics.empty else float("nan"),
        "ir": float(ics.mean() / ics.std()) if len(ics) > 1 and ics.std() else float("nan"),
    }
    meta = {
        "method": "CPCV",
        "n_groups": plan.n_groups,
        "test_groups": plan.test_groups,
        "n_splits": len(plan.splits),
        "n_paths": plan.n_paths,
        "purge_days": plan.purge_days,
        "embargo_days": plan.embargo_days,
        "span": [str(calendar[0]), str(calendar[-1])],
    }
    logger.info("cv-aggregated", extra={"distribution": distribution, "rank_ic": rank_ic})
    return CPCVResult(meta=meta, paths=path_rows, distribution=distribution, rank_ic=rank_ic)
