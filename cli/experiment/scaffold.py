"""Train -> backtest -> extract scaffold for the zcrypto experiment pipeline.

`run_experiment` mirrors the working end-to-end qlib flow in
``cli/example/workflow.py`` but consumes a :class:`Recipe` and returns a rich
:class:`RunResult` for the later trades / report / command tasks.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cli.data.index import compute_sha256
from cli.experiment.cache import ensure_cache_fresh, record_fingerprint
from cli.experiment.recipes.base import FEE_PRESETS, Recipe
from cli.logging import get_logger

logger = get_logger("experiment.scaffold")

# Metrics pulled from risk_analysis / port_analysis output (matches example.workflow).
_METRICS = ["annualized_return", "information_ratio", "max_drawdown"]


def handler_config(feature_config, *, instruments, start, end, fit_start, fit_end, handler_kwargs):
    """Build the full qlib handler config from a recipe's feature_config + runtime kwargs."""
    return {
        **feature_config,
        "kwargs": {
            **handler_kwargs,
            "instruments": list(instruments),
            "start_time": start,
            "end_time": end,
            "fit_start_time": fit_start,
            "fit_end_time": fit_end,
            "freq": "day",
        },
    }


def strategy_config_with_signal(strategy_config: dict, signal) -> dict:
    """Inject the runtime ``signal`` into a recipe's static strategy config."""
    return {**strategy_config, "kwargs": {**strategy_config.get("kwargs", {}), "signal": signal}}


@dataclass
class RunResult:
    """Everything downstream tasks (trades, report, command) need from one run."""

    metrics: dict
    report_df: pd.DataFrame
    positions: object  # mapping {Timestamp -> qlib Position}
    analysis_df: pd.DataFrame
    account_curve: pd.Series
    benchmark_curve: pd.Series
    context_prices: dict[str, pd.Series]
    ending_value: float
    run_id: str
    recorder_dir: Path
    recipe: Recipe
    data_fingerprint: str
    # Walk-forward provenance: None for the single-fit holdout, else the number of
    # retrain periods stitched into report_df (see cli/experiment/walkforward.py).
    wf_periods: int | None = None


def redis_preflight() -> None:
    """Ensure Redis is reachable; qlib's Disk*Cache locks require it."""
    import redis

    port = int(os.environ.get("ZCRYPTO_REDIS_PORT", "6379"))
    try:
        redis.Redis(host="localhost", port=port, socket_connect_timeout=2).ping()
    except Exception as exc:
        raise RuntimeError(f"Redis not reachable at localhost:{port}; start it with `scripts/redis.sh start`") from exc


def _dataset_config(recipe: Recipe) -> dict:
    """Feature handler over the traded universe, wrapped in a DatasetH.

    Passing ``instruments`` restricts the tradable set to the USDT pairs and
    excludes the reference instruments (BTCEUR, ETHBTC). The handler class is
    recipe-pluggable via ``recipe.feature_config`` (default: Alpha158).
    """
    return {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": handler_config(
                recipe.feature_config,
                instruments=recipe.universe,
                start=recipe.segments["train"][0],
                end=recipe.segments["test"][1],
                fit_start=recipe.segments["train"][0],
                fit_end=recipe.segments["train"][1],
                handler_kwargs=recipe.handler_kwargs,
            ),
            "segments": recipe.segments,
        },
    }


def exchange_kwargs(recipe: Recipe) -> dict:
    """Shared exchange config for both the holdout backtest and CPCV path backtests.

    `trade_unit=None` enables fractional crypto fills. qlib.init(region=REG_US) sets
    C.trade_unit=1 and Exchange.__init__ does kwargs.pop("trade_unit", C.trade_unit),
    so omitting this key would floor order amounts to whole coins and zero out
    BTC/ETH on a $10k account.
    """
    fee_open, fee_close = FEE_PRESETS[recipe.fee_preset]
    return {
        "freq": "day",
        "deal_price": "close",
        "open_cost": fee_open,
        "close_cost": fee_close,
        "min_cost": 0,
        "trade_unit": None,
    }


def _port_analysis_config(recipe: Recipe, model, dataset) -> dict:
    return {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
        },
        "strategy": strategy_config_with_signal(recipe.strategy_config, (model, dataset)),
        "backtest": {
            "start_time": recipe.segments["test"][0],
            "end_time": recipe.segments["test"][1],
            "account": recipe.account,
            "benchmark": recipe.benchmark,
            "exchange_kwargs": exchange_kwargs(recipe),
        },
    }


def _extract_metrics(analysis_df: pd.DataFrame, report_df: pd.DataFrame) -> dict:
    from qlib.contrib.evaluate import risk_analysis

    metrics = {
        key: {m: float(analysis_df.loc[(key, m)].iloc[0]) for m in _METRICS}
        for key in ["excess_return_without_cost", "excess_return_with_cost"]
    }
    abs_df = risk_analysis(report_df["return"] - report_df["cost"], freq="day")
    metrics["strategy_absolute"] = {m: float(abs_df.loc[m].iloc[0]) for m in _METRICS}
    return metrics


