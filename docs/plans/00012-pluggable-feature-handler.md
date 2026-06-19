# Pluggable feature handler + richer-signal experiment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the feature handler recipe-pluggable, ship two new feature sets (qlib `Alpha360` + a custom cross-asset feature layer), and run a clean A/B of both against the benchmarks — recording the honest verdict on whether a richer signal carries edge.

**Architecture:** `Recipe.feature_config` (handler class dict, mirroring `model_config`/`strategy_config`) is built into the qlib handler config by a `scaffold.handler_config(...)` helper used in both `scaffold.py` and `cpcv.py`. The cross-asset features ride on Alpha158 as an explicit, self-contained `CrossAssetProcessor` (a qlib `Processor`) in a recipe's `infer_processors` — so the handler-class seam (Alpha360) and the additive cross-asset features (a processor) stay orthogonal, and the cross-asset math is an isolated pure function.

**Tech Stack:** Python 3.12, uv, qlib (`pyqlib`), LightGBM, pandas, pytest, ruff (line length 132). Redis required for `experiment` (`scripts/redis.sh start`).

## Global Constraints

- **Behavior-preserving for benchmarks:** `skeleton`/`steady`/`regime_steady` must build the **identical** Alpha158 handler config after migrating to `feature_config` — guarded by a regression test.
- **Leak-free:** all cross-asset features use trailing windows (`.shift`/`.rolling`); cross-sectional rank is contemporaneous (per-date across instruments) — no forward reference. The existing CPCV purge (`label_horizon_days`) + embargo stay sufficient; no new leakage surface.
- **OHLCV-only:** features derive solely from daily `$close`/`$volume`. No new data source.
- ruff clean (line length 132); each Claude-authored commit gets a subagent `Reviewed-by:` before push.
- Full `uv run pytest` is slow (redis-gated experiment tests); iterate with targeted `uv run pytest path::test`.

## File structure

```
cli/experiment/
├── recipes/base.py              # MODIFY: add Recipe.feature_config (default Alpha158)
├── recipes/skeleton.py          # MODIFY: feature_config={Alpha158} (behavior-preserving)
├── recipes/steady.py            # MODIFY: same
├── recipes/regime_steady.py     # MODIFY: same
├── recipes/alpha360_steady.py   # NEW: steady book + feature_config={Alpha360}
├── recipes/crossasset_steady.py # NEW: steady book + Alpha158 + CrossAssetProcessor
├── features/__init__.py         # NEW (package marker)
├── features/cross_asset.py      # NEW: cross_asset_features (pure) + CrossAssetProcessor (qlib Processor)
├── scaffold.py                  # MODIFY: handler_config(...) helper; _dataset_config builds from feature_config
└── cpcv.py                      # MODIFY: _materialize_span builds from feature_config via the helper
tests/
├── test_experiment_recipe.py    # EXTEND: feature_config contract + benchmark preservation + 2 new recipes
├── test_cross_asset.py          # NEW: pure cross_asset_features + CrossAssetProcessor (stubbed D.features)
├── test_experiment_scaffold.py  # EXTEND (redis-gated): handler built from feature_config; benchmarks preserved; 2 recipes run
└── test_experiment_cpcv.py      # EXTEND (redis-gated): _materialize_span builds from feature_config
```

Phase A = Task 1 (seam). Phase B = Tasks 2–3 (cross-asset). Phase C = Tasks 4–5 (recipes). Task 6 = integration. Task 7 = closeout.

---

## Task 1: `feature_config` seam — pluggable handler class; migrate benchmarks

**Files:** Modify `cli/experiment/recipes/base.py`, `scaffold.py`, `cpcv.py`, `recipes/skeleton.py`, `recipes/steady.py`, `recipes/regime_steady.py`; Test `tests/test_experiment_recipe.py`.

**Interfaces:**
- Produces: `Recipe.feature_config: dict` (default `{"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}`). `scaffold.handler_config(feature_config, *, instruments, start, end, fit_start, fit_end, handler_kwargs) -> dict`.

