from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile

import pandas as pd
import qlib
from qlib.constant import REG_US
from qlib.contrib.evaluate import risk_analysis
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import PortAnaRecord, SignalRecord

from cli.example.config import BENCHMARK, TEST, TRAIN, VALID, WINDOW

FEATURE_EXPRS = [
    "$close/Ref($close, 5) - 1",
    "$close/Ref($close, 20) - 1",
    "Mean($close, 5)/$close - 1",
    "Mean($close, 20)/$close - 1",
    "Std($close/Ref($close, 1) - 1, 10)",
    "$volume/Mean($volume, 5) - 1",
]
FEATURE_NAMES = ["RET5", "RET20", "MA5", "MA20", "VOL10", "VRATIO"]
LABEL_EXPR = "Ref($close, -2)/Ref($close, -1) - 1"

_METRICS = ["annualized_return", "information_ratio", "max_drawdown"]


def run_experiment(provider_uri: str, exp_uri: str, show_data: bool = False) -> dict:
    # MLflow rejects file:// tracking URIs unless this flag is set; needed for offline runs.
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    # qlib 0.9.7's MLflowExpManager builds its FileLock path via os.path.join(netloc, path.lstrip("/"), ...)
    # at expm.py:237, turning any absolute file:// URI into a CWD-RELATIVE mkdir. Run the whole qlib
    # session inside a disposable cwd so that scaffolding lands in a throwaway dir, not the caller's tree.
    with tempfile.TemporaryDirectory(prefix="zcrypto-qlib-cwd-") as cwd_tmp, contextlib.chdir(cwd_tmp):
        # qlib's MLflowRecorder._log_uncommitted_code runs `git diff/status/diff --cached` in CWD
        # via subprocess.check_output(..., shell=True); without a repo here it would write a usage
        # message to *our* stderr and emit "Fail to log the uncommitted code" INFO records.
        subprocess.run(["git", "init", "-q"], check=True)
        qlib.init(
            provider_uri=provider_uri,
            region=REG_US,
            exp_manager={
                "class": "MLflowExpManager",
                "module_path": "qlib.workflow.expm",
                "kwargs": {"uri": exp_uri, "default_exp_name": "example"},
            },
        )

        dataset = init_instance_by_config(_dataset_config())
        model = init_instance_by_config(_model_config())

        if show_data:
            print(dataset.prepare("train").head().to_string())

        port_analysis_config = _port_analysis_config(model, dataset)
        with R.start(experiment_name="example"):
            model.fit(dataset)
            recorder = R.get_recorder()
            SignalRecord(model, dataset, recorder).generate()
            PortAnaRecord(recorder, port_analysis_config, "day").generate()
            return _extract_metrics(recorder)


def _dataset_config() -> dict:
    return {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "DataHandlerLP",
                "module_path": "qlib.data.dataset.handler",
                "kwargs": {
                    "start_time": WINDOW[0],
                    "end_time": WINDOW[1],
                    "instruments": "all",
                    "data_loader": {
                        "class": "QlibDataLoader",
                        "kwargs": {
                            "config": {
                                "feature": [FEATURE_EXPRS, FEATURE_NAMES],
                                "label": [[LABEL_EXPR], ["LABEL0"]],
                            },
                            "freq": "day",
                        },
                    },
                    "infer_processors": [
                        {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
                    ],
                    "learn_processors": [{"class": "DropnaLabel"}],
                },
            },
            "segments": {"train": TRAIN, "valid": VALID, "test": TEST},
        },
    }


def _model_config() -> dict:
    return {
        "class": "LinearModel",
        "module_path": "qlib.contrib.model.linear",
        "kwargs": {"estimator": "ols"},
    }


def _port_analysis_config(model, dataset) -> dict:
    return {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
        },
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {"signal": (model, dataset), "topk": 2, "n_drop": 1},
        },
        "backtest": {
            "start_time": TEST[0],
            # Qlib needs one calendar day beyond end_time for the last step's look-ahead;
            # stop one day before the calendar boundary to avoid IndexError.
            "end_time": (pd.Timestamp(TEST[1]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "account": 100000,
            "benchmark": BENCHMARK,
            "exchange_kwargs": {
                "freq": "day",
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 0,
            },
        },
    }


def _extract_metrics(recorder) -> dict:
    analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
    metrics = {
        key: {m: float(analysis_df.loc[(key, m)].iloc[0]) for m in _METRICS}
        for key in ["excess_return_without_cost", "excess_return_with_cost"]
    }
    report = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
    abs_df = risk_analysis(report["return"] - report["cost"], freq="day")
    # risk_analysis returns a single-column DataFrame; .iloc[0] takes that scalar.
    metrics["strategy_absolute"] = {m: float(abs_df.loc[m].iloc[0]) for m in _METRICS}
    return metrics