def _context_prices(recipe: Recipe) -> dict[str, pd.Series]:
    """Close series over the full [train start .. test end] span for chart context."""
    from qlib.data import D

    symbols = ["BTCUSDT", *recipe.reference_instruments]
    start = recipe.segments["train"][0]
    end = recipe.segments["test"][1]
    df = D.features(symbols, ["$close"], start_time=start, end_time=end, freq="day")
    out: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            series = df.loc[sym, "$close"]
        except KeyError:
            continue
        out[sym] = series
    return out


def run_experiment(
    recipe: Recipe,
    *,
    data_dir: Path,
    out_dir: Path,
    refresh_cache: bool = False,
) -> RunResult:
    """Run train -> backtest -> extract for *recipe* and return a RunResult.

    Heavy qlib imports are deferred into the function body so importing this
    module stays cheap (mirrors ``cli/example/workflow.py``).
    """
    data_dir = Path(data_dir).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if recipe.wf_enabled:
        # Walk-forward holdout: periodic retraining + stitched report_df. Returns a
        # single-fit-compatible RunResult; the single-fit path below is untouched.
        from cli.experiment.walkforward import run_walkforward_holdout

        return run_walkforward_holdout(recipe, data_dir=data_dir, refresh_cache=refresh_cache)

    redis_preflight()
    logger.info("redis-ok", extra={"port": int(os.environ.get("ZCRYPTO_REDIS_PORT", "6379"))})

    ensure_cache_fresh(data_dir, refresh=refresh_cache)
    logger.info("cache-checked", extra={"data_dir": str(data_dir), "refresh": refresh_cache})

    # MLflow rejects file:// tracking URIs unless this flag is set; needed for offline runs.
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

    import qlib
    from qlib.constant import REG_US
    from qlib.utils import init_instance_by_config
    from qlib.workflow import R
    from qlib.workflow.record_temp import PortAnaRecord, SignalRecord

    # Persistent MLflow store: absolute file:// path so the run (model + artifacts) survives.
    mlflow_uri = (out_dir / "mlruns").resolve().as_uri()

    # qlib 0.9.7's MLflowExpManager builds its FileLock path relative to CWD (expm.py:237),
    # and MLflowRecorder._log_uncommitted_code runs `git` in CWD. Run the qlib session inside a
    # throwaway cwd with a git repo so neither pollutes the caller's tree (see example.workflow).
    with tempfile.TemporaryDirectory(prefix="zcrypto-qlib-cwd-") as cwd_tmp, contextlib.chdir(cwd_tmp):
        subprocess.run(["git", "init", "-q"], check=True)
        qlib.init(
            provider_uri=str(data_dir),
            region=REG_US,
            expression_cache="DiskExpressionCache",
            dataset_cache="DiskDatasetCache",
            exp_manager={
                "class": "MLflowExpManager",
                "module_path": "qlib.workflow.expm",
                "kwargs": {"uri": mlflow_uri, "default_exp_name": recipe.name},
            },
            logging_config=None,  # prevent qlib from overwriting our configured handlers
        )
        logger.info("init", extra={"provider_uri": str(data_dir), "mlflow_uri": mlflow_uri})

        dataset = init_instance_by_config(_dataset_config(recipe))
        model = init_instance_by_config(recipe.model_config)
        logger.info("dataset-built", extra={"recipe": recipe.name, "n_instruments": len(recipe.universe)})

        port_cfg = _port_analysis_config(recipe, model, dataset)
        with R.start(experiment_name=recipe.name):
            model.fit(dataset)
            recorder = R.get_recorder()
            R.save_objects(**{"trained_model": model})
            logger.info("fit-done", extra={"run_id": recorder.id})

            SignalRecord(model, dataset, recorder).generate()
            PortAnaRecord(recorder, port_cfg, "day").generate()
            logger.info("backtest-done", extra={"run_id": recorder.id})

            report_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
            positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")
            analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")

            metrics = _extract_metrics(analysis_df, report_df)
            logger.info("metrics", extra={"metrics": metrics})

            account_curve = recipe.account * (1 + report_df["return"]).cumprod()
            benchmark_curve = recipe.account * (1 + report_df["bench"]).cumprod()
            context_prices = _context_prices(recipe)

            run_id = recorder.id
            recorder_dir = Path(recorder.get_local_dir())

    record_fingerprint(data_dir)
    data_fingerprint = compute_sha256(data_dir / "index.json")

    ending_value = float(account_curve.iloc[-1])
    logger.info("done", extra={"run_id": run_id, "ending_value": ending_value})

    return RunResult(
        metrics=metrics,
        report_df=report_df,
        positions=positions,
        analysis_df=analysis_df,
        account_curve=account_curve,
        benchmark_curve=benchmark_curve,
        context_prices=context_prices,
        ending_value=ending_value,
        run_id=run_id,
        recorder_dir=recorder_dir,
        recipe=recipe,
        data_fingerprint=data_fingerprint,
    )
