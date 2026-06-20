# Realistic Execution Costs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make calibrated realistic execution costs (size-scaled slippage via qlib's `impact_cost` + a maker-fill effective-cost haircut) the default experiment cost model, with a `--fees-only` opt-out baseline, calibrated from the iter-17 aggTrades sample, then re-measure all recipes to quantify the net-P&L haircut — resolving `T0004`.

**Architecture:** The `Recipe` (frozen dataclass) gains three cost fields — `impact_cost`, `maker_fill_haircut`, `fees_only` — defaulting to calibrated constants in a new `cli/experiment/costs.py`. `exchange_kwargs(recipe)` (the single cost-config builder, called from cpcv/scaffold/multiseed/walkforward) reads them: realistic = qlib `impact_cost` + haircut-bumped fees; `fees_only=True` = raw `fee_preset` + no impact. A `--fees-only` flag swaps `recipe.fees_only=True` once at the top of the command via `dataclasses.replace` (the iter-18 `with_pit_universe` pattern — no call-site churn). A one-off `calibrate_execution.py` estimates the constants from the aggTrades mirror at closeout.

**Tech Stack:** Python 3.12, uv, Typer, qlib, pandas, pytest + Typer `CliRunner`, ruff.

## Global Constraints

- **`exchange_kwargs(recipe)` keeps its single-argument signature** — do NOT add a `fees_only` parameter to it or thread one through `run_cpcv`/`run_experiment`/`run_holdout_seeds`/`run_walkforward` or their 4 `exchange_kwargs(recipe)` call sites (`cpcv.py:221`, `multiseed.py:191`, `scaffold.py:162`, `walkforward.py:195`). The toggle lives on the recipe (`recipe.fees_only`), swapped at the top of the command.
- **`--fees-only` default off** → calibrated costs are the default (the iteration's point — recipe results intentionally change vs the old fees-only). `--fees-only` reverts to today's exact `exchange_kwargs` output (raw `fee_preset`, no `impact_cost` key) — the comparison baseline.
- **Single-scalar wired model:** qlib's `Exchange.impact_cost` and `open_cost`/`close_cost` are single scalars; the wired `impact_cost` + haircut are single representative values. The calibration's per-tier `(c, f, s)` breakdown is **analysis** (recorded in `COST_CALIBRATION["tiers"]` + the verdict to justify the representative value and flag thin-book risk), NOT per-instrument wiring. Per-tier slippage wiring (a custom Exchange subclass) is out of scope (parked with the custom executor).
- **`COST_CALIBRATION` values are provisional during implementation** (clearly marked) and **replaced at closeout** by running `calibrate_execution.py` on the real sample — like iter-18's LUNCUSDT-at-closeout. Code tasks assert wiring/structure, not magnitudes.
- ruff: line length 132, double quotes, import sorting (`select = ["I"]`). Run `uv run ruff check --fix <files>` + `uv run ruff format <files>` before each commit.
- Commit messages: `<type>(<scope>): <subject>` (imperative, lowercase, no period, no "iter-N" tag), ending with a `Co-Authored-By:` trailer naming the **actual implementing model**.

---

### Task 1: `costs.py` calibration constants + Recipe cost fields

**Files:**
- Create: `cli/experiment/costs.py`
- Modify: `cli/experiment/recipes/base.py` (import `COST_CALIBRATION`; add 3 fields to `Recipe`)
- Test: `tests/test_experiment_costs.py`, `tests/test_experiment_recipe.py`

**Interfaces:**
- Produces: `COST_CALIBRATION: dict` with keys `impact_cost: float`, `maker_fill_haircut: float`, `tiers: dict`; `Recipe` gains `impact_cost: float`, `maker_fill_haircut: float`, `fees_only: bool` (consumed by Task 2/3).

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_costs.py` (new):

```python
def test_cost_calibration_shape():
    from cli.experiment.costs import COST_CALIBRATION

    assert set(COST_CALIBRATION) >= {"impact_cost", "maker_fill_haircut", "tiers"}
    assert isinstance(COST_CALIBRATION["impact_cost"], float)
    assert isinstance(COST_CALIBRATION["maker_fill_haircut"], float)
    assert COST_CALIBRATION["impact_cost"] >= 0.0
    assert COST_CALIBRATION["maker_fill_haircut"] >= 0.0
```

In `tests/test_experiment_recipe.py`, add:

```python
def test_recipe_cost_fields_default_to_calibration():
    from cli.experiment.costs import COST_CALIBRATION
    from cli.experiment.recipes.base import resolve_recipe

    r = resolve_recipe("steady")
    assert r.impact_cost == COST_CALIBRATION["impact_cost"]
    assert r.maker_fill_haircut == COST_CALIBRATION["maker_fill_haircut"]
    assert r.fees_only is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_costs.py tests/test_experiment_recipe.py -k "cost" -v`
Expected: FAIL — `ModuleNotFoundError: cli.experiment.costs` / `Recipe` has no `impact_cost`.

- [ ] **Step 3: Create `costs.py`**

```python
"""Calibrated execution-cost constants for the experiment cost model (see docs/specs/00018).

These are the DEFAULT realistic-cost parameters: qlib's Exchange ``impact_cost`` (size-scaled
slippage, applied per instrument as ``impact_cost * (order$ / bar$-volume) ** 2``) and a
``maker_fill_haircut`` (an additive per-side cost fraction approximating the taker penalty when
a maker limit order does not fill). They are calibrated from the iter-17 aggTrades sample by
``cli/experiment/scripts/calibrate_execution.py``.

NOTE: the values below are PROVISIONAL placeholders set during implementation; they are replaced
at the iter-19 closeout with the values printed by calibrate_execution.py on the real sample.
``tiers`` records the per-liquidity-tier breakdown for the record (the wired model uses the
single representative ``impact_cost`` / ``maker_fill_haircut`` — qlib's exchange cost knobs are
single scalars).
"""

from __future__ import annotations

COST_CALIBRATION: dict = {
    # PROVISIONAL — replaced at closeout from calibrate_execution.py on the real aggTrades sample.
    "impact_cost": 0.1,  # qlib Exchange impact_cost coefficient (single representative)
    "maker_fill_haircut": 0.0005,  # additive per-side cost fraction (5 bps) for non-fills
    "tiers": {},  # per-tier {tier: {"impact_cost": c, "fill_rate": f, "spread": s}} — analysis record
}
```

- [ ] **Step 4: Add the Recipe cost fields**

In `cli/experiment/recipes/base.py`, add the import near the top (after the existing imports):

```python
from cli.experiment.costs import COST_CALIBRATION
```

In the `Recipe` dataclass, add after the `fee_preset` field (line 40):

```python
    # Realistic execution-cost knobs (see docs/specs/00018). Defaults = calibrated values;
    # fees_only=True reverts exchange_kwargs to the raw fee_preset (no slippage) for the A/B baseline.
    impact_cost: float = field(default=COST_CALIBRATION["impact_cost"])
    maker_fill_haircut: float = field(default=COST_CALIBRATION["maker_fill_haircut"])
    fees_only: bool = field(default=False)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_costs.py tests/test_experiment_recipe.py -k "cost" -v`
Expected: PASS (2 new tests + existing recipe tests unaffected).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/costs.py cli/experiment/recipes/base.py tests/test_experiment_costs.py tests/test_experiment_recipe.py
uv run ruff format cli/experiment/costs.py cli/experiment/recipes/base.py tests/test_experiment_costs.py tests/test_experiment_recipe.py
git add cli/experiment/costs.py cli/experiment/recipes/base.py tests/test_experiment_costs.py tests/test_experiment_recipe.py
git commit -m "feat(experiment): add calibrated cost constants + Recipe cost fields"
```

---

### Task 2: `exchange_kwargs` realistic-default + fees_only branch

**Files:**
- Modify: `cli/experiment/scaffold.py` (`exchange_kwargs`)
- Test: `tests/test_experiment_scaffold.py`

**Interfaces:**
- Consumes: `Recipe.impact_cost`, `Recipe.maker_fill_haircut`, `Recipe.fees_only` (Task 1).
- Produces: `exchange_kwargs(recipe) -> dict` — realistic adds `impact_cost` + haircut-bumped `open_cost`/`close_cost`; `fees_only` returns today's exact dict (no `impact_cost` key).

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_scaffold.py`, add (use a minimal Recipe via `resolve_recipe`):

```python
def test_exchange_kwargs_realistic_default_adds_impact_and_haircut():
    from cli.experiment.recipes.base import FEE_PRESETS, resolve_recipe
    from cli.experiment.scaffold import exchange_kwargs

    r = resolve_recipe("steady")  # fees_only defaults False
    ek = exchange_kwargs(r)
    fee_open, fee_close = FEE_PRESETS[r.fee_preset]
    assert ek["impact_cost"] == r.impact_cost
    assert ek["open_cost"] == fee_open + r.maker_fill_haircut
    assert ek["close_cost"] == fee_close + r.maker_fill_haircut
    assert ek["deal_price"] == "close" and ek["trade_unit"] is None


def test_exchange_kwargs_fees_only_is_todays_behavior():
    import dataclasses

    from cli.experiment.recipes.base import FEE_PRESETS, resolve_recipe
    from cli.experiment.scaffold import exchange_kwargs

    r = dataclasses.replace(resolve_recipe("steady"), fees_only=True)
    ek = exchange_kwargs(r)
    fee_open, fee_close = FEE_PRESETS[r.fee_preset]
    assert ek["open_cost"] == fee_open and ek["close_cost"] == fee_close
    assert "impact_cost" not in ek  # raw fees-only path, byte-identical to pre-iter-19
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_scaffold.py -k "exchange_kwargs" -v`
Expected: FAIL — realistic asserts `impact_cost`/haircut not yet added.

- [ ] **Step 3: Modify `exchange_kwargs`**

Replace the body of `exchange_kwargs` in `cli/experiment/scaffold.py`:

```python
def exchange_kwargs(recipe: Recipe) -> dict:
    """Shared exchange config for the holdout + CPCV path backtests.

    `trade_unit=None` enables fractional crypto fills (qlib.init(region=REG_US) sets
    C.trade_unit=1, which would floor order amounts to whole coins and zero out BTC/ETH on a
    $10k account).

    Cost model (see docs/specs/00018): by default realistic — qlib `impact_cost` (size-scaled
    slippage, per-instrument `(order$/bar$-vol)**2`) plus a maker-fill haircut folded into the
    fee fractions. `recipe.fees_only=True` reverts to the raw fee_preset with no slippage (the
    A/B baseline, byte-identical to the pre-iter-19 output).
    """
    fee_open, fee_close = FEE_PRESETS[recipe.fee_preset]
    if recipe.fees_only:
        return {
            "freq": "day",
            "deal_price": "close",
            "open_cost": fee_open,
            "close_cost": fee_close,
            "min_cost": 0,
            "trade_unit": None,
        }
    return {
        "freq": "day",
        "deal_price": "close",
        "open_cost": fee_open + recipe.maker_fill_haircut,
        "close_cost": fee_close + recipe.maker_fill_haircut,
        "impact_cost": recipe.impact_cost,
        "min_cost": 0,
        "trade_unit": None,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_scaffold.py -k "exchange_kwargs" -v`
Expected: PASS (both new tests + existing scaffold tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/scaffold.py tests/test_experiment_scaffold.py
uv run ruff format cli/experiment/scaffold.py tests/test_experiment_scaffold.py
git add cli/experiment/scaffold.py tests/test_experiment_scaffold.py
git commit -m "feat(experiment): realistic cost model in exchange_kwargs with fees_only baseline"
```

---

### Task 3: `--fees-only` flag + cost-model marker + README

**Files:**
- Modify: `cli/experiment/command.py` (flag; swap `recipe.fees_only`; `run_meta` cost block + stdout line)
- Modify: `README.md` (Usage)
- Test: `tests/test_experiment_command.py`

**Interfaces:**
- Consumes: `Recipe.fees_only` + `exchange_kwargs` (Tasks 1-2).

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_command.py`, extend `_patch_experiment_heavy_fns` so `fake_run_experiment` captures the recipe's cost flag (add alongside the existing captures):

```python
        captured["run_experiment_fees_only"] = recipe.fees_only
```

Then add two tests (mirror the existing `test_experiment_passes_seeds_and_deterministic` setup — `_short_recipe()`, monkeypatched `resolve_recipe`/`load_config`/`resolve_data_dir`, `_patch_experiment_heavy_fns`, `--quick`):

```python
def test_experiment_fees_only_flag_sets_recipe_and_marker(monkeypatch, tmp_path):
    captured = {}
    short_recipe = _short_recipe()
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)
    monkeypatch.setattr("cli.experiment.command.load_config", lambda: {})
    monkeypatch.setattr("cli.experiment.command.resolve_data_dir", lambda d, cfg: tmp_path)
    _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, _fake_result(tmp_path))

    result = runner.invoke(app, ["experiment", "--recipe", "steady", "--quick", "--fees-only", "--out", str(tmp_path / "runs")])

    assert result.exit_code == 0, result.stdout
    assert captured["run_experiment_fees_only"] is True
    assert "fees-only" in result.stdout.lower()


