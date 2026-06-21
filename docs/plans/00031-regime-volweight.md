# Vol-weighted (risk-parity-lite) Gated Basket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inverse-vol (risk-parity-lite) weighting strategy gated by the BTC-trend regime, plus a `regime_volweight_majors` recipe, so the iter-32 closeout can A/B inverse-vol vs equal weighting of the 10-major gated basket.

**Architecture:** A pure `inverse_vol_weights(vols)` + a `VolWeightedRegimeStrategy(WeightStrategyBase)` (in `regime.py`). `WeightStrategyBase`'s order generator scales target weights by `get_risk_degree`, so the regime gate composes natively (no iter-23 workaround). The per-name vol panel is **trailing** and looked up **strictly before** each trade date (no look-ahead).

**Tech Stack:** Python 3.12, uv, qlib (`WeightStrategyBase`), numpy, pandas, scikit-learn, pytest, ruff.

## Global Constraints

- **NO LOOK-AHEAD (cardinal):** the per-name vol used to weight trade date *t* must come from closes **strictly before t**. `generate_target_weight_position` looks up the most recent vol-panel row with index `< trade_start_time`. The review and a unit test must verify this.
- `WeightStrategyBase` is the base (its order generator honors `get_risk_degree`). The gate exposure reuses `regime_exposure_series` (existing) + a `get_risk_degree` override returning `_base_risk_degree * regime_mult` (mirroring `RegimeGatedTopkStrategy`).
- `inverse_vol_weights` is a pure function (no qlib) — unit-tested in isolation.
- ruff: line length 132, double quotes, import sorting. `uv run ruff check --fix` + `uv run ruff format` before commit.
- Commit: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `inverse_vol_weights` + `VolWeightedRegimeStrategy`

**Files:**
- Modify: `cli/experiment/strategies/regime.py`
- Test: `tests/test_regime_strategy.py` (extend)

**Interfaces:**
- Produces: `inverse_vol_weights(vols: pd.Series) -> pd.Series`; `VolWeightedRegimeStrategy(WeightStrategyBase)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regime_strategy.py`:

```python
def test_inverse_vol_weights_basics():
    import numpy as np
    import pandas as pd

    from cli.experiment.strategies.regime import inverse_vol_weights

    w = inverse_vol_weights(pd.Series({"A": 0.1, "B": 0.2, "C": 0.4}))
    assert abs(w.sum() - 1.0) < 1e-9
    assert w["A"] > w["B"] > w["C"]  # lower vol -> higher weight
    # non-finite / non-positive vols are dropped then renormalized
    w2 = inverse_vol_weights(pd.Series({"A": 0.1, "B": float("nan"), "C": 0.0, "D": 0.1}))
    assert abs(w2.sum() - 1.0) < 1e-9
    assert w2["B"] == 0.0 and w2["C"] == 0.0
    assert abs(w2["A"] - 0.5) < 1e-9 and abs(w2["D"] - 0.5) < 1e-9
    # all-bad -> equal-weight fallback
    w3 = inverse_vol_weights(pd.Series({"A": float("nan"), "B": 0.0}))
    assert abs(w3.sum() - 1.0) < 1e-9 and abs(w3["A"] - 0.5) < 1e-9


def test_volweight_strategy_no_lookahead(monkeypatch):
    """Cardinal: the weights for date t use the vol row STRICTLY BEFORE t, never t's own row."""
    import numpy as np
    import pandas as pd

    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    dates = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    # prior row (2025-01-02): A low vol, B high vol -> A should get the higher weight.
    # t's own row (2025-01-03): inverted (A high, B low) -> if used, weights would invert (look-ahead).
    s._vol_panel = pd.DataFrame(
        {"A": [0.5, 0.1, 0.9], "B": [0.5, 0.9, 0.1]}, index=dates
    )
    score = pd.Series({"A": 0.0, "B": 0.0})
    w = s.generate_target_weight_position(score, current=None, trade_start_time=dates[2], trade_end_time=dates[2])
    # used the 2025-01-02 row (A=0.1 < B=0.9) -> A heavier. If it look-ahead-used 2025-01-03, A<B.
    assert w["A"] > w["B"], "look-ahead: weights must use the strictly-prior vol row"


def test_volweight_get_risk_degree_applies_regime(monkeypatch):
    import pandas as pd

    from cli.experiment.strategies import regime as rg

    s = object.__new__(rg.VolWeightedRegimeStrategy)
    s._base_risk_degree = 0.95
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    s._exposure = pd.Series([1.0, 0.0], index=idx)  # risk-on then risk-off

    class _Cal:
        def __init__(self, d):
            self._d = d

        def get_trade_step(self):
            return 0

        def get_step_time(self, step, shift=0):
            return (self._d, self._d)

    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[1])), raising=False)
    assert s.get_risk_degree(0) == 0.0  # risk-off -> cash
    monkeypatch.setattr(rg.VolWeightedRegimeStrategy, "trade_calendar", property(lambda self: _Cal(idx[0])), raising=False)
    assert s.get_risk_degree(0) == 0.95
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_regime_strategy.py -k "inverse_vol or volweight" -v`
Expected: FAIL — `inverse_vol_weights` / `VolWeightedRegimeStrategy` not defined.

