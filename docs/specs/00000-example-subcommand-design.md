# 00000 — `example` subcommand (Qlib ETH-USD backtest demo)

- **Date:** 2026-06-07
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-1
- **Scope:** Add a `zcrypto example` subcommand that runs a self-contained, offline Qlib strategy experiment end-to-end on a tiny bundled crypto dataset.

## Goal

`zcrypto example` demonstrates Qlib's capability for a full strategy experiment —
feature engineering → model training → cross-sectional backtest → reported metrics —
on a **very small, bundled dataset with a short time window** and a **small runtime
footprint**. It is the project's first real use of Qlib (no `qlib.init` exists yet).

It mirrors Qlib's `examples/workflow_by_code.py`, but swaps the downloaded CN-stock
data + Alpha158 + LightGBM for: a **bundled crypto CSV** + a **~6-feature custom
handler** + the **numpy-only LinearModel**. No network access at runtime, no new
runtime dependencies.

## Background & constraints

- Qlib (`pyqlib` 0.9.7) is installed but unwired. `qlib.tests.data.GetData` only
  downloads Qlib's *prebuilt stock* datasets; the CSV→Qlib-binary converter
  (`scripts/dump_bin.py`) ships only in the qlib **repo**, not the installed package.
  Therefore the example must **write Qlib's binary data format itself**.
- "Simple" / "small" (from the request): very small dataset, short time window, no
  lengthy single function, small runtime data footprint.
- Repo rules: README `## Usage` updated in the same change (`readme-usage.md`);
  iterations-history entry as the final plan task (`iterations-history.md`); branch +
  PR into `develop` titled `feat(cli): iter-1 — …` (`branch-workflow.md`,
  `pull-requests.md`).

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Signal | **Lightweight ML model** — custom ~6-feature handler + `LinearModel` (OLS). |
| Universe | **Tiny multi-coin universe** (ETH headline + 5 others) so `TopkDropoutStrategy` genuinely picks among assets; no custom strategy class needed. |
| Data source | **Bundled static CSV**, generated once at authoring time via `yfinance`; runtime is fully offline & deterministic. |

## CLI surface

- `zcrypto example` — no required arguments; runs the demo and prints a metrics table.
- `--show-data / --no-show-data` (default **off**) — print the prepared feature-frame
  head (the `example_df.head()` moment from the reference) for illustration.
- README `## Usage` table updated in the same change.

## Module layout

New subpackage `cli/example/` (small, independently-testable units — keeps every
function short):

- `cli/example/data/crypto_ohlcv.csv` — committed dataset (see below).
- `cli/example/dataset.py` — CSV → Qlib binary provider.
  `build_provider(csv_path: Path, out_dir: Path) -> str` (returns `provider_uri`),
  split into short helpers `_write_calendar`, `_write_instruments`, `_write_features`.
- `cli/example/workflow.py` — `run_experiment(provider_uri: str, show_data: bool) -> dict`
  (qlib.init → configs → train → records → metrics dict).
- `cli/example/command.py` — the Typer command: create temp dir → `build_provider`
  → `run_experiment` → render table. Registered on `app` in `cli/__main__.py`.

## Bundled data

- **Window:** `2025-12-01` → `2026-05-31` (~182 daily rows per coin; the most recent
  complete 6 months as of 2026-06-07).
- **Coins (6):** `BTCUSD`, `ETHUSD`, `BNBUSD`, `SOLUSD`, `XRPUSD`, `ADAUSD`
  (ETH is the headline asset **and** the backtest benchmark).
- **Columns:** `date, symbol, open, high, low, close, volume`.
- **Generation (authoring-time, one-off):** fetch daily OHLCV via `yfinance`
  (tickers `BTC-USD`, …), write the CSV, commit it (~60 KB). `yfinance` is a
  **dev-only one-off**, *not* added to project dependencies.
  - **Verification at generation:** confirm `yfinance` returns the full window for all
    six coins; if any series is short, trim the window or drop/replace the coin then.
    Window and coin list are tunable constants.
- **Splits:**
  - train: `2025-12-01` … `2026-03-15`
  - valid: `2026-03-16` … `2026-03-31`
  - test + backtest: `2026-04-01` … `2026-05-31`

## Qlib binary format (what `build_provider` writes)