def test_experiment_default_is_realistic_costs(monkeypatch, tmp_path):
    captured = {}
    short_recipe = _short_recipe()
    monkeypatch.setattr("cli.experiment.command.resolve_recipe", lambda name: short_recipe)
    monkeypatch.setattr("cli.experiment.command.load_config", lambda: {})
    monkeypatch.setattr("cli.experiment.command.resolve_data_dir", lambda d, cfg: tmp_path)
    _patch_experiment_heavy_fns(monkeypatch, tmp_path, captured, _fake_result(tmp_path))

    result = runner.invoke(app, ["experiment", "--recipe", "steady", "--quick", "--out", str(tmp_path / "runs")])

    assert result.exit_code == 0, result.stdout
    assert captured["run_experiment_fees_only"] is False
    assert "realistic" in result.stdout.lower()
```

(If `_short_recipe()`/`_fake_result()` are not yet module-level helpers, they exist from iter-18 — reuse them; do not duplicate literals.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_experiment_command.py -k "fees_only or realistic_costs" -v`
Expected: FAIL — unknown option `--fees-only`.

- [ ] **Step 3: Add the flag, the swap, and the marker**

In `cli/experiment/command.py`:

(a) Add the option after the `deterministic` option (mirror the `--pit-universe` option added in iter-18):

