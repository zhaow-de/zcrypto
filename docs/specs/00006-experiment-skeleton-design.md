# 00006 — `zcrypto experiment --recipe skeleton`: end-to-end Qlib experiment (train → backtest → report) harness

- **Date:** 2026-06-17
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-7
- **Scope:** A new `zcrypto experiment` command running an end-to-end Qlib
  pipeline — `qlib.init` → Alpha158 → LightGBM → `TopkDropoutStrategy` backtest
  → Plotly report — on the `./data` provider, with a **single swappable
  "recipe"** (selected by `--recipe`) as the only moving part, a **predict-ready
  run bundle**, and a **fingerprint-busted disk cache**. The command runs the
  full **train → backtest → report** cycle for one recipe (data prep is the
  separate `zcrypto data` command). Implements the daily baseline of
  `docs/research/01.binance-eea-spot-quant.md` (Stage 1 → early Stage 2).
- **Depends on:** spec `00005` (provider at `./data`; cache at `./data/cache`).

## Goal

`zcrypto experiment --recipe skeleton` trains the recipe's model, runs a
cross-sectional **long/cash** portfolio **backtest** starting from **10,000
USDT** over the test window, and writes an interactive Plotly report plus a
predict-ready run bundle — headlining the **ending USDT-equivalent fair-market
value** (`10,000 → XXXX USDT (+yy%)`). Swapping the single recipe module is how
the user experiments; everything else is fixed scaffolding.

The command is **`experiment`** with a **`--recipe`** selector: `experiment`
names the whole train → backtest → report run (the backtest is one step of it),
and `--recipe <name>` picks the recipe module that is the only moving part. A
future `predict --recipe <name>` reuses the same selector to reload this run's
trained bundle and emit live buy/sell signals.

## Background & constraints

- **Builds on the proven `example` pipeline shape** (`cli/example/workflow.py`):
  `qlib.init` → `DatasetH` → `model.fit` → `R.start` + `SignalRecord` +
  `PortAnaRecord` → metrics. The example *prints* metrics and *discards* its
  MLflow store; this command *persists* a run bundle and *plots*. It does **not**
  reuse the example's config (6 fake symbols, OLS, 6 months) — only its shape.
- **Research alignment** (`docs/research/01.binance-eea-spot-quant.md`): the 19
  USDT pairs **are** the roadmap's §7 basket (Tier 1–3); `ETHBTC` = its Tier-4
  crypto/crypto anchor; `BTCEUR` = its EUR sleeve. Strategy = cross-sectional ML
  ranker, long/cash, daily rebalance = `TopkDropoutStrategy` on Alpha158 +
  LightGBM (§5). "History trick": model on long USDT history — exactly our data
  (§6). Fees from §8. Stress windows LUNA (May 2022) + FTX (Nov 2022) from
  §6/§13. This is the roadmap's **Stage 1 → early Stage 2** daily baseline.
