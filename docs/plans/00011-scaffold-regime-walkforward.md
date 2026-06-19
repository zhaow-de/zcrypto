# Scaffold extension: pluggable strategy + BTC-regime overlay + walk-forward — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the experiment strategy recipe-pluggable, ship a parameterized BTC-trend regime overlay (resolves open-topic `00003`), and add walk-forward holdout retraining — the two scaffold-level answers to the regime non-stationarity the `steady` validation exposed.

**Architecture:** `Recipe` gains a full `strategy_config` (mirroring `model_config`) that both `scaffold.py` (holdout) and `cpcv.py` (path backtests) build from, injecting the runtime `signal`. A new `RegimeGatedTopkStrategy` (a `TopkDropoutStrategy` subclass) scales gross exposure via qlib's `get_risk_degree` hook off a pure, precomputed BTC-trend multiplier. Walk-forward is a holdout-only periodic-retrain branch in `run_experiment`, orthogonal to CPCV.

**Tech Stack:** Python 3.12, uv, qlib (`pyqlib`), LightGBM, pandas, pytest, ruff (line length 132). Redis required for `experiment` (qlib disk-cache locks): `scripts/redis.sh start`.

## Global Constraints

- **Behavior-preserving for benchmarks:** `skeleton` and `steady` must build the **identical** `TopkDropoutStrategy` (same kwargs) with walk-forward off, so they remain valid benchmarks. A regression test guards this.
- **Leak-free:** any train→predict split (CPCV *and* walk-forward) purges `label_horizon_days` between train end and predict start.
- **No new data / no new runtime deps** (scipy/lightgbm/qlib already present).
- **Spot-only ⇒ long/cash:** the overlay scales gross exposure toward cash, never short.
- ruff clean (`uv run ruff check` + `ruff format --check`); each Claude-authored commit gets a subagent `Reviewed-by:` before push (`.claude/rules/commit-messages.md`).
- Full `uv run pytest` is slow (~15-20 min, redis-gated experiment tests); iterate with targeted `uv run pytest path::test`, Redis up.

## File structure

```
cli/experiment/
├── recipes/base.py            # MODIFY: Recipe.strategy_config replaces strategy_kwargs; + wf_* knobs
├── recipes/skeleton.py        # MODIFY: migrate strategy_kwargs -> strategy_config (TopkDropout, identical)
├── recipes/steady.py          # MODIFY: same migration (identical book)
├── recipes/regime_steady.py   # NEW: steady's book + RegimeGatedTopkStrategy(binary-200) + walk-forward
├── strategies/__init__.py     # NEW (package marker, one-line docstring)
├── strategies/regime.py       # NEW: regime_exposure_series (pure) + RegimeGatedTopkStrategy (qlib wrapper)
├── walkforward.py             # NEW: build_wf_periods (pure) + run_walkforward_holdout (scaffold helper)
├── scaffold.py                # MODIFY: strategy_config_with_signal helper; use in _port_analysis_config; wf branch in run_experiment
└── cpcv.py                    # MODIFY: build path-backtest strategy via strategy_config_with_signal
tests/
├── test_experiment_recipe.py  # EXTEND: contract migration, benchmark preservation, regime_steady
├── test_regime_strategy.py    # NEW: regime_exposure_series + get_risk_degree logic
├── test_walkforward.py        # NEW: build_wf_periods
├── test_experiment_scaffold.py# EXTEND (redis-gated): seam preserves skeleton; regime + wf integration
└── test_experiment_cpcv.py    # EXTEND (redis-gated): cpcv builds strategy from strategy_config
```

Two phases: **Phase A** = Tasks 1–5 (seam + regime overlay, independently shippable). **Phase B** = Tasks 6–7 (walk-forward). **Task 8** = closeout.

---

## Phase A — pluggable strategy seam + regime overlay

### Task 1: Strategy seam — `strategy_config` replaces `strategy_kwargs`; wire scaffold + cpcv; migrate benchmarks

**Files:**
- Modify: `cli/experiment/recipes/base.py` (Recipe fields)
- Modify: `cli/experiment/scaffold.py` (helper + `_port_analysis_config`)
- Modify: `cli/experiment/cpcv.py` (path backtest, ~line 199)
- Modify: `cli/experiment/recipes/skeleton.py`, `cli/experiment/recipes/steady.py`
- Test: `tests/test_experiment_recipe.py`