- [ ] **Step 3: Implement in `cli/experiment/strategies/regime.py`**

Change the qlib import at the top:
```python
from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy
```
to:
```python
from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy, WeightStrategyBase
```

Append at the end of the file:

```python
def inverse_vol_weights(vols: pd.Series) -> pd.Series:
    """Risk-parity-lite weights: proportional to 1/vol over finite, strictly-positive vols,
    normalized to sum to 1. Non-finite or <=0 vols get weight 0 (then the rest renormalize);
    if none are usable, fall back to equal weights over the input index.
    """
    vols = vols.astype("float64")
    inv = 1.0 / vols
    good = np.isfinite(inv) & (vols > 0)
    if not good.any():
        n = len(vols)
        return pd.Series(1.0 / n, index=vols.index) if n else pd.Series(dtype="float64")
    inv = inv.where(good, 0.0)
    return inv / inv.sum()


class VolWeightedRegimeStrategy(WeightStrategyBase):
    """Inverse-vol (risk-parity-lite) weights over the universe, gated by the BTC-trend regime.

    Cross-sectional weights come from trailing per-name realized vol, looked up STRICTLY BEFORE
    each trade date (no look-ahead). Total exposure is scaled by the regime multiplier via
    ``get_risk_degree``, which ``WeightStrategyBase``'s order generator honors natively.
    """

    def __init__(
        self,
        *,
        weight_universe,
        weight_vol_lookback=30,
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
        super().__init__(**kwargs)
        self._base_risk_degree = self.risk_degree
        self.weight_universe = list(weight_universe)
        self.weight_vol_lookback = weight_vol_lookback
        self.regime_mode = regime_mode
        self.regime_benchmark = regime_benchmark
        self.regime_ma_window = regime_ma_window
        self.regime_ma_fast = regime_ma_fast
        self.regime_band = regime_band
        self.chop_exposure = chop_exposure
        self.vol_target = vol_target
        self.vol_lookback = vol_lookback
        self._exposure = self._build_exposure()
        self._vol_panel = self._build_vol_panel()

    def _build_exposure(self) -> pd.Series:
        from qlib.data import D

        close = D.features([self.regime_benchmark], ["$close"], freq="day")["$close"].droplevel(0)
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

    def _build_vol_panel(self) -> pd.DataFrame:
        from qlib.data import D

        close = D.features(self.weight_universe, ["$close"], freq="day")["$close"]
        wide = close.unstack(level="instrument").sort_index()
        # Trailing realized vol per name (rolling std of daily returns). Each row d uses closes <= d.
        return wide.pct_change().rolling(self.weight_vol_lookback).std()

    def _mult_for(self, date) -> float:
        date = pd.Timestamp(date).normalize()
        exp = self._exposure
        if date in exp.index:
            return float(exp.loc[date])
        prior = exp.loc[:date]
        return float(prior.iloc[-1]) if len(prior) else 1.0

    def get_risk_degree(self, trade_step=None):
        step = trade_step if trade_step is not None else self.trade_calendar.get_trade_step()
        _, date = self.trade_calendar.get_step_time(step)
        return self._base_risk_degree * self._mult_for(date)

    def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
        names = list(score.index)
        t = pd.Timestamp(trade_start_time).normalize()
        vp = self._vol_panel
        prior = vp.loc[vp.index < t]  # NO LOOK-AHEAD: strictly-prior vol row only
        vols = prior.iloc[-1].reindex(names) if len(prior) else pd.Series(index=names, dtype="float64")
        w = inverse_vol_weights(vols)
        return {k: float(v) for k, v in w.items() if v > 0}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_regime_strategy.py -k "inverse_vol or volweight" -v`
