---
status: open
---

# Regime-overlay tuning (the slow gate works — now refine it)

## Context — what

iter-23 (spec/plan `00022`) discovered that the BTC-trend regime overlay had been **inert since iter-12** (qlib's `TopkDropoutStrategy` sizes buys with the raw `self.risk_degree`, bypassing the overridden `get_risk_degree()`; fixed by a strategy-level workaround). Once actually wired, the **slow binary-200d gate (`regime_steady`) is the project's first OOS-robust improvement**: across-window long-only mean Sharpe **0.289 vs `steady` 0.154**, worst window **−0.220 vs −0.753** (full cash through the 2022 crash; 2025 bear loss halved). Crucially, **faster gates were worse** — `regime_fast` (100d) and `regime_cross` (50/200) *whipsawed*, re-entering on bear-market dead-cat bounces (regime_fast made 2022 −1.28). This topic tracks refining the (now-working) overlay.

## Why this matters

The slow gate is a genuine defensive edge (capital preservation in bears) and the first thing in the project that improves risk-adjusted return out-of-sample across windows. It is defensive, not new alpha — but it is a usable building block, and the whipsaw finding points at concrete levers to push the improvement further (or to combine the gate with a market-neutral book that *does* carry alpha).

## Findings so far

- iter-23: slow binary-200d gate Pareto-beats `steady` (mean 0.289 vs 0.154; worst −0.220 vs −0.753). Faster/cross gates whipsaw and underperform. See the iter-23 entry in `docs/iterations-history.md`.
- iter-24: of the two refinement levers — **vol-targeting is a mild positive, graded is negative.** `regime_voltarget` (binary 200d + `vol_target=0.50`) is the new (slim) best: mean 0.311 vs the binary gate's 0.289, worst −0.223 (≈ binary), recovering a little bull-window exposure while keeping the 2022 full-cash protection. `regime_graded` is worse (mean 0.259, worst −0.658): its ±5% chop band keeps partial exposure in the 2022 crash (−0.658 vs full-cash 0.000), defeating the gate. **The binary all-or-nothing full-cash-in-bear is the load-bearing virtue.** Caveat: the vol-target gain (+0.023) is small / possibly within seed noise.
- iter-25/26: **the feature-stacking thread is conclusively closed.** Stacking funding (`regime_funding_voltarget`, mean 0.241) or cross-asset features (`regime_crossasset_voltarget`, 0.304) on the gate fails to beat `regime_voltarget` (0.311) — no feature add improves the gated book. `regime_voltarget` (gate on plain Alpha158) is the **~0.31 OOS defensive ceiling**, and the research levers of this overlay are exhausted.
- The inert-gate root cause + the strategy workaround are in `cli/experiment/strategies/regime.py`; the qlib bug has been **submitted upstream** to microsoft/qlib (draft at `.tmp/qlib-bug-topkdropout-ignores-get-risk-degree.md`, gitignored).

## Suggested next steps

The overlay's research levers are exhausted — graded, vol-target, funding-stack, cross-asset-stack, **and now the anti-whipsaw confirmation filter** are all closed (see Findings so far); `regime_voltarget` is the ~0.31 OOS defensive ceiling. Combining the gate with a market-neutral / L/S book is dead-on-arrival (the L/S edge failed OOS, iter-22). The only forward research path is genuinely new information (on-chain, `T0010`). Remaining items:

- **Anti-whipsaw confirmation filter — CLOSED (iter-53/54).** Added a causal `confirm_days` debounce on the BTC-200d gate (flip only after N consecutive days on the new side) and swept N=2/3/5/10 vs `beta_null`: **every N is net-negative** (N2 −0.095, N3 −0.108, N5 −0.034, N10 −0.362). Any confirmation lag delays the (correct) bull re-entry by more than the whipsaw it saves — confirming the slow 200d gate is already the right speed. The `regime_confirm_days` mode + `beta_null_confirm{2,3,5,10}` recipes remain as the documented negative.
- **`vol_target` finer-grid sliver (last untested low-EV lever):** iter-24 chose `vol_target=0.50` over no-vol-target (gain +0.023, within seed noise); a finer grid (0.40/0.45/0.55/0.60) was not swept. Very low EV (the lever is ~noise), but the last defined refinement before the overlay is fully closed.
- **qlib upstream bug — submitted, awaiting release:** filed to microsoft/qlib (`TopkDropoutStrategy` should size buys via `get_risk_degree()`); retire the strategy-level workaround in `cli/experiment/strategies/regime.py` once the fix ships in an official release.
