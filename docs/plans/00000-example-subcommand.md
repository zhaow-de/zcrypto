# `example` Subcommand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `zcrypto example` subcommand that runs a self-contained, offline Qlib strategy experiment (feature engineering → LinearModel → TopkDropout backtest → metrics) on a tiny bundled crypto dataset.

**Architecture:** A small `cli/example/` subpackage. `dataset.py` writes Qlib's binary data format from a bundled CSV into a temp dir; `workflow.py` runs the Qlib pipeline and returns a metrics dict; `command.py` wires a Typer command (temp dir → build → run → render). Heavy imports (`qlib`) are deferred inside the command so `zcrypto --version` stays fast. Tests use seeded synthetic data so they need no network; only the committed CSV is generated once via `yfinance`.

**Tech Stack:** Python 3.12, uv, Typer, pyqlib 0.9.7 (`qlib.contrib.model.linear.LinearModel`, `qlib.contrib.strategy.signal_strategy.TopkDropoutStrategy`, `qlib.workflow` records), numpy/pandas (transitive via qlib), pytest + Typer `CliRunner`.

**Spec:** `docs/specs/00000-example-subcommand-design.md`

---

## File map

- Create `cli/example/__init__.py` — package marker.
- Create `cli/example/config.py` — shared constants (instruments, window, splits, benchmark). Single source of truth for both the workflow and the data-gen script.
- Create `cli/example/dataset.py` — `build_provider(csv_path, out_dir) -> str` plus `_write_calendar/_write_instruments/_write_features`.
- Create `cli/example/workflow.py` — `run_experiment(provider_uri, exp_uri, show_data=False) -> dict` plus config builders + `_extract_metrics`.
- Create `cli/example/command.py` — `example()` Typer command + `_render`.
- Create `cli/example/data/crypto_ohlcv.csv` — committed dataset (generated in Task 3).
- Create `scripts/gen_example_data.py` — dev-only, one-off `yfinance` fetch; not shipped.
- Modify `cli/__main__.py` — register the `example` command.
- Modify `README.md` — document the command under `## Usage`.
- Modify `pyproject.toml` — only if Task 6 shows the CSV is missing from the wheel.
- Modify `docs/iterations-history.md` — final task.
- Tests: `tests/test_example_dataset.py`, `tests/test_example_workflow.py`, `tests/test_example_command.py`.

**Commit convention:** `<type>(cli): <subject>` (Conventional Commits). End every commit message with `Co-Authored-By: Claude <your-model> <noreply@anthropic.com>` crediting the model that actually wrote the commit.

---

## Task 1: Scaffold package + shared config constants

Pure scaffolding/constants — no test (nothing behavioral yet).

**Files:**
- Create: `cli/example/__init__.py`
- Create: `cli/example/config.py`

- [ ] **Step 1: Create the package marker**

`cli/example/__init__.py`:

```python
```

(empty file)

- [ ] **Step 2: Create the shared constants**

`cli/example/config.py`:

```python
INSTRUMENTS = ["BTCUSD", "ETHUSD", "BNBUSD", "SOLUSD", "XRPUSD", "ADAUSD"]
BENCHMARK = "ETHUSD"

# Most recent complete 6 months as of 2026-06-07.
WINDOW = ("2025-12-01", "2026-05-31")
TRAIN = ("2025-12-01", "2026-03-15")
VALID = ("2026-03-16", "2026-03-31")
TEST = ("2026-04-01", "2026-05-31")
```

- [ ] **Step 3: Verify it imports**

Run: `uv run python -c "from cli.example import config; print(config.INSTRUMENTS, config.TEST)"`
Expected: `['BTCUSD', 'ETHUSD', 'BNBUSD', 'SOLUSD', 'XRPUSD', 'ADAUSD'] ('2026-04-01', '2026-05-31')`

- [ ] **Step 4: Commit**