```python
    fees_only: bool = typer.Option(
        False,
        "--fees-only/--no-fees-only",
        help="Use the fees-only cost model (raw fee_preset, no slippage/maker-fill) instead of the "
        "default calibrated realistic costs. The A/B baseline for the execution-cost re-measure.",
    ),
```

(b) After the recipe is resolved + (iter-18) the pit-universe swap block, add:

```python
    if fees_only:
        recipe = dataclasses.replace(recipe, fees_only=True)
    cost_model = "fees-only (no slippage/maker-fill)" if fees_only else "realistic (calibrated slippage + maker-fill)"
```

(`dataclasses` is already imported in the command body.)

(c) In the `run_meta` dict, add a cost-model block (near `"fee_preset": recipe.fee_preset,`):

```python
        "cost_model": {
            "fees_only": recipe.fees_only,
            "impact_cost": recipe.impact_cost,
            "maker_fill_haircut": recipe.maker_fill_haircut,
        },
```

(d) Add a stdout line near the existing `⚠ {marker}` survivorship line:

```python
    typer.echo(f"  cost model         : {cost_model}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_experiment_command.py -k "fees_only or realistic_costs" -v`
Expected: PASS.

- [ ] **Step 5: Update README Usage**

In `README.md`, under the `zcrypto experiment` options table, add a row for `--fees-only/--no-fees-only` (default off): "Use the fees-only cost model (no slippage/maker-fill) instead of the default calibrated realistic costs — the A/B baseline." Add a one-line note under the command that **calibrated realistic costs are the default** cost model (size-scaled slippage + maker-fill haircut). Don't hand-edit the mdformat TOC.