Under `out_dir` (the temp `provider_uri`):

- `calendars/day.txt` — every date in the window, sorted, `%Y-%m-%d`, one per line.
- `instruments/all.txt` — `CODE\tSTART\tEND` (tab-separated) per coin.
- `features/<code_lowercased>/<field>.day.bin` for fields
  `open, high, low, close, volume, factor` (with `factor` = 1.0). Each `.bin` is a
  little-endian float32 array `[start_index, v0, v1, …]`, where `start_index` is the
  coin's first-date index into the calendar.

**Risk note:** the exact `.bin` byte layout is medium-high confidence. The round-trip
unit test (below) verifies it before anything downstream is built.

## Qlib pipeline (`run_experiment`)

- `qlib.init(provider_uri=<temp>, region=REG_US)` (no CN-style price limit).
- **Handler:** `DataHandlerLP` (`qlib.data.dataset.handler`) configured with an inline
  `QlibDataLoader` — ~6 expression features and one label:
  - features (max lookback 20d): `$close/Ref($close,5)-1`, `$close/Ref($close,20)-1`,
    `Mean($close,5)/$close-1`, `Mean($close,20)/$close-1`,
    `Std($close/Ref($close,1)-1,10)`, `$volume/Mean($volume,5)-1`.
  - label: `Ref($close,-2)/Ref($close,-1)-1` (next-day return; `-1/-2` avoids
    look-ahead since signals at T trade at T+1).
  - light processors: fill NaN features, drop NaN labels (exact list left to the plan).
- **Dataset:** `DatasetH` wrapping the handler with the three segments above.
- **Model:** `qlib.contrib.model.linear.LinearModel` (OLS; deterministic, numpy-only).
- **Backtest** (`port_analysis_config`, via `R.start` recorder context):
  - executor: `SimulatorExecutor(time_per_step="day", generate_portfolio_metrics=True)`.
  - strategy: `TopkDropoutStrategy(signal=(model, dataset), topk=2, n_drop=1)`.
  - backtest kwargs: test window, `account=100000`, `benchmark="ETHUSD"`,
    `exchange_kwargs={deal_price:"close", open_cost:0.0005, close_cost:0.0015,
    min_cost:0}` (no price-limit threshold).
  - records: `SignalRecord`, `SigAnaRecord`, `PortAnaRecord`.
- **Output:** read `PortAnaRecord`'s `port_analysis_1day.pkl` and print a compact table
  of the key rows — annualized return, information ratio, max drawdown — for both the
  absolute and excess-vs-ETH return. `run_experiment` returns these as a dict.

## Footprint & artifacts

Everything ephemeral. The Qlib binary dataset **and** the MLflow recorder
(`R.start(uri=<temp>/mlruns)`) are written under a single `tempfile.TemporaryDirectory`,
regenerated per run (tiny/fast), and cleaned up on exit. Only the ~60 KB CSV is
committed; nothing else persists in the repo or working tree.

## Packaging

Ensure hatchling ships `cli/example/data/crypto_ohlcv.csv` in the wheel (so the
installed `zcrypto example` console script works, not just `python -m cli`); locate it
at runtime via `importlib.resources`. Verify by building the wheel and confirming the
CSV is present.

## Testing

- **Unit (round-trip), `dataset.py`:** `build_provider` on a 3-row toy CSV → `qlib.init`
  + `D.features` reads back identical OHLCV values. De-risks the `.bin` format.
- **Smoke (CliRunner), command:** `zcrypto example` exits 0 and prints the metric
  labels; assert the returned metrics are **present and finite**, not exact magnitudes
  (avoids brittleness under numpy/qlib version drift). Runs the full pipeline on the
  bundled data (a few seconds).

## Out of scope

Live/streaming data, hyperparameter tuning, multiple models, plotting, persisted
artifacts, and any command other than `example`.

## Closeout (repo rules)

- This spec: `docs/specs/00000-example-subcommand-design.md`; plan reuses serial
  `00000` under `docs/plans/`.
- Final plan task appends a `docs/iterations-history.md` entry.
- Branch off `develop`; PR titled `feat(cli): iter-1 — Qlib ETH-USD example subcommand`
  into `develop`; per-commit + aggregated co-author trailers per the rules.