```bash
git add cli/example/__init__.py cli/example/config.py
git commit -m "$(cat <<'EOF'
feat(cli): scaffold example package with shared config

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `dataset.build_provider` — CSV → Qlib binary (round-trip TDD)

Writes Qlib's file format: `calendars/day.txt`, `instruments/all.txt`, and `features/<code_lower>/<field>.day.bin` (little-endian float32 `[start_index, v0, v1, …]`). Assumes each symbol covers a contiguous run of the calendar (true for daily crypto with aligned dates).

**Files:**
- Create: `cli/example/dataset.py`
- Test: `tests/test_example_dataset.py`

- [ ] **Step 1: Write the failing round-trip test**

`tests/test_example_dataset.py`:

```python
import pytest

from cli.example.dataset import build_provider


def test_build_provider_roundtrip(tmp_path):
    csv = tmp_path / "toy.csv"
    csv.write_text(
        "date,symbol,open,high,low,close,volume\n"
        "2026-01-01,AAAUSD,10,11,9,10.5,100\n"
        "2026-01-02,AAAUSD,10.5,12,10,11.5,120\n"
        "2026-01-03,AAAUSD,11.5,12,11,11.0,90\n"
    )
    provider = build_provider(csv, tmp_path / "qlib_data")

    import qlib
    from qlib.constant import REG_US
    from qlib.data import D

    qlib.init(provider_uri=provider, region=REG_US)
    df = D.features(["AAAUSD"], ["$close", "$open", "$volume"], freq="day")

    assert df["$close"].tolist() == pytest.approx([10.5, 11.5, 11.0])
    assert df["$open"].tolist() == pytest.approx([10.0, 10.5, 11.5])
    assert df["$volume"].tolist() == pytest.approx([100.0, 120.0, 90.0])
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_example_dataset.py -v`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` (no `build_provider`).

- [ ] **Step 3: Implement `dataset.py`**

`cli/example/dataset.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FIELDS = ["open", "high", "low", "close", "volume", "factor"]


def build_provider(csv_path: Path, out_dir: Path) -> str:
    """Write a Qlib file-format dataset from an OHLCV CSV; return the provider_uri."""
    df = pd.read_csv(csv_path, parse_dates=["date"]).sort_values(["symbol", "date"])
    if "factor" not in df.columns:
        df["factor"] = 1.0

    calendar = sorted(pd.to_datetime(df["date"].unique()))
    date_to_idx = {ts: i for i, ts in enumerate(calendar)}

    out_dir = Path(out_dir)
    _write_calendar(out_dir, calendar)
    _write_instruments(out_dir, df)
    _write_features(out_dir, df, date_to_idx)
    return str(out_dir)


def _write_calendar(out_dir: Path, calendar: list) -> None:
    cal_dir = out_dir / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    lines = [ts.strftime("%Y-%m-%d") for ts in calendar]
    (cal_dir / "day.txt").write_text("\n".join(lines) + "\n")


def _write_instruments(out_dir: Path, df: pd.DataFrame) -> None:
    inst_dir = out_dir / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for symbol, g in df.groupby("symbol"):
        start = g["date"].min().strftime("%Y-%m-%d")
        end = g["date"].max().strftime("%Y-%m-%d")
        lines.append(f"{symbol.upper()}\t{start}\t{end}")
    (inst_dir / "all.txt").write_text("\n".join(lines) + "\n")


def _write_features(out_dir: Path, df: pd.DataFrame, date_to_idx: dict) -> None:
    for symbol, g in df.groupby("symbol"):
        g = g.sort_values("date")
        start_idx = date_to_idx[g["date"].iloc[0]]
        code_dir = out_dir / "features" / symbol.lower()
        code_dir.mkdir(parents=True, exist_ok=True)
        for field in FIELDS:
            values = g[field].to_numpy(dtype="float32")
            arr = np.concatenate([[np.float32(start_idx)], values]).astype("<f4")
            arr.tofile(code_dir / f"{field}.day.bin")
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_example_dataset.py -v`
Expected: PASS. (If it fails reading values, inspect the written `.bin` with `np.fromfile(path, "<f4")` — element 0 must be the start index, then the values.)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/example/dataset.py tests/test_example_dataset.py
uv run ruff format cli/example/dataset.py tests/test_example_dataset.py
git add cli/example/dataset.py tests/test_example_dataset.py
git commit -m "$(cat <<'EOF'
feat(cli): add CSV-to-Qlib-binary dataset builder

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Generate + commit the bundled CSV (`yfinance`, one-off)

