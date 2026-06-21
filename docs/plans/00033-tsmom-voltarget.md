# per-asset TSMOM + vol-targeting (`tsmom_voltarget`) — Implementation Plan (iter-35)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** ship a per-asset trend-gated, inverse-vol, vol-targeted recipe `tsmom_voltarget` (spec
`docs/specs/00033-tsmom-voltarget-design.md`) and A/B it against `beta_null`. One variable vs `beta_null`:
the gate (market BTC-200d → per-asset own-100d-SMA trend selection).

**Tech stack:** Python 3.12, qlib, numpy/pandas, pytest, uv. Redis up for backtest tests.

## Global Constraints

- `tsmom_voltarget` = `beta_null`'s book verbatim EXCEPT the strategy gains `trend_window=100` (per-asset
  trend gating, market gate disabled). Frozen: top-10-liquidity PIT universe, inverse-vol, `vol_target=0.50`,
  `vip2_bnb`, `DummyRegressor`, label `Ref($close,-6)/Ref($close,-1)-1`, `label_horizon_days=6`.
- `trend_window=None` ⇒ `VolWeightedRegimeStrategy` is byte-identical to today (back-compat with `beta_null`,
  `regime_volweight_majors`).
- TDD; ruff before each commit; per-period cost-adjusted verdicts (`stress --null beta_null`).

## File Structure

- Modify: `cli/experiment/strategies/regime.py` (`VolWeightedRegimeStrategy` per-asset trend mode)
- Create: `cli/experiment/recipes/tsmom_voltarget.py`
- Tests: `tests/test_regime_strategy.py`, `tests/test_experiment_recipe.py`
- Closeout: `docs/iterations-history.md`, `docs/open-topics/` (follow-ups), `README.md` if user-facing

---

### Task 1: per-asset trend-gating mode on `VolWeightedRegimeStrategy`

**Files:** Modify `cli/experiment/strategies/regime.py`; Test `tests/test_regime_strategy.py`.

**Interfaces — Produces:** `__init__` gains `trend_window: int | None = None`. When set:
- the **market regime multiplier is disabled** (`_mult_for`/the BTC gate returns `1.0` — no full-cash-on-BTC);
- a **per-asset trend filter** is applied in `generate_target_weight_position`: after the existing
  `names = list(score.index)` (and the liquidity-membership intersect from iter-34), drop any name whose latest
  close at `trade_start_time` is **≤ its own SMA(`trend_window`)**. The close/SMA panel is built lazily from
  `D.features(self.weight_universe, ["$close"])` (mirror `_build_vol_panel`, regime.py:192-198), cached;
  expose an injectable `self._close_panel` (or `_sma_panel`) test seam like `_membership_schedule`.
- `trend_window=None` ⇒ no change (existing market-gate behaviour).

- [ ] **Step 1 — failing test:** inject `_membership_schedule` + a synthetic close/SMA panel (test seam);
  with `trend_window=100`, feed a `score` whose names include some above and some below their SMA → assert the
  held set is exactly members ∩ {close > SMA}; assert a name below its SMA is dropped; assert the market gate
  does NOT zero exposure when `trend_window` is set (per-asset filter governs, not BTC). Assert `trend_window=None`
  reproduces today's output (regression).
- [ ] **Step 2 — red.** `uv run pytest tests/test_regime_strategy.py -q`
- [ ] **Step 3 — implement** (lazy `$close` SMA panel + filter + multiplier-disable; keep inverse-vol weighting
  + liquidity membership intact).
- [ ] **Step 4 — green** + ruff. **Step 5 — commit** `feat(experiment): add per-asset trend-gating mode to VolWeightedRegimeStrategy`.

### Task 2: `tsmom_voltarget` recipe + drift-guard

**Files:** Create `cli/experiment/recipes/tsmom_voltarget.py`; Test `tests/test_experiment_recipe.py`.

**Interfaces — Produces:** `RECIPE = Recipe(name="tsmom_voltarget", ...)` = a copy of `beta_null` with
`trend_window=100` added to `strategy_config.kwargs` (everything else identical: universe, membership_top_n=10,
membership_lookback_days=30, inverse-vol, vol_target 0.50, vip2_bnb, DummyRegressor, label, segments).

- [ ] **Step 1 — failing drift-guard test:** `resolve_recipe("tsmom_voltarget")` has all of `beta_null`'s frozen
  params PLUS `trend_window==100`; its non-lever fields match the `beta_null`/`steady` book.
- [ ] **Step 2 — red.** `uv run pytest tests/test_experiment_recipe.py -q -k tsmom`
- [ ] **Step 3 — implement** the recipe. **Step 4 — green** + resolve-check + ruff.
- [ ] **Step 5 — commit** `feat(experiment): add tsmom_voltarget recipe (per-asset TSMOM + vol-target)`.

### Task 3: stress A/B verdict + closeout

**Files:** `docs/iterations-history.md`, `docs/open-topics/`, `README.md` (if user-facing).

- [ ] **Step 1 — run the A/B (background, redis-gated):** `uv run zcrypto stress --recipe tsmom_voltarget --null beta_null --seeds 4`; read the per-window `delta_sharpe` + `delta_ci` + across-window `delta_mean_across_windows`.
- [ ] **Step 2 — verdict:** record whether the mean delta-vs-null > 0 and its CI clears 0 (the success bar).
  Honest either way (a null result is a real finding).
- [ ] **Step 3 — open-topics follow-ups:** the per-asset SMA window-sweep (50/100/200) and the intraday
  (4h / realized-vol) sizing variant — new `T<NNNN>` topics (per `.claude/rules/open-topics.md`).
- [ ] **Step 4 — iterations-history:** append the iter-35 entry with the measured delta-vs-null verdict + what
  landed (the `trend_window` mode, the recipe).
- [ ] **Step 5 — commit** `docs: iter-35 closeout — tsmom_voltarget A/B verdict vs beta_null`.

## Iterations-history note

Task 3 appends the iter-35 entry (per `.claude/rules/iterations-history.md`) with the real measured verdict.