**Interfaces:**
- Produces: `Recipe.strategy_config: dict` (full `{class, module_path, kwargs}`); `Recipe.wf_enabled: bool=False`, `wf_retrain_freq: str="quarter"`, `wf_window: str="expanding"`, `wf_rolling_years: int=3`. `scaffold.strategy_config_with_signal(strategy_config: dict, signal) -> dict` returning `{**strategy_config, "kwargs": {**strategy_config["kwargs"], "signal": signal}}`.
- Consumes: nothing new.

- [ ] **Step 1: Failing test — seam helper + migration + benchmark preservation** in `tests/test_experiment_recipe.py`:

```python
def test_strategy_config_with_signal_injects_signal():
    from cli.experiment.scaffold import strategy_config_with_signal
    cfg = {"class": "TopkDropoutStrategy", "module_path": "m", "kwargs": {"topk": 5}}
    out = strategy_config_with_signal(cfg, signal="SIG")
    assert out["class"] == "TopkDropoutStrategy" and out["module_path"] == "m"
    assert out["kwargs"] == {"topk": 5, "signal": "SIG"}
    assert cfg["kwargs"] == {"topk": 5}  # input not mutated


def test_skeleton_strategy_config_is_topk_dropout_unchanged():
    r = resolve_recipe("skeleton")
    sc = r.strategy_config
    assert sc["class"] == "TopkDropoutStrategy"
    assert sc["module_path"] == "qlib.contrib.strategy.signal_strategy"
    assert sc["kwargs"] == {"topk": 5, "n_drop": 1}


def test_steady_strategy_config_is_topk_dropout_unchanged():
    sc = resolve_recipe("steady").strategy_config
    assert sc["class"] == "TopkDropoutStrategy"
    assert sc["kwargs"] == {"topk": 10, "n_drop": 1, "hold_thresh": 5}


def test_recipe_walkforward_defaults_off():
    r = resolve_recipe("skeleton")
    assert r.wf_enabled is False
    assert r.wf_retrain_freq == "quarter"
    assert r.wf_window == "expanding"
    assert r.wf_rolling_years == 3
```

Also delete the now-obsolete `strategy_kwargs` assertions: in `test_steady_low_turnover_strategy` replace `resolve_recipe("steady").strategy_kwargs == {...}` with the `strategy_config["kwargs"]` form above (keep one such assertion, drop duplicates).

- [ ] **Step 2: Run — expect FAIL** (`strategy_config` / helper absent):
`uv run pytest tests/test_experiment_recipe.py -q` → FAIL (AttributeError / ImportError).

- [ ] **Step 3: Recipe contract** — in `base.py`, in `@dataclass Recipe`: replace the `strategy_kwargs: dict` field with `strategy_config: dict  # full init_instance_by_config dict for the strategy`. Add after the CPCV knobs:
```python
    # Walk-forward holdout retraining (see docs/specs/00011). Off = single-fit holdout.
    wf_enabled: bool = field(default=False)
    wf_retrain_freq: str = field(default="quarter")  # quarter | year
    wf_window: str = field(default="expanding")  # expanding | rolling
    wf_rolling_years: int = field(default=3)
```

- [ ] **Step 4: Seam helper + wiring.** In `scaffold.py` add:
```python
def strategy_config_with_signal(strategy_config: dict, signal) -> dict:
    """Inject the runtime ``signal`` into a recipe's static strategy config."""
    return {**strategy_config, "kwargs": {**strategy_config.get("kwargs", {}), "signal": signal}}
```
In `scaffold._port_analysis_config`, replace the hardcoded `"strategy": {...TopkDropoutStrategy..., "kwargs": {**recipe.strategy_kwargs, "signal": (model, dataset)}}` block with:
```python
        "strategy": strategy_config_with_signal(recipe.strategy_config, (model, dataset)),
```
In `cpcv.py` (the per-path `backtest(...)` call, ~line 199), replace the inline `strategy={...TopkDropoutStrategy..., "kwargs": {**recipe.strategy_kwargs, "signal": signal}}` with:
```python
                strategy=strategy_config_with_signal(recipe.strategy_config, signal),
```
Add `strategy_config_with_signal` to the `from cli.experiment.scaffold import ...` line in `cpcv.py`.