Expected: PASS (3 tests). Also run the full file: `uv run pytest tests/test_regime_strategy.py -q` (existing regime tests must still pass).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/strategies/regime.py tests/test_regime_strategy.py
uv run ruff format cli/experiment/strategies/regime.py tests/test_regime_strategy.py
uv run pytest tests/test_regime_strategy.py -q
git add cli/experiment/strategies/regime.py tests/test_regime_strategy.py
git commit -m "feat(experiment): add inverse-vol risk-parity-lite regime weight strategy"
```

---

### Task 2: `regime_volweight_majors` recipe

**Files:**
- Create: `cli/experiment/recipes/regime_volweight_majors.py`
- Modify: `README.md`
- Test: `tests/test_experiment_recipe.py` (extend)

**Interfaces:**
- Consumes: `Recipe`; `VolWeightedRegimeStrategy` (Task 1); DummyRegressor via the iter-27 seam; `resolve_recipe`.
- Produces: recipe `regime_volweight_majors`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_recipe.py`:

```python
def test_regime_volweight_majors_is_volweighted_gated_10major():
    rv, st = resolve_recipe("regime_volweight_majors"), resolve_recipe("steady")
    majors = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT")
    sc = rv.strategy_config
    assert sc["class"] == "VolWeightedRegimeStrategy"
    assert sc["module_path"] == "cli.experiment.strategies.regime"
    assert tuple(sc["kwargs"]["weight_universe"]) == majors
    assert sc["kwargs"]["regime_mode"] == "binary"
    assert sc["kwargs"]["regime_ma_window"] == 200
    assert sc["kwargs"]["vol_target"] == 0.50
    assert sc["kwargs"]["regime_benchmark"] == "BTCUSDT"
    assert rv.model_config["class"] == "DummyRegressor"
    assert rv.universe == majors
    # steady's data book preserved
    assert rv.handler_kwargs == st.handler_kwargs
    assert rv.feature_config == st.feature_config
    assert rv.segments == st.segments
    assert rv.fee_preset == st.fee_preset and rv.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_volweight_majors -v`
Expected: FAIL — recipe not found.

- [ ] **Step 3: Create `cli/experiment/recipes/regime_volweight_majors.py`**