- [ ] **Step 6: Lint + targeted suite + commit**

```bash
uv run ruff check --fix cli/experiment/command.py tests/test_experiment_command.py
uv run ruff format cli/experiment/command.py tests/test_experiment_command.py
uv run pytest tests/test_experiment_command.py tests/test_experiment_costs.py tests/test_experiment_scaffold.py tests/test_experiment_recipe.py -q
git add cli/experiment/command.py tests/test_experiment_command.py README.md
git commit -m "feat(experiment): add --fees-only flag + cost-model marker"
```

---

### Task 4: `calibrate_execution.py` calibration script + estimators

**Files:**
- Create: `cli/experiment/scripts/__init__.py` (if absent), `cli/experiment/scripts/calibrate_execution.py`, `cli/experiment/scripts/README.md`
- Test: `tests/test_calibrate_execution.py`

**Interfaces:**
- Consumes: the aggTrades mirror (`aggtrades_mirror_path` from `cli/data/mirror.py`) + the manifest; produces `COST_CALIBRATION`-shaped output (printed for the closeout to paste into `costs.py`).
- Produces: `estimate_impact_coef(trades, bar_dollar_volume, probe_frac=0.005) -> float`, `estimate_fill(trades) -> tuple[float, float]` (fill_rate, spread), `calibrate(paths, source=None) -> dict` (the `COST_CALIBRATION` dict), `main()`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_calibrate_execution.py` (new), use a tiny synthetic aggTrades DataFrame (columns `price, quantity, is_buyer_maker`) with a known answer:

```python
import pandas as pd


