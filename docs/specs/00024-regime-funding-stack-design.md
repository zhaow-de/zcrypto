# Regime × funding stack — Design

**Iteration:** iter-25
**Advances open-topic:** `T0017` (regime-overlay tuning) — the "combine the gate with another signal" lever.
**Builds on:** iter-20 (`funding_steady` — the funding-carry feature, the best single feature add), iter-24 (`regime_voltarget` — the best regime gate, OOS mean Sharpe 0.311), iter-23 (the gate now actually engages).

## Context — what

The project has two positive ingredients: the **funding-carry signal** (`funding_steady`, a modest cross-sectional edge — iter-20) and **regime-timing** (`regime_voltarget`, binary 200d gate + vol-targeting — the best recipe to date, OOS mean Sharpe 0.311). This iteration tests whether they **stack** — i.e. does regime-gating the funding book beat the gated plain book — or are **redundant**, since iter-21 showed funding's long-only edge is itself a *defensive low-beta tilt*, and the regime gate also avoids beta in bears. They may target the same risk.

## Why this matters

Stacking the two best ingredients is the most direct remaining shot (within knob-tweak scope) at pushing the defensive recipe past 0.311 toward something less marginal. And the result is decisive either way: if regime-gating the funding book beats `regime_voltarget`, funding carries something orthogonal to beta-timing (a genuine stack → new best recipe); if it merely matches `regime_voltarget`, funding's edge IS the beta-timing the gate already provides (redundant — confirming iter-21's "funding = defensive tilt" read, and telling us to stop stacking defenses and look for orthogonal alpha).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One new recipe `regime_funding_voltarget`** = `funding_steady`'s book verbatim (incl. the `FundingRateProcessor`) + the iter-24 winning gate (`RegimeGatedTopkStrategy`, binary 200d + `vol_target=0.50`). | Isolates the single change vs `funding_steady` (the gate) and vs `regime_voltarget` (the funding feature), so the 4-arm A/B cleanly attributes any delta. Uses the proven best gate. |
| 2 | **4-arm A/B on the `zcrypto stress` OOS harness** (`--seeds 8`): `steady` · `funding_steady` · `regime_voltarget` · `regime_funding_voltarget`. | Compares the combo to BOTH its parents (the gated plain book and the ungated funding book) + the ungated baseline. `steady`, `funding_steady`, `regime_voltarget` stress results already exist on disk (gate-independent / iter-24 post-fix) and are reused; only `regime_funding_voltarget` runs fresh. |
| 3 | **The combo copies `funding_steady`'s book verbatim** (handler with `FundingRateProcessor` first, model, label, segments, universe, fees) and changes ONLY `strategy_config` to the regime gate; `topk/n_drop/hold_thresh=10/1/5`, no `wf_enabled`. | Clean isolation; drift-guarded by a test against `resolve_recipe("funding_steady")`. |

## Component file tree

```
cli/experiment/recipes/
└── regime_funding_voltarget.py  # NEW: funding_steady's book (FundingRateProcessor + steady book) +
                                 #      RegimeGatedTopkStrategy binary/200d/vol_target=0.50.
tests/
└── test_experiment_recipe.py    # EXTEND: regime_funding_voltarget resolves; wires the regime gate;
                                 #         book (incl. FundingRateProcessor infer_processor) matches funding_steady.
README.md                        # MODIFY: Usage — add regime_funding_voltarget.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress --recipe regime_funding_voltarget --seeds 8`; read `steady` / `funding_steady` / `regime_voltarget` from their existing stress bundles. Record per-window long-only Sharpe + across-window mean / worst for all four. Verdict → `docs/iterations-history.md`:
- **Stack:** `regime_funding_voltarget` mean Sharpe > `regime_voltarget` (0.311) AND > `funding_steady` → funding adds something orthogonal to the gate → new best recipe.
- **Redundant:** `regime_funding_voltarget` ≈ `regime_voltarget` → funding's edge is the beta-timing the gate already supplies (confirms iter-21) → stop stacking defenses.

## Scope & deferred

- **In:** the 1 new recipe; the drift-guard test; the 4-arm OOS-stress A/B + verdict; README; T0017 progress note.
- **Out (stays in T0017):** anti-whipsaw filter; gating `crossasset_steady`; combining the gate with a market-neutral book; finer vol_target tuning.
- **Untouched:** `RegimeGatedTopkStrategy`, `FundingRateProcessor`, the harnesses, data/cost layers.

## Closeout tasks (authored when the work is real)

- Run the `regime_funding_voltarget` stress; assemble the 4-arm table → record the stack-vs-redundant verdict (and the new best recipe if it stacks).
- iter-25 iterations-history entry; update `T0017` `## Findings so far` (stack result) and trim `## Suggested next steps`.
- README `## Usage`: `regime_funding_voltarget`.