**Requires network.** This is the only task needing internet. The script is dev-only (lives in `scripts/`, not shipped). If the execution environment has no network, stop and ask a human to run Step 2 via `! uv run --with yfinance python scripts/gen_example_data.py`, then continue.

**Files:**
- Create: `scripts/gen_example_data.py`
- Create (output, committed): `cli/example/data/crypto_ohlcv.csv`

- [ ] **Step 1: Write the generation script**

`scripts/gen_example_data.py`:

```python
"""Dev-only one-off: fetch daily crypto OHLCV via yfinance into the bundled CSV.

Run: uv run --with yfinance python scripts/gen_example_data.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

from cli.example.config import INSTRUMENTS, WINDOW

YAHOO = {code: f"{code[:-3]}-USD" for code in INSTRUMENTS}  # BTCUSD -> BTC-USD
OUT = Path(__file__).resolve().parents[1] / "cli" / "example" / "data" / "crypto_ohlcv.csv"


def _fetch(code: str) -> pd.DataFrame:
    start, end = WINDOW
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(
        YAHOO[code], start=start, end=end_excl, interval="1d",
        auto_adjust=False, progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    d = raw.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
    d.columns = ["date", "open", "high", "low", "close", "volume"]
    d["symbol"] = code
    return d


def main() -> None:
    frames = [_fetch(code) for code in INSTRUMENTS]
    common = set.intersection(*(set(f["date"]) for f in frames))
    df = pd.concat(frames)
    df = df[df["date"].isin(common)].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["symbol", "date"])[
        ["date", "symbol", "open", "high", "low", "close", "volume"]
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(df)} rows, {df['symbol'].nunique()} symbols, "
          f"{df['date'].nunique()} dates)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it (needs network)**

Run: `uv run --with yfinance python scripts/gen_example_data.py`
Expected: prints `wrote …/crypto_ohlcv.csv (≈1000+ rows, 6 symbols, ≈180 dates)`.
If `yfinance` returns a short series for any coin (so `common` is small), note it and either widen tolerance or drop/replace that coin and update `INSTRUMENTS`/`WINDOW` in `config.py` accordingly.

- [ ] **Step 3: Sanity-check the CSV**

Run: `uv run python -c "import pandas as pd; d=pd.read_csv('cli/example/data/crypto_ohlcv.csv'); print(d['symbol'].unique()); print(d['date'].min(), d['date'].max()); print(d.groupby('symbol').size().to_dict())"`
Expected: 6 symbols, dates within `2025-12-01`..`2026-05-31`, equal row counts per symbol.

- [ ] **Step 4: Commit**

```bash
git add scripts/gen_example_data.py cli/example/data/crypto_ohlcv.csv
git commit -m "$(cat <<'EOF'
feat(cli): add bundled ETH-USD crypto OHLCV dataset and generator

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `workflow.run_experiment` — Qlib pipeline (integration TDD, synthetic data)

The integration test builds a provider from **seeded synthetic data spanning `WINDOW` for `INSTRUMENTS`** (no network, no committed CSV needed) and asserts the returned metrics are finite.

**Files:**
- Create: `cli/example/workflow.py`
- Test: `tests/test_example_workflow.py`

- [ ] **Step 1: Write the failing integration test**

`tests/test_example_workflow.py`:

```python
import math

import numpy as np
import pandas as pd

from cli.example.config import INSTRUMENTS, WINDOW
from cli.example.dataset import build_provider
from cli.example.workflow import run_experiment


def _synthetic_csv(path):
    rng = np.random.default_rng(0)
    dates = pd.date_range(WINDOW[0], WINDOW[1], freq="D")
    rows = []
    for i, sym in enumerate(INSTRUMENTS):
        price = 100.0 + i * 10
        for d in dates:
            price = max(1.0, price * (1 + rng.normal(0, 0.02)))
            rows.append((d.strftime("%Y-%m-%d"), sym, price,
                         price * 1.01, price * 0.99, price,
                         rng.uniform(1000, 2000)))
    cols = ["date", "symbol", "open", "high", "low", "close", "volume"]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return path


def test_run_experiment_returns_finite_metrics(tmp_path):
    csv = _synthetic_csv(tmp_path / "synthetic.csv")
    provider = build_provider(csv, tmp_path / "qlib_data")
    exp_uri = (tmp_path / "mlruns").as_uri()

    metrics = run_experiment(provider, exp_uri)

    for key in ["strategy_absolute", "excess_return_with_cost", "excess_return_without_cost"]:
        for m in ["annualized_return", "information_ratio", "max_drawdown"]:
            assert math.isfinite(metrics[key][m]), f"{key}/{m} not finite"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_example_workflow.py -v`
Expected: FAIL — no `run_experiment`.

- [ ] **Step 3: Implement `workflow.py`**

`cli/example/workflow.py`:

```python
from __future__ import annotations

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
            "end_time": TEST[1],
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
    metrics["strategy_absolute"] = {m: float(abs_df.loc[m].iloc[0]) for m in _METRICS}
    return metrics
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_example_workflow.py -v`
Expected: PASS (a few seconds). If `load_object` errors on a path, inspect `recorder.list_artifacts()` and adjust the artifact names in `_extract_metrics`; if `analysis_df.loc[(key, m)]` KeyErrors, `print(analysis_df.index)` to confirm the `(key, metric)` MultiIndex.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix cli/example/workflow.py tests/test_example_workflow.py
uv run ruff format cli/example/workflow.py tests/test_example_workflow.py
git add cli/example/workflow.py tests/test_example_workflow.py
git commit -m "$(cat <<'EOF'
feat(cli): add Qlib backtest workflow for the example demo

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `command.example` + register + README (smoke TDD)

Heavy imports (`dataset`, `workflow` → `qlib`) are **deferred inside `example()`** so `zcrypto --version` stays fast. The smoke test runs the real command on the **committed CSV** (Task 3 must be done).

**Files:**
- Create: `cli/example/command.py`
- Modify: `cli/__main__.py`
- Modify: `README.md`
- Test: `tests/test_example_command.py`

- [ ] **Step 1: Write the failing smoke test**

`tests/test_example_command.py`:

```python
from typer.testing import CliRunner

from cli.__main__ import app

runner = CliRunner()


def test_example_runs_and_reports_metrics():
    result = runner.invoke(app, ["example"])
    assert result.exit_code == 0, result.output
    assert "annualized_return" in result.output
    assert "Excess vs ETH" in result.output


def test_example_listed_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "example" in result.output
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_example_command.py -v`
Expected: FAIL — `example` is not a registered command (exit code 2 / not in help).

- [ ] **Step 3: Implement `command.py`**

`cli/example/command.py`:

```python
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
        False, "--show-data/--no-show-data",
        help="Print the head of the prepared feature frame.",
    ),
) -> None:
    """Run a small offline Qlib ETH-USD strategy backtest demo."""
    from cli.example.dataset import build_provider
    from cli.example.workflow import run_experiment

    with tempfile.TemporaryDirectory(prefix="zcrypto-example-") as tmp:
        tmp_path = Path(tmp)
        data_ref = files("cli.example").joinpath("data", "crypto_ohlcv.csv")
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
```