- **Crypto correctness.** 24/7 calendar comes from the dataset's `day.txt`.
  `REG_US` is chosen because it sets `trade_unit=1` and **no** price-limit
  (suits crypto, unlike `REG_CN`'s lot-of-100 + ±10% limit) — validated by the
  example's passing test. Fractional trading is enabled via `trade_unit=None`
  (a $10k account cannot buy whole-unit BTC/ETH; without this, high-priced coins
  are untradable and the backtest is silently wrong).
- **Simplicity-First.** This is one end-to-end run with a simple
  train/valid/test split. The robustness machinery (purged CV, regime overlay,
  slippage, point-in-time universe, paper trading) is **deferred** to open-topics
  `T0002`–`T0006` and explicitly out of scope; the plain split's label-overlap
  **leakage** is flagged, not fixed.
- **Repo rules unchanged.** README `## Usage` updated in the same change;
  `docs/iterations-history.md` closeout; branch + PR.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Verb / flag | **`experiment --recipe`** — `experiment` names the whole recipe run (train → backtest → report); `--recipe <name>` selects the recipe module. No `experiment --exp` redundancy; matches the "recipe = moving part" language; a future `predict --recipe <name>` reuses the flag. Package `cli/experiment/`. |
| Moving part | **One recipe module = the full recipe** (features + label + model + strategy + segments + universe + costs). Resolved by importing `cli/experiment/recipes/<name>.py` (filename = `--recipe` name). |
| Result shape | Cross-sectional **long/cash** portfolio (`TopkDropoutStrategy`); `account = 10,000` USDT; ending mark-to-close value = headline. |
| Universe | **19 USDT pairs traded**; `BTCEUR` + `ETHBTC` are **chart-only reference lines** (different quote currencies; excluded from the book to keep USDT accounting coherent). |
| Features / model / strategy | **Alpha158** / **`LGBModel`** / **`TopkDropoutStrategy(topk=5, n_drop=1)`**; label `Ref($close,-2)/Ref($close,-1)-1`. |
| Splits | train `2020-01-01..2023-12-31` (contains LUNA + FTX), valid `2024`, test `2025-01-01..2026-06-15`. |
| Fees | Recipe field with presets: **VIP2+BNB 12 bps** round-trip (`open=close=0.0006`) **default**; VIP2 std 16 bps (`0.0008`); zero-fee promo `0.0`. Size-scaled slippage deferred. |
| Fractional | `trade_unit=None` (exact Qlib spelling to confirm in the plan). |
| Persistence | **Option B run bundle:** persist the MLflow recorder **and** a per-run bundle (`model.pkl` copy + `run_meta.json` manifest + recipe snapshot). |
| Cache | Enable `DiskExpressionCache` + `DiskDatasetCache` → `./data/cache`; **fingerprint auto-bust** on `index.json` hash; `--refresh-cache` flag. |
| Plot | **Plotly 3-panel** HTML; `--svg` static export (kaleido); auto-open in browser unless `--no-open` / non-TTY. |
| Trades | Shown in **text** (stdout summary + `trades.csv`) and **plot** (timeline panel), derived from `positions_normal` day-over-day deltas. |
| Stress windows | LUNA `2022-05-07..05-16`, FTX `2022-11-06..11-14`; shaded on the context panel. |

## Package layout

```
cli/experiment/
├── command.py          # Typer `experiment` command + flags; wired into cli/__main__.py
├── scaffold.py         # FIXED pipeline: cache → init → dataset → fit → backtest → extract
├── report.py           # Plotly 3-panel report → HTML (+ optional SVG), browser open
├── cache.py            # disk-cache enable + index.json fingerprint auto-bust
├── stress.py           # named stress windows (LUNA, FTX)
├── recipes/
│   ├── base.py         # Recipe dataclass = the contract (the moving part)
│   └── skeleton.py     # the default recipe
└── data/               # small synthetic qlib FIXTURE for the test (committed)
```

Wired into `cli/__main__.py` via `app.command("experiment")(experiment)` (a
single command with options, like `example`).

## The Recipe — the one moving part

`recipes/base.py` defines a frozen dataclass; `recipes/skeleton.py` exposes a
module-level `RECIPE` instance. Resolution:
`importlib.import_module(f"cli.experiment.recipes.{name}")`; an unknown
`--recipe` errors with the list of available recipe files. To add an experiment,
drop in `recipes/<name>.py`.

```python
@dataclass(frozen=True)
class Recipe:
    name: str
    handler_config: dict            # Alpha158 DataHandlerLP config (features + processors)
    label: list                     # e.g. [["Ref($close,-2)/Ref($close,-1)-1"], ["LABEL0"]]
    model_config: dict              # LGBModel init_instance_by_config dict
    strategy_config: dict           # TopkDropoutStrategy config
    segments: dict                  # {"train": (...), "valid": (...), "test": (...)}
    universe: list[str]             # the 19 USDT pairs (traded)
    reference_instruments: list[str]  # ["BTCEUR", "ETHBTC"] (chart-only)
    account: float                  # 10_000
    benchmark: str                  # "BTCUSDT"
    fee_preset: str                 # "vip2_bnb" | "vip2_std" | "zero" → open/close cost
```

## Fixed scaffolding (`scaffold.py`)

Generalizes `example/workflow.py`, adapting its MLflow-cwd handling for
**persistence**:

1. **Cache** (`cache.py`): compute `sha256(data_dir/index.json)`; if it differs
   from `data_dir/cache/.dataset_fingerprint` (or `--refresh-cache`), `rmtree`
   `data_dir/cache`. Record the fresh fingerprint after init.
2. `qlib.init(provider_uri=data_dir, region=REG_US, expression_cache="DiskExpressionCache", dataset_cache="DiskDatasetCache", ...)`.
3. Build `DatasetH` from `recipe.handler_config` (Alpha158) over `recipe.universe`
   + `recipe.segments`.
4. `model = init_instance_by_config(recipe.model_config)`; `model.fit(dataset)`
   — **the train step**.
5. `with R.start(experiment_name=recipe.name)`: `R.save_objects(trained_model=model)`;
   `SignalRecord(model, dataset, recorder).generate()`;
   `PortAnaRecord(recorder, port_cfg, "day").generate()` — **the backtest step**,
   with `account`, `benchmark`, and `exchange_kwargs` carrying the **fee preset**
   + `trade_unit=None`.
6. Load back via the recorder: `report_normal_1day.pkl` (account-value series,
   return/cost/turnover), `positions_normal_1day.pkl` (→ trades),
   `port_analysis_1day.pkl` (excess metrics), and `risk_analysis` (absolute
   metrics).
7. Persist the MLflow store under `runs/mlruns/`; return metrics + series +
   trades + `run_id` to `command.py` for the **report step** + bundle write.

**MLflow-cwd caveat.** qlib 0.9.7's `MLflowExpManager` builds its lock path
relative to CWD (see the example's comment). To persist under `runs/mlruns/`,
run the qlib session with a controlled CWD + stable `exp_uri` (adapting the
example's temp-cwd / `git init` workaround). Exact mechanism finalized in the
plan.

## Disk cache + fingerprint busting (`cache.py`)

Qlib's disk cache lives at `<provider>/cache` = `./data/cache` (no relocation
needed — spec `00005` made `./data` gitignored, and `verify` ignores `cache/`).
Qlib's own invalidation is imperfect for in-place history rewrites, so busting is
made correct **on our side**: the cache is keyed implicitly to the dataset via
`sha256(index.json)` (the data pipeline rewrites `index.json` on every
`download` / `backfill` / `delist` / `rename`). Mismatch ⇒ wipe `./data/cache`
before use; `--refresh-cache` forces it. Cheap belt-and-suspenders at daily
scale; earns its keep as features/frequency grow.

## Output / run bundle

```
runs/                          # dir RETAINED via committed runs/.gitignore (* + !.gitignore)
├── mlruns/                    # MLflow recorder: trained_model, pred.pkl, label.pkl,
│                              #   port_analysis_1day.pkl, report_normal_1day.pkl,
│                              #   positions_normal_1day.pkl   (browse: `mlflow ui`)
└── <recipe>/<UTC-timestamp>/  # self-contained, predict-ready bundle
    ├── report.html            # interactive 3-panel Plotly report
    ├── report.svg             # static vector export (only with --svg)
    ├── metrics.json           # ending value, return, IR, max-DD, turnover
    ├── trades.csv             # full buy/sell log
    ├── run_meta.json          # manifest (below)
    ├── recipe_snapshot.json   # frozen copy of the recipe config
    └── model.pkl              # copy of the trained model (D3: self-contained)
```

`run_meta.json` records: `recipe`, `exp_id`, `run_id`, `git_commit`,
`qlib_version`, `lightgbm_version`, `segments`, `feature_names` (+ order),
`label`, `universe`, `fee_preset`, `account`, `benchmark`,
`data_calendar` (from/to), `index_fingerprint`, `created_at`. **Predict-readiness:**
a future `zcrypto predict --recipe <name> [--run latest]` reloads `model.pkl`,
rebuilds the fitted feature pipeline (mechanism — recompute-from-config vs.
pickle-the-handler — parked until `predict` is built; the manifest captures what
either needs), scores today's bars, and applies the recipe's top-k selection to
emit buy/sell signals.

## Plotly report (`report.py`) — three panels

- **Panel 1 — equity (test window).** Strategy account value vs. `BTCUSDT`
  buy-&-hold, both rebased to 10,000 at test start. Title = ending value +
  return; metrics annotation (annualized return, IR, max-DD).
- **Panel 2 — trade timeline (test window, shared x-axis with Panel 1).**
  x = date, y = symbol; green ▲ = buy, red ▼ = sell; marker size ∝ trade value.
- **Panel 3 — market context (full 2020→2026).** `BTCUSDT` + `BTCEUR` + `ETHBTC`
  rebased to 10,000 at 2020 (the two non-USDT as **dashed**, labeled "indexed");
  **LUNA + FTX shaded** (`vrect` + annotation); optional marker for the
  test-window span.

`write_html(include_plotlyjs="inline")`; auto-open via `webbrowser` unless
`--no-open` or non-TTY; `--svg` → `report.svg` via kaleido. Reference-line prices
fetched via `D.features` after init.

## Trades (text + data)

Derive from `positions_normal_1day.pkl` day-over-day deltas (buy = +qty,
sell = −qty), priced at close. `trades.csv` = full log
(`date, side, symbol, qty, price, value`). Stdout summary = total trades / buys /
sells, turnover, and a per-symbol trade count.

## CLI surface

```
zcrypto experiment [--recipe skeleton] [--data-dir ./data] [--out ./runs] \
                   [--open/--no-open] [--svg/--no-svg] [--refresh-cache]
```

Global `--log` / `--log-level` apply. The headline (`10,000 → XXXX USDT`), the
trade summary, and the artifact paths print to stdout.

## Dependencies

- **plotly** — required (charts).
- **lightgbm** — required by `LGBModel`; confirm whether `pyqlib` already pulls
  it, add to `pyproject.toml` if not.
- **kaleido** — for `--svg` static export.

## Error handling & logging

- `--recipe` not found → error listing the available `recipes/*.py`.
- `--data-dir` missing or not a Qlib dataset (no `calendars/day.txt`) →
  actionable error.
- Universe instrument absent from the dataset, or a segment outside the calendar
  → error.
- **JSONL log events** (via existing `cli/logging`): cache check/bust, qlib
  init, dataset build, train start/finish, backtest, metrics, report written,
  bundle written.

## Crypto-correctness notes (validated / assumed / unknown)

- *validated* — `REG_US` (`trade_unit=1`, no limit) suits crypto; the example
  passes with it. 24/7 calendar comes from the dataset's `day.txt`.
- *assumed* — `trade_unit=None` enables fractional fills (confirm exact param in
  the plan).
- *assumed* — Alpha158 runs cleanly on the crypto fields (`vwap`/`factor`
  present); confirm in the plan.
- *unknown* — whether `lightgbm` is already installed transitively; confirm /
  add the dep in the plan.

## Testing strategy

- **Synthetic Qlib fixture** (`cli/experiment/data/`, committed, mirroring how
  `example` bundles its CSV): a few instruments **including** `BTCUSDT` /
  `BTCEUR` / `ETHBTC`, a calendar long enough for Alpha158's windows + the three
  segments, and spanning a fake stress window so the shading path is exercised.
- **Integration test** (`experiment --recipe skeleton --data-dir <fixture>`):
  finite metrics; ending value computed; `report.html` written with three panels
  + shaded regions; non-empty `trades.csv`; `run_meta.json` + `model.pkl`
  present; `cache/` built with a `.dataset_fingerprint`; `--refresh-cache` and a
  mutated `index.json` both trigger a bust.
- **Unit tests:** recipe resolution (valid / invalid `--recipe`); fingerprint
  compute/compare; trades-from-positions diff; rebasing math; reference-line
  fetch.
- **Operational:** assert the expected JSONL events are emitted.
- **Manual verification:** run on the real `./data`; open `report.html`.

## Out of scope (deferred → open-topics)

- **`T0002`** purged k-fold CV + embargo / CPCV / deflated Sharpe — the plain
  split's leakage is flagged here, fixed there.
- **`T0003`** BTC-trend regime overlay (long/cash gating + vol targeting).
- **`T0004`** size-scaled slippage + maker-fill realism.
- **`T0005`** (open-topic) point-in-time universe / survivorship.
- **`T0006`** (open-topic) paper-trading harness before live.
- The **realistic-expectations** framing (≈0.5–1.2 net Sharpe, 15–30% DD, may
  trail a BTC hold) is recorded so results are read with the right prior.
- The future **`predict`** command itself (reads this run bundle); the
  fitted-pipeline reload mechanism is parked until then.

## References

- Prerequisite: spec `00005` (data relayout; provider `./data`).
- Research roadmap: `docs/research/01.binance-eea-spot-quant.md`
  (§5 strategy, §6 data/CV, §7 basket, §8 fees, §13 stages).
- Example pipeline: `cli/example/workflow.py`.
- Deferred items: `docs/open-topics/T0002`–`T0006`.
- Qlib: Alpha158 / `LGBModel` / `TopkDropoutStrategy`; paper arXiv 2009.11189.