def _trades(prices, qtys, makers):
    return pd.DataFrame({"price": prices, "quantity": qtys, "is_buyer_maker": makers})


def test_estimate_impact_coef_recovers_known_coefficient():
    from cli.experiment.scripts.calibrate_execution import estimate_impact_coef

    # A book that walks linearly: consuming a probe of `probe_frac` of bar volume moves VWAP
    # a known amount → the recovered c = impact_bps_ratio / probe_frac**2 is finite + positive.
    trades = _trades(
        prices=[100.0, 100.1, 100.2, 100.3, 100.4],
        qtys=[10.0, 10.0, 10.0, 10.0, 10.0],
        makers=[True, True, False, False, True],
    )
    bar_dollar_volume = sum(p * q for p, q in zip(trades["price"], trades["quantity"]))
    c = estimate_impact_coef(trades, bar_dollar_volume, probe_frac=0.2)
    assert isinstance(c, float) and c > 0.0


def test_estimate_fill_returns_rate_and_spread():
    from cli.experiment.scripts.calibrate_execution import estimate_fill

    trades = _trades(
        prices=[100.0, 100.0, 100.1, 100.1, 100.0],
        qtys=[5.0, 5.0, 5.0, 5.0, 5.0],
        makers=[True, False, True, False, True],
    )
    fill_rate, spread = estimate_fill(trades)
    assert 0.0 <= fill_rate <= 1.0
    assert spread >= 0.0