- [ ] **Step 4: Register the command in `cli/__main__.py`**

Add the import after the existing `import typer` line and register the command after the `main` callback is defined (before `if __name__ == "__main__":`). Insert:

```python
from cli.example.command import example

app.command(name="example")(example)
```

So the bottom of `cli/__main__.py` reads:

```python
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


from cli.example.command import example

app.command(name="example")(example)


if __name__ == "__main__":
    app()
```

(Place the `from cli.example.command import example` import here at the bottom rather than the top — it keeps the module-level import block unchanged and avoids a forward-reference to `app`. Ruff may move it to the top during `--fix`; if it does, that is fine because `app` is already defined above the call. If ruff reorders such that the `app.command(...)` call precedes `app`'s definition, keep the import at top but leave the `app.command(...)` call at the bottom.)

- [ ] **Step 5: Run the smoke test to confirm it passes**

Run: `uv run pytest tests/test_example_command.py -v`
Expected: PASS. (Runs the full pipeline on the bundled CSV; a few seconds.)

- [ ] **Step 6: Confirm `--version` still works and is not slowed by eager qlib import**

Run: `uv run zcrypto --version`
Expected: prints `zcrypto v0.0.0 (with pyqlib-0.9.7)` and exits 0.

- [ ] **Step 7: Update `README.md` `## Usage`**

In `README.md`, under `## Usage`, after the existing options table and the "Running with no options prints the help." line, add:

```markdown
### Commands

| Command   | Description                                              |
| --------- | -------------------------------------------------------- |
| `example` | Run a small offline Qlib ETH-USD strategy backtest demo. |

```bash
zcrypto example                # run the demo backtest
zcrypto example --show-data    # also print the prepared feature-frame head
```
```

(The `mdformat` pre-commit hook owns the table-of-contents; let it regenerate the TOC — do not hand-edit the TOC block.)

- [ ] **Step 8: Commit (let pre-commit reflow the README, then re-stage)**

```bash
uv run ruff check --fix cli/example/command.py cli/__main__.py tests/test_example_command.py
uv run ruff format cli/example/command.py cli/__main__.py tests/test_example_command.py
git add cli/example/command.py cli/__main__.py tests/test_example_command.py README.md
git commit -m "$(cat <<'EOF'
feat(cli): add example subcommand running the Qlib backtest demo

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

If pre-commit (mdformat / end-of-file fixer) rewrites `README.md` and aborts, re-stage and re-commit (never `--no-verify`):

```bash
git add README.md && git commit -m "$(cat <<'EOF'
feat(cli): add example subcommand running the Qlib backtest demo

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Verify the wheel ships the bundled CSV

The installed `zcrypto example` console script reads the CSV via `importlib.resources`, so it must be inside the wheel.

**Files:**
- Modify (only if needed): `pyproject.toml`

- [ ] **Step 1: Build the wheel**

Run: `uv build --wheel`
Expected: writes a wheel under `dist/`.

- [ ] **Step 2: Check the CSV is inside**

Run: `uv run python -c "import glob,zipfile; w=sorted(glob.glob('dist/*.whl'))[-1]; print([n for n in zipfile.ZipFile(w).namelist() if 'crypto_ohlcv' in n])"`
Expected: `['cli/example/data/crypto_ohlcv.csv']`.

- [ ] **Step 3: If (and only if) the list is empty, add an explicit include and rebuild**

Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"cli/example/data/crypto_ohlcv.csv" = "cli/example/data/crypto_ohlcv.csv"
```

Then rerun Steps 1–2 and confirm the CSV now appears. Commit:

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
build(config): include bundled example dataset in the wheel

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

(If the CSV was already present in Step 2, skip this step — no commit needed.)

---

## Task 7: Full-suite verification + iterations-history entry

**Files:**
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (existing CLI tests + the three new test files).

- [ ] **Step 2: Coverage**

Run: `uv run coverage run -m pytest && uv run coverage report`
Expected: passes; `cli/example/*` modules are exercised (dataset, workflow, command).

- [ ] **Step 3: Lint + format the whole tree**

Run: `uv run ruff check --fix && uv run ruff format`
Expected: no remaining lint errors.

- [ ] **Step 4: Append the iterations-history entry**

Add to the bottom of `docs/iterations-history.md`:

```markdown
## 2026-06-07 — iter-1: `example` Qlib backtest subcommand

- Added `zcrypto example`: a self-contained, **offline** Qlib strategy experiment on a tiny bundled crypto dataset — the project's first real Qlib wiring (`qlib.init` was previously absent).
- `cli/example/dataset.py` writes Qlib's file format (`calendars/day.txt`, `instruments/all.txt`, `features/<coin>/<field>.day.bin` as little-endian float32 `[start_index, …]`) from an OHLCV CSV into a temp `provider_uri`.
- `cli/example/workflow.py` runs the pipeline: ~6-feature `QlibDataLoader` handler + numpy-only `LinearModel` (OLS) → `SignalRecord`/`PortAnaRecord` backtest with `TopkDropoutStrategy(topk=2, n_drop=1)` over 6 coins (`REG_US`, `deal_price=close`, costs 0.0005/0.0015, benchmark `ETHUSD`); returns annualized-return / information-ratio / max-drawdown for strategy-absolute and excess-vs-ETH (with/without cost).
- `cli/example/command.py` runs everything in a `TemporaryDirectory` (Qlib binary data **and** MLflow recorder are ephemeral; nothing persists in the repo). Heavy imports are deferred so `zcrypto --version` stays fast.
- Bundled data: `cli/example/data/crypto_ohlcv.csv` (~6 months daily OHLCV, 6 coins, window `2025-12-01`..`2026-05-31`), generated one-off by dev-only `scripts/gen_example_data.py` (`yfinance`; not a project dependency, not shipped).
- `--show-data/--no-show-data` flag prints the prepared feature-frame head.
- Tests use seeded synthetic data (no network): `tests/test_example_dataset.py` (binary round-trip), `tests/test_example_workflow.py` (finite-metrics integration), `tests/test_example_command.py` (CLI smoke).
```

- [ ] **Step 5: Commit**

```bash
git add docs/iterations-history.md
git commit -m "$(cat <<'EOF'
docs(cli): record iter-1 example subcommand in iterations history

Co-Authored-By: Claude <your-model> <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Final green check**

Run: `uv run pytest -q && uv run pre-commit run --all-files`
Expected: tests pass; pre-commit hooks pass (re-stage + re-commit if any hook reflows files).

---

## Self-review notes

- **Spec coverage:** CLI surface + `--show-data` (Task 5) ✓; module layout (Tasks 1,2,4,5) ✓; bundled data window/coins/splits (Tasks 1,3) ✓; binary format (Task 2) ✓; handler/model/strategy/backtest/output (Task 4) ✓; temp-dir footprint (Task 5) ✓; packaging (Task 6) ✓; round-trip + smoke tests (Tasks 2,4,5) ✓; README + iterations-history closeout (Tasks 5,7) ✓.
- **Type consistency:** `build_provider(csv_path, out_dir) -> str` and `run_experiment(provider_uri, exp_uri, show_data=False) -> dict` are used identically in tests and command; metric keys (`strategy_absolute`, `excess_return_with_cost`, `excess_return_without_cost`) and metric names (`annualized_return`, `information_ratio`, `max_drawdown`) match across `workflow.py`, `command.py`, and the tests.
- **Known risk:** exact Qlib artifact paths / `analysis_df` MultiIndex in `_extract_metrics` (Task 4) are the most likely to need a small adjustment; the integration test surfaces it immediately, and Step 4 gives the inspection commands.