- [ ] **Step 1: Failing tests** in `tests/test_experiment_recipe.py`:
```python
def test_handler_config_builds_full_handler_dict():
    from cli.experiment.scaffold import handler_config
    out = handler_config(
        {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"},
        instruments=["BTCUSDT", "ETHUSDT"], start="2020-01-01", end="2025-12-31",
        fit_start="2020-01-01", fit_end="2023-12-31", handler_kwargs={"label": (["x"], ["L"])},
    )
    assert out["class"] == "Alpha158" and out["module_path"] == "qlib.contrib.data.handler"
    assert out["kwargs"]["instruments"] == ["BTCUSDT", "ETHUSDT"]
    assert out["kwargs"]["start_time"] == "2020-01-01" and out["kwargs"]["end_time"] == "2025-12-31"
    assert out["kwargs"]["fit_start_time"] == "2020-01-01" and out["kwargs"]["fit_end_time"] == "2023-12-31"
    assert out["kwargs"]["freq"] == "day" and out["kwargs"]["label"] == (["x"], ["L"])

def test_benchmarks_use_alpha158_feature_config():
    for name in ("skeleton", "steady", "regime_steady"):
        fc = resolve_recipe(name).feature_config
        assert fc == {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}
```

- [ ] **Step 2: Run — expect FAIL** (`feature_config`/`handler_config` absent): `uv run pytest tests/test_experiment_recipe.py -q`.