- [ ] **Step 5: Migrate benchmarks.** In `skeleton.py` replace `strategy_kwargs={"topk": 5, "n_drop": 1}` with:
```python
    strategy_config={
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {"topk": 5, "n_drop": 1},
    },
```
In `steady.py` replace `strategy_kwargs={"topk": 10, "n_drop": 1, "hold_thresh": 5}` with the same shape carrying `{"topk": 10, "n_drop": 1, "hold_thresh": 5}`. Update the steady comment to reference `strategy_config`.

- [ ] **Step 6: Run — expect PASS + ruff**: `uv run pytest tests/test_experiment_recipe.py -q` → PASS; `uv run ruff check cli/experiment tests && uv run ruff format --check cli/experiment tests` → clean.

- [ ] **Step 7: Commit**
```bash
git add cli/experiment/recipes/base.py cli/experiment/recipes/skeleton.py cli/experiment/recipes/steady.py cli/experiment/scaffold.py cli/experiment/cpcv.py tests/test_experiment_recipe.py
git commit -m "feat(experiment): make the backtest strategy recipe-pluggable via strategy_config

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Pure regime exposure logic — `regime_exposure_series`

**Files:**
- Create: `cli/experiment/strategies/__init__.py`, `cli/experiment/strategies/regime.py`
- Test: `tests/test_regime_strategy.py`

**Interfaces:**
- Produces: `regime_exposure_series(close: pd.Series, *, mode="binary", ma_window=200, ma_fast=None, band=0.0, chop_exposure=0.5, vol_target=None, vol_lookback=30) -> pd.Series` — a date-indexed multiplier in `[0, 1]`. Warmup dates (insufficient MA history) → `1.0`.

- [ ] **Step 1: Failing test** `tests/test_regime_strategy.py`:
```python
import numpy as np
import pandas as pd
from cli.experiment.strategies.regime import regime_exposure_series

def _close(values):
    idx = pd.date_range("2020-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")

def test_binary_full_above_ma_cash_below():
    # rising then falling around a short MA window
    up = list(range(1, 21)); down = list(range(20, 0, -1))
    s = regime_exposure_series(_close(up + down), mode="binary", ma_window=5)
    # warmup (first <5) -> 1.0
    assert (s.iloc[:4] == 1.0).all()
    # deep in the uptrend -> close > MA -> 1.0; deep in downtrend -> 0.0
    assert s.iloc[18] == 1.0
    assert s.iloc[-2] == 0.0

def test_graded_has_chop_tier():
    flat = [100.0] * 30
    s = regime_exposure_series(_close(flat), mode="graded", ma_window=5, band=0.05, chop_exposure=0.5)
    # flat price == MA -> within band -> chop tier
    assert s.iloc[-1] == 0.5

def test_cross_uses_fast_vs_slow():
    up = list(range(1, 41))
    s = regime_exposure_series(_close(up), mode="cross", ma_window=20, ma_fast=5)
    # steady uptrend: fast MA > slow MA -> 1.0 once both windows are warm
    assert s.iloc[-1] == 1.0

def test_vol_target_scales_down_high_vol():
    rng = np.random.default_rng(0)
    calm = _close(100 + np.cumsum(rng.normal(0, 0.1, 400)))
    s_off = regime_exposure_series(calm, mode="binary", ma_window=5)
    s_on = regime_exposure_series(calm, mode="binary", ma_window=5, vol_target=0.0001, vol_lookback=20)
    # a tiny vol_target forces heavy downscaling vs off
    assert s_on.iloc[-1] < s_off.iloc[-1]
    assert (s_on >= 0).all() and (s_on <= 1).all()

def test_multiplier_bounded_unit_interval():
    s = regime_exposure_series(_close(list(range(1, 60))), mode="binary", ma_window=10)
    assert s.min() >= 0.0 and s.max() <= 1.0