```python
"""regime_volweight_majors recipe — inverse-vol (risk-parity-lite) gated basket of the 10 majors.

iter-32 A/B vs the iter-30 best (regime_equalweight_majors, gated EQUAL-weight). Same 10-major
universe, same DummyRegressor (no selection), same gate (binary 200d + vol_target 0.50); the only
change is the weighting — VolWeightedRegimeStrategy weights held names by inverse trailing vol
(down-weighting the more volatile), motivated by iter-30/31 (volatile names drag the basket).
"""

from cli.experiment.recipes.base import Recipe

_MAJORS = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOGEUSDT",
    "TRXUSDT",
)

RECIPE = Recipe(
    name="regime_volweight_majors",
    handler_kwargs={
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        "label": (["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"]),
    },
    model_config={
        "class": "DummyRegressor",
        "module_path": "sklearn.dummy",
        "kwargs": {"strategy": "mean"},
    },
    strategy_config={
        "class": "VolWeightedRegimeStrategy",
        "module_path": "cli.experiment.strategies.regime",
        "kwargs": {
            "weight_universe": _MAJORS,
            "weight_vol_lookback": 30,
            "regime_mode": "binary",
            "regime_benchmark": "BTCUSDT",
            "regime_ma_window": 200,
            "vol_target": 0.50,
        },
    },
    feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
    segments={
        "train": ("2020-01-01", "2023-12-31"),
        "valid": ("2024-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2026-06-15"),
    },
    universe=_MAJORS,
    reference_instruments=("BTCEUR", "ETHBTC"),
    account=10_000.0,
    benchmark="BTCUSDT",
    fee_preset="vip2_bnb",
    label_horizon_days=6,
    feature_lookback_days=60,
    cv_n_groups=6,
    cv_test_groups=2,
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_experiment_recipe.py -k regime_volweight_majors -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

Add a row: `regime_volweight_majors` — inverse-vol (risk-parity-lite) gated basket of the 10 majors (iter-32 A/B vs equal-weight). Match the existing format; don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + recipe-test run + commit**

```bash
uv run ruff check --fix cli/experiment/recipes/regime_volweight_majors.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/recipes/regime_volweight_majors.py tests/test_experiment_recipe.py
uv run pytest tests/test_experiment_recipe.py -q
git add cli/experiment/recipes/regime_volweight_majors.py tests/test_experiment_recipe.py README.md
git commit -m "feat(experiment): add regime_volweight_majors (inverse-vol gated basket)"
```

---

## Closeout (operational — run by the orchestrator after Tasks 1-2 land, NOT a subagent task)

1. **Run the new arm** (redis up): `uv run zcrypto stress --recipe regime_volweight_majors --seeds 8`.
2. **Sanity FIRST:** confirm the per-window Sharpe is NOT bit-identical to `regime_equalweight_majors` (else a silent weighting bug — STOP + fix, cf. iter-23).
3. **A/B** vs `regime_equalweight_majors`: per-window long-only Sharpe + mean / worst.
4. **Verdict** → `docs/iterations-history.md`: does inverse-vol weighting beat equal-weight (esp. a better bear tail)? Record the running best.
5. **Update `T0018`**; **README** (Task 2).
6. **iter-32 iterations-history entry.**

---

## Self-Review

**Spec coverage:** Decision 1 (`inverse_vol_weights`) → Task 1; Decision 2 (`VolWeightedRegimeStrategy`, gate via get_risk_degree, no look-ahead) → Task 1; Decision 3 (`regime_volweight_majors`) → Task 2; Decision 4 (validation) → Task 1 tests (no-look-ahead unit test) + Closeout 2 (differs-from-equal-weight). README → Task 2 Step 5; verdict + T0018 + history → Closeout.

**Placeholder scan:** No TBD/TODO. Full code for the pure fn, the strategy, and the recipe. Verdict values are closeout.

**Type consistency:** `inverse_vol_weights(vols: pd.Series) -> pd.Series` used by the strategy + tested directly. `VolWeightedRegimeStrategy(WeightStrategyBase)` implements `generate_target_weight_position` (the abstract method) + overrides `get_risk_degree` (the gate). The recipe's `strategy_config` kwargs match `__init__` (`weight_universe`, `weight_vol_lookback`, `regime_mode`, `regime_ma_window`, `vol_target`, `regime_benchmark`). The no-look-ahead unit test stubs `_vol_panel` so the strict-prior lookup is verified without qlib. The recipe `universe` and `strategy_config.kwargs.weight_universe` are the same 10 majors (via `_MAJORS`).