- [ ] **Step 3: Recipe field.** In `base.py` `Recipe`, add after `strategy_config`:
```python
    feature_config: dict = field(
        default_factory=lambda: {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}
    )
```
(Use `default_factory` — it's a mutable default; place it after the non-default fields or give it a default so dataclass ordering holds. It already follows the required positional fields, so a defaulted field is correct.)

- [ ] **Step 4: Helper + wiring.** In `scaffold.py` add:
```python
def handler_config(feature_config, *, instruments, start, end, fit_start, fit_end, handler_kwargs):
    """Build the full qlib handler config from a recipe's feature_config + runtime kwargs."""
    return {
        **feature_config,
        "kwargs": {
            **handler_kwargs,
            "instruments": list(instruments),
            "start_time": start, "end_time": end,
            "fit_start_time": fit_start, "fit_end_time": fit_end,
            "freq": "day",
        },
    }
```
In `scaffold._dataset_config`, replace the inline `handler_kwargs={...}` + `"handler": {"class": "Alpha158", ...}` with:
```python
    return {
        "class": "DatasetH", "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": handler_config(
                recipe.feature_config, instruments=recipe.universe,
                start=recipe.segments["train"][0], end=recipe.segments["test"][1],
                fit_start=recipe.segments["train"][0], fit_end=recipe.segments["train"][1],
                handler_kwargs=recipe.handler_kwargs,
            ),
            "segments": recipe.segments,
        },
    }
```
In `cpcv._materialize_span`, replace the inline handler dict with `handler_config(recipe.feature_config, instruments=recipe.universe, start=start, end=end, fit_start=start, fit_end=end, handler_kwargs=recipe.handler_kwargs)`. Import `handler_config` from `cli.experiment.scaffold` in `cpcv.py`.

- [ ] **Step 5: Migrate benchmarks.** Add `feature_config={"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}` to `skeleton.py`, `steady.py`, `regime_steady.py` RECIPE definitions (explicit, so the A/B variants read symmetrically). (The default already covers it, but explicit is clearer and the test checks the resolved value either way.)

- [ ] **Step 6: Run — expect PASS + ruff**: `uv run pytest tests/test_experiment_recipe.py -q`; `uv run ruff check cli/experiment tests && uv run ruff format --check cli/experiment tests`.

- [ ] **Step 7: Commit** — `feat(experiment): make the feature handler recipe-pluggable via feature_config` (+ `Co-Authored-By: Claude Opus 4.8` trailer).

---

## Task 2: Pure cross-asset feature logic — `cross_asset_features`

**Files:** Create `cli/experiment/features/__init__.py`, `cli/experiment/features/cross_asset.py`; Test `tests/test_cross_asset.py`.

**Interfaces:**
- Produces: `cross_asset_features(close: pd.DataFrame, *, btc="BTCUSDT", rs_windows=(5, 20), beta_windows=(20, 60), leadlag_lags=(1, 2, 3), coint_window=60, vol_window=20, mom_window=20) -> pd.DataFrame` — input `close` is a **wide** panel (index=date, columns=instrument) of raw close; returns a frame indexed by MultiIndex `(datetime, instrument)`, columns = cross-asset feature names (single level). BTC's own rows get neutral values.

- [ ] **Step 1: Failing tests** `tests/test_cross_asset.py` — build a synthetic wide close panel (e.g. BTC + 2 alts, ~120 days), assert:
  - the returned frame has the expected feature columns (relative-strength, beta, lead-lag, cointegration-z, cs-rank families) for each window;
  - **leak-safety:** a feature value at date `t` is unchanged when future rows (`> t`) are altered (recompute on a truncated-at-`t` panel yields the same value at `t`);
  - **BTC self-row:** BTC's relative-strength = 0 and beta-to-BTC = 1 (neutral) on warm dates;
  - values are finite after warmup (no inf); warmup rows may be NaN.
```python
import numpy as np, pandas as pd
from cli.experiment.features.cross_asset import cross_asset_features

def _panel():
    idx = pd.date_range("2020-01-01", periods=120, freq="D")
    rng = np.random.default_rng(0)
    btc = 100 + np.cumsum(rng.normal(0, 1, 120))
    return pd.DataFrame({"BTCUSDT": btc, "ETHUSDT": btc * 1.1 + rng.normal(0, 1, 120),
                         "XRPUSDT": 50 + np.cumsum(rng.normal(0, 0.5, 120))}, index=idx)

def test_btc_self_row_is_neutral():
    f = cross_asset_features(_panel(), btc="BTCUSDT")
    btc = f.xs("BTCUSDT", level="instrument")
    assert abs(btc["rs_20"].iloc[-1]) < 1e-9
    assert abs(btc["beta_20"].iloc[-1] - 1.0) < 1e-6

def test_leak_safe_trailing():
    p = _panel()
    full = cross_asset_features(p, btc="BTCUSDT")
    truncated = cross_asset_features(p.iloc[:100], btc="BTCUSDT")
    t = p.index[99]
    a = full.xs(t, level="datetime").sort_index()
    b = truncated.xs(t, level="datetime").sort_index()
    pd.testing.assert_frame_equal(a, b, check_like=True)
```

- [ ] **Step 2: Run — expect FAIL** (module absent).

- [ ] **Step 3: Implement** `features/__init__.py` (`"""Pluggable feature layers for the experiment pipeline."""`) and `cross_asset.py`'s pure function. Compute on the wide panel:
  - `rets = close.pct_change()`; `btc_ret = rets[btc]`.
  - **relative strength** `rs_<w>`: `(close/close.shift(w) - 1).sub(close[btc]/close[btc].shift(w) - 1, axis=0)`.
  - **beta** `beta_<w>`: `rets.rolling(w).cov(btc_ret).div(btc_ret.rolling(w).var(), axis=0)`.
  - **lead-lag** `leadlag_<lag>`: `rets.rolling(coint_window).corr(btc_ret.shift(lag))`.
  - **cointegration-z** `coint_z`: `spread = np.log(close).sub(np.log(close[btc]), axis=0)`; `(spread - spread.rolling(coint_window).mean()) / spread.rolling(coint_window).std()`.
  - **cross-sectional rank** `csrank_mom`, `csrank_vol`: per-date rank across instruments of `close/close.shift(mom_window)-1` and `rets.rolling(vol_window).std()` (`.rank(axis=1, pct=True)`).
  - Force BTC's own column neutral where applicable (`rs_*`=0, `beta_*`=1, `leadlag_*`=NaN→drop or neutral, `coint_z`=0).
  - Each family is a wide date×instrument frame; `.stack()` each to `(datetime, instrument)` and concat into one frame with the named columns. Ensure the row index names are `("datetime", "instrument")`.

- [ ] **Step 4: Run — expect PASS + ruff.**

- [ ] **Step 5: Commit** — `feat(experiment): add pure cross-asset feature logic (cross_asset_features)`.

---

## Task 3: `CrossAssetProcessor` — the qlib wrapper

**Files:** Modify `cli/experiment/features/cross_asset.py` (add the class); Test `tests/test_cross_asset.py`.

**Interfaces:**
- Consumes: `cross_asset_features` (Task 2); qlib `Processor`, `qlib.data.D`.
- Produces: `CrossAssetProcessor(Processor)` — referenced in a recipe's `infer_processors` as `{"class": "CrossAssetProcessor", "module_path": "cli.experiment.features.cross_asset", "kwargs": {...}}`.

**RECON (implementer):** confirm against `.venv/.../qlib/data/dataset/processor.py` and a real loaded handler frame: (1) `Processor.__call__(self, df)` is the hook and `fit` defaults to no-op; (2) the loaded `df` row index is a MultiIndex with levels named `datetime`/`instrument` (and which is outer) — adjust `get_level_values`/`unstack` accordingly; (3) `D.features(insts, ["$close"], start_time, end_time, freq="day")` returns a `(instrument, datetime)` frame — `["$close"].unstack(level="instrument")` gives the wide date×instrument panel; (4) assigning `df[("feature", name)] = series` adds a column under the existing `feature` MultiIndex column level. If reality differs, adapt and report.

- [ ] **Step 1: Failing test** — instantiate the processor and call it on a synthetic handler-shaped df, with `D.features` monkeypatched to return a synthetic close panel (no qlib init / no redis):
```python
def test_cross_asset_processor_appends_feature_columns(monkeypatch):
    from cli.experiment.features import cross_asset as ca
    # synthetic loaded df: MultiIndex (datetime, instrument) rows, MultiIndex (group, name) cols
    idx = pd.MultiIndex.from_product([pd.date_range("2020-01-01", periods=120, freq="D"),
                                      ["BTCUSDT", "ETHUSDT", "XRPUSDT"]], names=["datetime", "instrument"])
    df = pd.DataFrame({("feature", "KMID"): 0.0, ("label", "LABEL0"): 0.0}, index=idx)
    monkeypatch.setattr(ca, "_load_close", lambda insts, start, end: _wide_close_panel())  # see note
    out = ca.CrossAssetProcessor()(df)
    assert ("feature", "rs_20") in out.columns and ("feature", "beta_20") in out.columns
    assert ("label", "LABEL0") in out.columns  # label preserved
    assert len(out) == len(df)
```
Note: implement the `D.features` access behind a thin module-level `_load_close(insts, start, end) -> wide_close_df` so the test can monkeypatch it without touching qlib. The processor calls `_load_close`.

- [ ] **Step 2: Run — expect FAIL** (class absent).

- [ ] **Step 3: Implement.** In `cross_asset.py`:
```python
def _load_close(insts, start, end):
    from qlib.data import D
    s = D.features(list(insts), ["$close"], start_time=start, end_time=end, freq="day")["$close"]
    return s.unstack(level="instrument")  # RECON: confirm level name/order

class CrossAssetProcessor(Processor):  # from qlib.data.dataset.processor import Processor
    def __init__(self, btc="BTCUSDT", **kwargs):
        self.btc, self.kwargs = btc, kwargs
    def __call__(self, df):
        dt = df.index.get_level_values("datetime")
        insts = df.index.get_level_values("instrument").unique()
        close = _load_close(insts, dt.min(), dt.max())
        feats = cross_asset_features(close, btc=self.btc, **self.kwargs)
        feats = feats.reindex(df.index)
        for name in feats.columns:
            df[("feature", name)] = feats[name]
        return df
```
Place `CrossAssetProcessor` so it prepends cleanly before `RobustZScoreNorm` (the recipe wires order — Task 5).

- [ ] **Step 4: Run — expect PASS + ruff.**

- [ ] **Step 5: Commit** — `feat(experiment): add CrossAssetProcessor (qlib processor over cross_asset_features)`.

---

## Task 4: `alpha360_steady` recipe

**Files:** Create `cli/experiment/recipes/alpha360_steady.py`; Test `tests/test_experiment_recipe.py`.

**RECON (implementer):** confirm `Alpha360.__init__` (`.venv/.../qlib/contrib/data/handler.py`) accepts the same handler kwargs `steady` passes — especially the `label` override `(["Ref($close, -6)/Ref($close, -1) - 1"], ["LABEL0"])` and `infer_processors`/`learn_processors`. If Alpha360 does not accept `label` the same way Alpha158 does, document the difference and either keep steady's 5-day label via the supported mechanism or note the deviation in the recipe docstring.

- [ ] **Step 1: Failing test:**
```python
def test_alpha360_steady_uses_alpha360_and_steady_book():
    r = resolve_recipe("alpha360_steady")
    assert r.feature_config == {"class": "Alpha360", "module_path": "qlib.contrib.data.handler"}
    st = resolve_recipe("steady")
    assert r.universe == st.universe and r.segments == st.segments
    assert r.strategy_config == st.strategy_config and r.model_config == st.model_config
    assert r.label_horizon_days == st.label_horizon_days
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — copy steady's book/model/label/universe/segments/fees verbatim (self-contained recipe convention), set `feature_config={"class": "Alpha360", "module_path": "qlib.contrib.data.handler"}`. Docstring: the A/B thesis (steady book, Alpha360 vs Alpha158) framed as falsifiable; note the honest expectation (more dims, same OHLCV info).
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(experiment): add alpha360_steady recipe (steady book + Alpha360 features)`.

---

## Task 5: `crossasset_steady` recipe

**Files:** Create `cli/experiment/recipes/crossasset_steady.py`; Test `tests/test_experiment_recipe.py`.

- [ ] **Step 1: Failing test:**
```python
def test_crossasset_steady_prepends_cross_asset_processor():
    r = resolve_recipe("crossasset_steady")
    assert r.feature_config == {"class": "Alpha158", "module_path": "qlib.contrib.data.handler"}
    procs = r.handler_kwargs["infer_processors"]
    assert procs[0]["class"] == "CrossAssetProcessor"
    assert procs[0]["module_path"] == "cli.experiment.features.cross_asset"
    # steady's normalization still present, after the cross-asset step
    assert any(p["class"] == "RobustZScoreNorm" for p in procs)
    st = resolve_recipe("steady")
    assert r.universe == st.universe and r.model_config == st.model_config
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — copy steady's config, but set `handler_kwargs.infer_processors = [{"class": "CrossAssetProcessor", "module_path": "cli.experiment.features.cross_asset", "kwargs": {}}, {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}, {"class": "Fillna", "kwargs": {"fields_group": "feature"}}]` (CrossAssetProcessor FIRST so its appended features get normalized by RobustZScoreNorm). `feature_config={Alpha158}`. Docstring: the thesis (steady book + the cross-asset information Alpha158 lacks), falsifiable.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(experiment): add crossasset_steady recipe (steady book + cross-asset features)`.

---

## Task 6: Integration (redis-gated) — seam preserves benchmarks; new recipes run

**Files:** Test `tests/test_experiment_scaffold.py` (extend); optionally `tests/test_experiment_cpcv.py`.

**RECON:** mirror the existing redis-gated fixture + `_redis_up()`/skip pattern. The synthetic fixture must include `BTCUSDT` (the cross-asset anchor) — it does (benchmark). The fixture may be short; the cross-asset windows (≤60d) will warm up within the fixture span or Fillna-fill — assert the run completes + produces metrics, not specific feature values.

- [ ] **Step 1: Test(s)** (redis-gated): (a) `handler_config(resolve_recipe("skeleton").feature_config, ...)["class"] == "Alpha158"` + a `skeleton` smoke run completes (benchmark preserved through the seam); (b) `alpha360_steady` runs end-to-end and produces metrics; (c) `crossasset_steady` runs end-to-end, produces metrics, and the materialized feature matrix includes a cross-asset column (e.g. assert a `cpcv._materialize_span`-built infer_df has a `feature` column named `rs_20` / `beta_20`). Use `dataclasses.replace(..., segments=_FIXTURE_SEGMENTS)` per the existing tests; keep assertions minimal (wiring + completion).

- [ ] **Step 2: Run** (Redis up): `scripts/redis.sh start`; `uv run pytest tests/test_experiment_scaffold.py -q`.
- [ ] **Step 3: Commit** — `test(experiment): redis-gated integration — feature seam + Alpha360/cross-asset recipes run`.

---

## Task 7: Closeout — validation, docs, open-topics, iterations-history

**Files:** Modify `README.md`; `docs/open-topics/T0008-pluggable-feature-handler.md` + `docs/open-topics/README.md`; create a new `docs/open-topics/T0010-<slug>.md`; modify `docs/iterations-history.md`; the two new recipe docstrings.

- [ ] **Step 1: Validation run + verdict.** Redis up; run `skeleton`, `steady`, `alpha360_steady`, `crossasset_steady` (full CPCV) into an isolated out-dir, then `zcrypto rank`. Record the honest verdict (does either richer feature set clear a meaningful net OOS Sharpe / PSR bar vs the benchmarks, or does the CPCV→holdout inversion persist?) — a one-line measured note in each new recipe's docstring (like `steady`), and in the iterations-history entry. Honest either way.

- [ ] **Step 2: README `## Usage`** — document `feature_config` (the recipe field) and the `alpha360_steady` + `crossasset_steady` recipes. (`mdformat` owns the README TOC — don't hand-edit it.)

- [ ] **Step 3: Open-topic `T0008`** — flip front-matter `status: open → partial` (seam + two handlers shipped; outcome documented). Add a `## Done so far` section (seam, Alpha360, cross-asset processor, the verdict); trim `## Suggested next steps` to the remainder (e.g. richer/learned features, other handler classes). Move its bullet from `## Open` to `## Partially done` in `docs/open-topics/README.md`. (If the verdict shows the seam fully answered the topic, `resolved` is acceptable — choose per outcome.)

- [ ] **Step 4: New open-topic `T0010`** — non-OHLCV features (funding-rate / on-chain / order-book) needing a new data source. Per `.claude/rules/open-topics.md` shape (`status: open`, `priority: medium`; Context/Why/Findings/Next-steps). Append its bullet to `## Open`. (Next free open-topic serial is `T0010` — T0000–T0009 exist.)

- [ ] **Step 5: `docs/iterations-history.md`** — append the iter-13 entry: the `feature_config` seam, `Alpha360` + the cross-asset feature layer (`cross_asset_features` + `CrossAssetProcessor`), the two recipes, the deferred `T0010`, and the validation verdict.

- [ ] **Step 6: Commit** — `docs(experiment): iter-13 closeout — README, T0008 partial, T0010, iterations-history`.

---

## Self-review

- **Spec coverage:** seam (Task 1) ✓; Alpha360 (Task 4) ✓; custom cross-asset via post-load processor (Tasks 2–3, Approach A) ✓; cross-asset feature families per Decision 6 (Task 2) ✓; A/B on steady's book (Tasks 4–5) ✓; benchmark preservation (Task 1 + Task 6) ✓; both scaffold + cpcv build from feature_config (Task 1) ✓; OHLCV-only + new open-topic for non-OHLCV (Task 7) ✓; validation + verdict (Task 7) ✓.
- **Refinement of spec:** the spec's "custom handler subclass" is realized as Alpha158 + an explicit `CrossAssetProcessor` in the recipe's `infer_processors` (simpler, recipe-transparent, same post-load-processor effect). Flagged.
- **Type consistency:** `feature_config` dict; `handler_config(feature_config, *, instruments, start, end, fit_start, fit_end, handler_kwargs)`; `cross_asset_features(close, *, ...) -> (datetime, instrument)×features`; `CrossAssetProcessor(Processor).__call__(df) -> df` — used consistently across tasks.
- **Risk flags:** Task 3 (qlib processor/df-index/D.features specifics) and Task 4 (Alpha360 accepting steady's `label`/processors) carry RECON notes; the pure cross-asset math (Task 2) is isolated and fully unit-tested so the integration surface is small.