```

- [ ] **Step 2: Run — expect FAIL** (module absent): `uv run pytest tests/test_regime_strategy.py -q` → FAIL.

- [ ] **Step 3: Implement.** `strategies/__init__.py`: `"""Pluggable backtest strategies for the experiment pipeline."""`. `strategies/regime.py` (pure part):
```python
"""BTC-trend regime overlay: pure exposure logic + a TopkDropout wrapper.

The pure ``regime_exposure_series`` maps a benchmark close series to a per-date
gross-exposure multiplier in [0, 1]; ``RegimeGatedTopkStrategy`` is the thin qlib
wrapper that applies it through ``get_risk_degree``. See docs/specs/00011.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_TRADING_DAYS = 365  # crypto trades 24/7


def regime_exposure_series(
    close: pd.Series,
    *,
    mode: str = "binary",
    ma_window: int = 200,
    ma_fast: int | None = None,
    band: float = 0.0,
    chop_exposure: float = 0.5,
    vol_target: float | None = None,
    vol_lookback: int = 30,
) -> pd.Series:
    close = close.astype("float64").sort_index()
    sma = close.rolling(ma_window).mean()
    if mode == "binary":
        mult = (close > sma).astype("float64")
    elif mode == "graded":
        mult = pd.Series(chop_exposure, index=close.index, dtype="float64")
        mult[close > sma * (1 + band)] = 1.0
        mult[close < sma * (1 - band)] = 0.0
    elif mode == "cross":
        if ma_fast is None:
            raise ValueError("mode='cross' requires ma_fast")
        sma_fast = close.rolling(ma_fast).mean()
        mult = (sma_fast > sma).astype("float64")
    else:
        raise ValueError(f"unknown regime mode: {mode!r}")
    # Warmup (any SMA NaN) -> cannot gate -> stay fully invested.
    warm = sma.isna() | (close.rolling(ma_fast).mean().isna() if mode == "cross" else False)
    mult[warm] = 1.0
    if vol_target is not None:
        realized = close.pct_change().rolling(vol_lookback).std() * np.sqrt(_TRADING_DAYS)
        scale = (vol_target / realized).clip(upper=1.0)
        mult = mult * scale.fillna(1.0)
    return mult.clip(0.0, 1.0)
```

- [ ] **Step 4: Run — expect PASS + ruff** on the two files.

- [ ] **Step 5: Commit**
```bash
git add cli/experiment/strategies/__init__.py cli/experiment/strategies/regime.py tests/test_regime_strategy.py
git commit -m "feat(experiment): add pure BTC-regime exposure logic (regime_exposure_series)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `RegimeGatedTopkStrategy` — the qlib wrapper

**Files:**
- Modify: `cli/experiment/strategies/regime.py` (add the class)
- Test: `tests/test_regime_strategy.py` (add `get_risk_degree` logic test)

**Interfaces:**
- Consumes: `regime_exposure_series` (Task 2); qlib `TopkDropoutStrategy`.
- Produces: `RegimeGatedTopkStrategy(*, regime_mode="binary", regime_benchmark="BTCUSDT", regime_ma_window=200, regime_ma_fast=None, regime_band=0.0, chop_exposure=0.5, vol_target=None, vol_lookback=30, **topk_kwargs)`. Referenced by config as `{"class": "RegimeGatedTopkStrategy", "module_path": "cli.experiment.strategies.regime", "kwargs": {...}}`.

**RECON (implementer):** confirm in qlib `BaseSignalStrategy.get_risk_degree(trade_step=None)` and `self.trade_calendar.get_step_time(trade_step)` (used by `TopkDropoutStrategy.generate_trade_decision`, `signal_strategy.py:140-142`); `qlib.data.D.features([sym], ["$close"], freq="day")` returns a MultiIndex `(instrument, datetime)` frame. The exposure precompute belongs in `__init__` (qlib is initialized by backtest time).

- [ ] **Step 1: Failing test** — test the `get_risk_degree` math without a live backtest by constructing the instance and stubbing its precomputed series + trade_calendar:
```python
def test_regime_get_risk_degree_scales_base_by_multiplier(monkeypatch):
    from cli.experiment.strategies import regime as rg
    # Avoid the qlib data query in __init__: stub _build_exposure to a fixed series.
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    monkeypatch.setattr(
        rg.RegimeGatedTopkStrategy, "_build_exposure",
        lambda self: pd.Series([1.0, 0.0, 0.5], index=idx),
    )
    strat = rg.RegimeGatedTopkStrategy(topk=5, n_drop=1, signal=pd.Series(dtype="float64"), risk_degree=0.95)

    class _Cal:  # minimal trade_calendar stub
        def __init__(self, d): self._d = d
        def get_trade_step(self): return 0
        def get_step_time(self, step, shift=0): return (self._d, self._d)

    strat.trade_calendar = _Cal(idx[1])  # risk-off date -> multiplier 0.0
    assert strat.get_risk_degree(0) == 0.0
    strat.trade_calendar = _Cal(idx[0])  # full
    assert strat.get_risk_degree(0) == 0.95
    strat.trade_calendar = _Cal(idx[2])  # chop -> 0.95 * 0.5
    assert abs(strat.get_risk_degree(0) - 0.475) < 1e-9
    # a date past the series -> carry forward the last value (0.5)
    strat.trade_calendar = _Cal(pd.Timestamp("2025-06-01"))
    assert abs(strat.get_risk_degree(0) - 0.475) < 1e-9
```

- [ ] **Step 2: Run — expect FAIL** (class absent).

- [ ] **Step 3: Implement** the class in `strategies/regime.py`:
```python
from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy


class RegimeGatedTopkStrategy(TopkDropoutStrategy):
    """TopkDropout whose gross exposure is scaled by a BTC-trend regime multiplier."""

    def __init__(
        self,
        *,
        regime_mode="binary",
        regime_benchmark="BTCUSDT",
        regime_ma_window=200,
        regime_ma_fast=None,
        regime_band=0.0,
        chop_exposure=0.5,
        vol_target=None,
        vol_lookback=30,
        **kwargs,
    ):
        super().__init__(**kwargs)  # topk, n_drop, hold_thresh, signal, risk_degree, ...
        self.regime_mode = regime_mode
        self.regime_benchmark = regime_benchmark
        self.regime_ma_window = regime_ma_window
        self.regime_ma_fast = regime_ma_fast
        self.regime_band = regime_band
        self.chop_exposure = chop_exposure
        self.vol_target = vol_target
        self.vol_lookback = vol_lookback
        self._exposure = self._build_exposure()

    def _build_exposure(self) -> pd.Series:
        from qlib.data import D

        df = D.features([self.regime_benchmark], ["$close"], freq="day")
        close = df["$close"].droplevel(0)  # drop instrument level -> date-indexed
        return regime_exposure_series(
            close,
            mode=self.regime_mode,
            ma_window=self.regime_ma_window,
            ma_fast=self.regime_ma_fast,
            band=self.regime_band,
            chop_exposure=self.chop_exposure,
            vol_target=self.vol_target,
            vol_lookback=self.vol_lookback,
        )

    def get_risk_degree(self, trade_step=None):
        step = trade_step if trade_step is not None else self.trade_calendar.get_trade_step()
        _, date = self.trade_calendar.get_step_time(step)
        date = pd.Timestamp(date).normalize()
        exp = self._exposure
        # exact date, else carry forward the most recent prior value, else full.
        if date in exp.index:
            mult = float(exp.loc[date])
        else:
            prior = exp.loc[:date]
            mult = float(prior.iloc[-1]) if len(prior) else 1.0
        return self.risk_degree * mult
```

- [ ] **Step 4: Run — expect PASS + ruff.**

- [ ] **Step 5: Commit**
```bash
git add cli/experiment/strategies/regime.py tests/test_regime_strategy.py
git commit -m "feat(experiment): add RegimeGatedTopkStrategy (exposure via get_risk_degree)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `regime_steady` recipe (regime overlay, walk-forward off for now)

**Files:**
- Create: `cli/experiment/recipes/regime_steady.py`
- Test: `tests/test_experiment_recipe.py`

**Interfaces:**
- Consumes: `RegimeGatedTopkStrategy` (Task 3), `strategy_config` + wf knobs (Task 1).

- [ ] **Step 1: Failing test** in `tests/test_experiment_recipe.py`:
```python
def test_regime_steady_uses_regime_strategy():
    r = resolve_recipe("regime_steady")
    sc = r.strategy_config
    assert sc["class"] == "RegimeGatedTopkStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] is None  # default off
    # steady's book preserved
    assert sc["kwargs"]["topk"] == 10 and sc["kwargs"]["hold_thresh"] == 5

def test_regime_steady_matches_steady_book_and_label():
    rg, st = resolve_recipe("regime_steady"), resolve_recipe("steady")
    assert rg.universe == st.universe and rg.segments == st.segments
    assert rg.handler_kwargs["label"] == st.handler_kwargs["label"]
    assert rg.label_horizon_days == st.label_horizon_days == 6
    assert rg.wf_enabled is False  # flipped on in Phase B
```

- [ ] **Step 2: Run — expect FAIL** (recipe absent).

- [ ] **Step 3: Implement** `recipes/regime_steady.py` — import `steady`'s handler_kwargs/model_config/universe/segments verbatim (copy the same values steady uses; keep self-contained per the recipe convention) and set:
```python
    strategy_config={
        "class": "RegimeGatedTopkStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "topk": 10, "n_drop": 1, "hold_thresh": 5,
            "regime_mode": "binary", "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200, "vol_target": None,
        },
    },
    ...  # label_horizon_days=6, feature_lookback_days=60, cv_n_groups=6, cv_test_groups=2, fees/account/benchmark = steady
    wf_enabled=False,  # Phase B flips this to True
```
Write a docstring stating the thesis (steady's book + regime gate + [pending] walk-forward) and that it's a falsifiable hypothesis judged by CPCV/PSR/PBO.

- [ ] **Step 4: Run — expect PASS + ruff.**

- [ ] **Step 5: Commit**
```bash
git add cli/experiment/recipes/regime_steady.py tests/test_experiment_recipe.py
git commit -m "feat(experiment): add regime_steady recipe (steady book + binary-200 regime overlay)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Phase-A integration (redis-gated) — benchmark preserved + regime runs

**Files:**
- Test: `tests/test_experiment_scaffold.py` (extend) and/or `tests/test_experiment_cpcv.py`

**RECON (implementer):** mirror the existing redis-gated experiment test setup (fixture data dir + `redis_preflight`/skip marker). Reuse the synthetic qlib fixture used by `test_experiment_scaffold.py`.

- [ ] **Step 1: Failing/▶ test** — add a redis-gated test that:
  1. runs `skeleton` (or a `--quick` equivalent via the scaffold API) and asserts it completes and the **built strategy is `TopkDropoutStrategy`** (benchmark preserved through the seam) — assert on `strategy_config_with_signal(resolve_recipe("skeleton").strategy_config, "x")["class"] == "TopkDropoutStrategy"` plus a smoke run;
  2. runs `regime_steady` (wf still off) end-to-end and asserts the run produces metrics and that the regime strategy reduced exposure on ≥1 date in a synthetic BTC downtrend (e.g., assert the run completes and, on a fixture engineered with a late downtrend, `regime_exposure_series` over the fixture's BTC close yields a `0.0` somewhere).

Keep the heavy assertions minimal (the unit tests cover the logic); this is a smoke + wiring guard. Mark `@pytest.mark.skipif(not _redis_up(), ...)` consistent with the file.

- [ ] **Step 2: Run** (Redis up): `scripts/redis.sh start`; `uv run pytest tests/test_experiment_scaffold.py -q` → PASS (or document skip if redis down).

- [ ] **Step 3: Commit**
```bash
git add tests/test_experiment_scaffold.py
git commit -m "test(experiment): redis-gated Phase-A integration — seam preserves skeleton, regime runs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Phase B — walk-forward retraining

### Task 6: Pure walk-forward period splitter — `build_wf_periods`

**Files:**
- Create: `cli/experiment/walkforward.py`
- Test: `tests/test_walkforward.py`

**Interfaces:**
- Produces: `build_wf_periods(train_start: str, test_start: str, test_end: str, *, freq="quarter", window="expanding", rolling_years=3, purge_days=0) -> list[tuple[tuple[str, str], tuple[str, str]]]` — each item is `((train_start, train_end), (predict_start, predict_end))`, ISO date strings; `train_end = predict_start − (purge_days + 1 day)`; expanding train starts at `train_start`, rolling at `predict_start − rolling_years`.

- [ ] **Step 1: Failing test** `tests/test_walkforward.py`:
```python
from cli.experiment.walkforward import build_wf_periods

def test_quarterly_expanding_covers_test_window():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2025-12-31", freq="quarter", window="expanding")
    assert len(periods) == 4
    # first predict quarter
    assert periods[0][1] == ("2025-01-01", "2025-03-31")
    # last predict quarter clamped to test_end
    assert periods[-1][1][1] == "2025-12-31"
    # expanding train always starts at train_start
    assert all(tr[0] == "2020-01-01" for tr, _ in periods)

def test_purge_gap_between_train_end_and_predict_start():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2025-03-31", freq="quarter", purge_days=6)
    (_, train_end), (predict_start, _) = periods[0]
    import pandas as pd
    assert pd.Timestamp(predict_start) - pd.Timestamp(train_end) == pd.Timedelta(days=7)  # 6 purge + 1

def test_rolling_window_drops_old_history():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2025-03-31", window="rolling", rolling_years=3)
    (train_start, _), (predict_start, _) = periods[0]
    import pandas as pd
    assert pd.Timestamp(train_start) == pd.Timestamp(predict_start) - pd.DateOffset(years=3)

def test_annual_freq():
    periods = build_wf_periods("2020-01-01", "2025-01-01", "2026-06-30", freq="year")
    assert len(periods) == 2
    assert periods[0][1] == ("2025-01-01", "2025-12-31")
    assert periods[1][1] == ("2026-01-01", "2026-06-30")
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** `walkforward.py` (`build_wf_periods` only this task) using pandas date offsets (`pd.tseries.offsets.QuarterEnd`/`YearEnd`, `pd.DateOffset`). Clamp the final predict end to `test_end`; format all dates `YYYY-MM-DD`.

- [ ] **Step 4: Run — expect PASS + ruff.**

- [ ] **Step 5: Commit**
```bash
git add cli/experiment/walkforward.py tests/test_walkforward.py
git commit -m "feat(experiment): add pure walk-forward period splitter (build_wf_periods)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Walk-forward holdout runner — wire into `run_experiment`; flip `regime_steady`

**Files:**
- Modify: `cli/experiment/walkforward.py` (add `run_walkforward_holdout`)
- Modify: `cli/experiment/scaffold.py` (`run_experiment` branch on `recipe.wf_enabled`)
- Modify: `cli/experiment/recipes/regime_steady.py` (`wf_enabled=True`)
- Test: `tests/test_experiment_scaffold.py` (redis-gated)

**Interfaces:**
- Consumes: `build_wf_periods` (Task 6); cpcv's training helpers (`_lgb_params`, `_materialize`-style, `_split_xy`, `_rows_on`) — **extract the shared training helpers** that both `cpcv.py` and `walkforward.py` need into a small module or import them (DRY; do not duplicate `_lgb_params`).
- Produces: `run_walkforward_holdout(recipe, *, data_dir) -> RunResult` (same `RunResult` shape `scaffold.run_experiment` returns).

**Design:** When `recipe.wf_enabled`, `run_experiment` delegates the holdout to `run_walkforward_holdout`, which for each `build_wf_periods(...)` period materializes the Alpha158 matrix over `[train_start..predict_end]`, fits LightGBM on the train rows, predicts the period, backtests it via qlib `backtest()` (cpcv-style), and **concatenates** the per-period `report_df` (`return`/`cost`/`bench`) into one continuous holdout series → the same metrics/`account_curve`/`benchmark_curve`/PSR/`returns.csv` the single-fit path produces. CPCV is unchanged and still runs before the holdout.

**RECON (implementer):** (1) decide whether to reuse `cpcv`'s `_materialize`/`_lgb_params`/`_split_xy`/`_rows_on` by importing or extracting to a shared helper module — pick the smaller diff, keep DRY. (2) `qlib.backtest.backtest()` returns `(portfolio_metric_dict, indicator_dict)`; the `report_df` is `portfolio_metric_dict["1day"][0]`. Positions/trades are **not** required for the walk-forward validation — if positions aren't readily collectable from `backtest()`, the wf `RunResult` may carry empty `positions`/skip `trades.csv` (document it; the report renders from `report_df`, and `rank`/PSR use `returns.csv`). Confirm the downstream (`command.py`, `report.py`) tolerates that, or guard it.

- [ ] **Step 1: Failing test** (redis-gated) `tests/test_experiment_scaffold.py`:
```python
@pytest.mark.skipif(not _redis_up(), reason="needs redis (scripts/redis.sh start)")
def test_walkforward_holdout_stitches_multiple_periods(tmp_path, synthetic_data_dir):
    from cli.experiment.recipes.base import resolve_recipe
    from cli.experiment.scaffold import run_experiment
    import dataclasses
    recipe = dataclasses.replace(resolve_recipe("steady"), name="wf_probe", wf_enabled=True, wf_retrain_freq="quarter")
    result = run_experiment(recipe, data_dir=synthetic_data_dir, out_dir=tmp_path)
    # stitched holdout covers the full test window contiguously
    assert len(result.report_df) > 0
    assert result.report_df.index.is_monotonic_increasing
    # metrics present (the validation outputs)
    assert "strategy_absolute" in result.metrics
```
(Adapt `synthetic_data_dir` / fixture name to the file's existing fixtures.)

- [ ] **Step 2: Run — expect FAIL** (`wf_enabled` ignored / runner absent).

- [ ] **Step 3: Implement** `run_walkforward_holdout` + the `run_experiment` branch; flip `regime_steady` `wf_enabled=True` and update its docstring/test (`test_regime_steady...` `wf_enabled is True`).

- [ ] **Step 4: Run — expect PASS + ruff + full targeted suite** (`uv run pytest tests/test_walkforward.py tests/test_regime_strategy.py tests/test_experiment_recipe.py -q`, then the redis-gated scaffold test).

- [ ] **Step 5: Commit**
```bash
git add cli/experiment/walkforward.py cli/experiment/scaffold.py cli/experiment/recipes/regime_steady.py tests/test_experiment_scaffold.py tests/test_experiment_recipe.py
git commit -m "feat(experiment): walk-forward holdout retraining; enable it on regime_steady

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Closeout — docs, open-topics, validation, iterations-history

**Files:**
- Modify: `README.md` (`## Usage`)
- Modify: `docs/open-topics/00003-btc-regime-overlay.md`, `00004-execution-slippage-fills.md`, `docs/open-topics/README.md`
- Create: `docs/open-topics/00007-multi-window-stress.md`, `docs/open-topics/00008-pluggable-feature-handler.md`
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: README `## Usage`** — document the `regime_steady` recipe, the `strategy_config` recipe field, and the `wf_*` knobs (the `mdformat` hook owns the README TOC — don't hand-edit it).

- [ ] **Step 2: Resolve `00003`** — flip front-matter `status: open → resolved`; add a `## Resolution` note (regime overlay shipped: `RegimeGatedTopkStrategy`, modes binary/graded/cross, vol-targeting knob; `regime_steady` demo). Move its bullet to `## Resolved` in `docs/open-topics/README.md` (let `mdformat` regenerate the TOC).

- [ ] **Step 3: Enhance `00004`** — add to `## Findings so far`: a parametric size-scaled slippage term is a scaffold extension separable from the data-gated aggTrades maker-fill; research §13 Stage 2 specified it for the baseline. (status stays `open`.)

- [ ] **Step 4: New `00007` + `00008`** — create per `.claude/rules/open-topics.md` shape (front-matter `status: open`; `## Context — what` / `## Why this matters` / `## Findings so far` / `## Suggested next steps`): `00007` multi-window training-stress harness (§13 Stage 3); `00008` pluggable feature handler (Alpha360 / custom crypto features per §5). Append both bullets to `## Open` in the index.

- [ ] **Step 5: Validation run + verdict.** With Redis up, run `regime_steady`, `steady`, and `skeleton` (full CPCV) into an isolated out-dir, then `zcrypto rank` over them; record the honest verdict (does the regime gate + walk-forward improve risk-adjusted holdout vs steady/skeleton — Sharpe, max-drawdown, PSR; DSR/PBO) in the PR description (and a one-line note in the `regime_steady` docstring, like `steady`). It is an honest result either way.

- [ ] **Step 6: `docs/iterations-history.md`** — append the iter-12 entry (one bullet per landed piece: the strategy seam, the regime overlay + modes, walk-forward, `regime_steady`, the deferred open-topics, the validation verdict).

- [ ] **Step 7: Commit**
```bash
git add README.md docs/open-topics docs/iterations-history.md cli/experiment/recipes/regime_steady.py
git commit -m "docs(experiment): iter-12 closeout — README, 00003 resolved, 00007/00008, iterations-history

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:** seam (Task 1) ✓; regime overlay all 3 modes + vol-target knob (Tasks 2–3) ✓; default binary-200 (`regime_steady`, Task 4) ✓; walk-forward quarterly/expanding + knobs (Tasks 6–7) ✓; benchmark preservation (Task 1 tests + Task 5) ✓; CPCV uses the same strategy (Task 1 cpcv wiring) ✓; deferred → open-topics + 00003 resolved (Task 8) ✓; validation (Task 8) ✓.
- **Type consistency:** `strategy_config` dict shape, `strategy_config_with_signal(cfg, signal)`, `regime_exposure_series(...)→Series`, `build_wf_periods(...)→list[tuple[tuple,tuple]]`, `run_walkforward_holdout(recipe,*,data_dir)→RunResult` — used consistently across tasks.
- **Risk flags:** Task 3 (qlib `get_risk_degree`/`trade_calendar` API) and Task 7 (walk-forward `RunResult` compatibility, positions/trades) carry RECON notes; the pure logic (Tasks 2, 6) is isolated and fully unit-tested so the integration surface is small.