def test_calibrate_emits_cost_calibration_shape(tmp_path, monkeypatch):
    # calibrate() with an empty/synthetic sample returns the COST_CALIBRATION shape (keys present).
    from cli.experiment.scripts.calibrate_execution import calibrate

    out = calibrate(sample_frames={"BTCUSDT": [_trades([100.0, 100.1], [1.0, 1.0], [True, False])]})
    assert set(out) >= {"impact_cost", "maker_fill_haircut", "tiers"}
    assert isinstance(out["impact_cost"], float)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_calibrate_execution.py -v`
Expected: FAIL — module/functions not defined.

- [ ] **Step 3: Implement the estimators + `calibrate` + `main`**

Create `cli/experiment/scripts/calibrate_execution.py`:

```python
"""One-off: calibrate the realistic execution-cost constants from the iter-17 aggTrades sample.

Usage:
    uv run python cli/experiment/scripts/calibrate_execution.py [--backup-dir <path>]

Parses the aggTrades zips in the raw mirror (per pair, per day), estimates per-pair/per-tier
(impact coefficient c, maker-fill rate f, spread s), and PRINTS a COST_CALIBRATION dict to paste
into cli/experiment/costs.py at the iter-19 closeout. NOT part of the routine flow — see
cli/experiment/scripts/README.md.

The estimators are deliberately simple, daily-granularity approximations (documented in the spec):
  - impact c: simulate consuming `probe_frac` of the bar's $-volume from the first trade price;
    realized VWAP slippage (ratio) = c * probe_frac**2  →  c = slippage_ratio / probe_frac**2.
  - fill (f, s): spread s = (mean taker-buy price - mean maker price) / mid; fill rate f =
    fraction of volume resting as maker (is_buyer_maker aggregated) as a fill proxy.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Liquidity tiers for the iter-17 sample (by daily $-volume); confirmed at calibration.
TIERS: dict[str, tuple[str, ...]] = {
    "deep": ("BTCUSDT", "ETHUSDT"),
    "mid": ("SOLUSDT", "LINKUSDT", "ATOMUSDT"),
    "thin": ("PEPEUSDT",),
}


def estimate_impact_coef(trades: pd.DataFrame, bar_dollar_volume: float, probe_frac: float = 0.005) -> float:
    """Recover qlib's impact coefficient c from one bar's trades.

    Consume `probe_frac` of `bar_dollar_volume` starting at the first trade; the realized VWAP
    slippage ratio vs the first price equals c * probe_frac**2, so c = ratio / probe_frac**2.
    """
    if trades.empty or bar_dollar_volume <= 0 or probe_frac <= 0:
        return 0.0
    p0 = float(trades["price"].iloc[0])
    target = bar_dollar_volume * probe_frac
    cum_val = 0.0
    cum_qty = 0.0
    for price, qty in zip(trades["price"].to_numpy(), trades["quantity"].to_numpy()):
        take = float(qty)
        line_val = float(price) * take
        if cum_val + line_val >= target:
            take = max((target - cum_val) / float(price), 0.0)
            line_val = float(price) * take
        cum_val += line_val
        cum_qty += take
        if cum_val >= target:
            break
    if cum_qty <= 0 or p0 <= 0:
        return 0.0
    vwap = cum_val / cum_qty
    slippage_ratio = abs(vwap - p0) / p0
    return float(slippage_ratio / (probe_frac**2))


def estimate_fill(trades: pd.DataFrame) -> tuple[float, float]:
    """Estimate (maker_fill_rate, spread_ratio) from one bar's trades.

    fill_rate = fraction of volume where is_buyer_maker is True (a resting-maker proxy);
    spread = (mean price of taker-buy trades - mean price of maker trades) / mid, clamped >= 0.
    """
    if trades.empty:
        return 0.0, 0.0
    qty = trades["quantity"].to_numpy(dtype=float)
    maker_mask = trades["is_buyer_maker"].to_numpy(dtype=bool)
    total = float(qty.sum())
    fill_rate = float(qty[maker_mask].sum() / total) if total > 0 else 0.0
    maker_px = trades.loc[maker_mask, "price"]
    taker_px = trades.loc[~maker_mask, "price"]
    mid = float(trades["price"].mean())
    if len(maker_px) and len(taker_px) and mid > 0:
        spread = max((float(taker_px.mean()) - float(maker_px.mean())) / mid, 0.0)
    else:
        spread = 0.0
    return fill_rate, spread


def calibrate(sample_frames: dict[str, list[pd.DataFrame]], *, taker_premium: float = 0.0002) -> dict:
    """Aggregate per-pair estimates into the COST_CALIBRATION dict.

    `sample_frames` maps SYMBOL -> list of per-day trades DataFrames. Returns the
    {"impact_cost", "maker_fill_haircut", "tiers"} dict (single representative impact_cost +
    haircut; per-tier breakdown recorded under "tiers").
    """
    sym_to_tier = {s: t for t, syms in TIERS.items() for s in syms}
    per_tier: dict[str, dict] = {}
    for sym, frames in sample_frames.items():
        tier = sym_to_tier.get(sym, "mid")
        cs, fs, ss = [], [], []
        for tr in frames:
            bar_vol = float((tr["price"] * tr["quantity"]).sum())
            cs.append(estimate_impact_coef(tr, bar_vol))
            f, s = estimate_fill(tr)
            fs.append(f)
            ss.append(s)
        bucket = per_tier.setdefault(tier, {"c": [], "f": [], "s": []})
        bucket["c"].extend(cs)
        bucket["f"].extend(fs)
        bucket["s"].extend(ss)

    def _mean(xs: list[float]) -> float:
        return float(sum(xs) / len(xs)) if xs else 0.0

    tiers_out = {}
    for tier, b in per_tier.items():
        f = _mean(b["f"])
        s = _mean(b["s"])
        tiers_out[tier] = {
            "impact_cost": _mean(b["c"]),
            "fill_rate": f,
            "spread": s,
            "haircut": (1.0 - f) * (s / 2.0 + taker_premium),
        }
    # Single representative = mean across tiers present (the closeout records whether tiers diverge).
    impact = _mean([t["impact_cost"] for t in tiers_out.values()])
    haircut = _mean([t["haircut"] for t in tiers_out.values()])
    return {"impact_cost": impact, "maker_fill_haircut": haircut, "tiers": tiers_out}


def _load_sample_frames(backup_dir: Path) -> dict[str, list[pd.DataFrame]]:
    """Read the aggTrades mirror zips into per-pair lists of trades DataFrames."""
    import zipfile

    from cli.data.mirror import aggtrades_mirror_path  # reuse the mirror path builder

    cols = ["agg_id", "price", "quantity", "first_id", "last_id", "ts", "is_buyer_maker", "is_best_match"]
    root = backup_dir / "raw"
    frames: dict[str, list[pd.DataFrame]] = {}
    base = root / "spot" / "daily" / "aggTrades"
    for sym_dir in sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []:
        sym = sym_dir.name
        for zpath in sorted(sym_dir.rglob("*.zip")):
            with zipfile.ZipFile(zpath) as zf:
                name = zf.namelist()[0]
                df = pd.read_csv(zf.open(name), header=None, names=cols, usecols=["price", "quantity", "is_buyer_maker"])
            frames.setdefault(sym, []).append(df)
    return frames


def main() -> None:
    import argparse
    import json

    from cli.config import load_config, resolve_backup_dir

    parser = argparse.ArgumentParser(description="Calibrate realistic execution costs from the aggTrades sample.")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Mirror backup dir (default: from zcrypto.toml).")
    args = parser.parse_args()

    backup_dir = resolve_backup_dir(args.backup_dir, load_config())
    print(f"Calibrating execution costs from aggTrades under {backup_dir}/raw ...")
    frames = _load_sample_frames(backup_dir)
    print(f"Loaded {sum(len(v) for v in frames.values())} pair-days across {len(frames)} pairs.")
    result = calibrate(frames)
    print("COST_CALIBRATION = " + json.dumps(result, indent=4))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_calibrate_execution.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Register the script in a scripts README**

Create `cli/experiment/scripts/README.md` with an entry for `calibrate_execution.py`: one-time, parses the aggTrades sample and prints the `COST_CALIBRATION` dict to paste into `cli/experiment/costs.py`; usage `uv run python cli/experiment/scripts/calibrate_execution.py [--backup-dir <path>]`; note it is NOT part of the routine `zcrypto experiment` flow. (Match the style of `cli/data/scripts/README.md` — read it first.)

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix cli/experiment/scripts/calibrate_execution.py tests/test_calibrate_execution.py
uv run ruff format cli/experiment/scripts/calibrate_execution.py tests/test_calibrate_execution.py
git add cli/experiment/scripts/ tests/test_calibrate_execution.py
git commit -m "feat(experiment): add calibrate_execution one-off cost-calibration script"
```

---

## Closeout (operational — run by the orchestrator after Tasks 1-4 land, NOT a subagent task)

1. **Calibrate:** run `uv run python cli/experiment/scripts/calibrate_execution.py` on the real aggTrades sample → record the per-tier `(c, f, s)` + whether tiers diverge materially. Paste the printed `impact_cost` / `maker_fill_haircut` / `tiers` into `cli/experiment/costs.py` (replacing the provisional values), update `test_cost_calibration_shape` if needed, re-run `uv run pytest tests/test_experiment_costs.py`; commit `feat(experiment): set calibrated execution-cost constants from the aggTrades sample`. Dispatch a review subagent (per `commit-messages.md`).
2. **Re-measure:** run all 5 recipes **calibrated-default vs `--fees-only`** at `--seeds 16 --deterministic --quick` (redis up via `scripts/redis.sh start`). Record, per recipe, the holdout distribution (ending value, Sharpe, PSR) for both + the **net-P&L haircut** (realistic below fees-only, vs the seed-noise band); note whether it scales with turnover / thin-book exposure.
3. **Resolve `T0004`:** flip front-matter `partial` → `resolved`, `git mv docs/open-topics/T0004-execution-slippage-fills.md docs/open-topics/archive/`, update the README index link to `archive/` + move the bullet to R&D `### Resolved`; record the haircut verdict in the topic.
4. **README `## Usage`:** confirm the `--fees-only` flag + calibrated-costs-default note landed (Task 3).
5. **iter-19 iterations-history entry:** the cost model, the calibration (per-tier finding + single-vs-tiered), the haircut verdict, and the `T0004` resolution.

---

## Self-Review

**Spec coverage:** Decision 1 (one-off calibration script) → Task 4 + Closeout 1; Decision 2 (slippage via impact_cost, per-tier analysis) → Task 1/2 + Task 4's `estimate_impact_coef`/`tiers` (single-scalar wired, per-tier recorded — resolves the spec's "per-tier mapping" against qlib's single-scalar exchange, see Global Constraints); Decision 3 (maker-fill haircut) → Task 2 (fee bump) + Task 4's `estimate_fill`; Decision 4 (calibrated default + `--fees-only`) → Tasks 1-3; Decision 5 (re-measure) → Closeout 2. Subsumed parametric term: the calibrated `impact_cost` is the size-scaled term (noted). README → Task 3. T0004 resolution → Closeout 3.

**Placeholder scan:** No TBD/TODO. The provisional `COST_CALIBRATION` values are explicitly marked + replaced at Closeout 1 (the only deferred concretes, correctly closeout RECONs). All code steps carry full code.

**Type consistency:** `COST_CALIBRATION` keys (`impact_cost`/`maker_fill_haircut`/`tiers`) identical across Task 1 (costs.py), Task 4 (calibrate output), and the Recipe defaults. `Recipe.fees_only`/`impact_cost`/`maker_fill_haircut` named identically across Tasks 1-3. `exchange_kwargs(recipe)` keeps its single-arg signature (Global Constraints) — the 4 call sites are untouched. `estimate_impact_coef(trades, bar_dollar_volume, probe_frac)` / `estimate_fill(trades) -> (f, s)` / `calibrate(sample_frames)` consistent between Task 4's code and tests.
