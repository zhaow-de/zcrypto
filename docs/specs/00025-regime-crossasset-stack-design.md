# Regime × cross-asset stack — Design

**Iteration:** iter-26
**Advances open-topic:** `T0017` (regime-overlay tuning) — the "gate `crossasset_steady`" lever; decisively closes the feature-stacking question.
**Builds on:** iter-13 (`crossasset_steady` — the cross-asset relative-strength feature, the iter-13 feature winner), iter-24 (`regime_voltarget`, best gate, OOS mean Sharpe 0.311), iter-25 (funding did NOT stack with the gate — redundant).

## Context — what

iter-25 found regime-timing does not stack with the funding signal (funding's edge is a defensive beta tilt, redundant with the gate). This iteration runs the same test on the **cross-asset** signal — a *different* feature type (relative strength / cross-sectional momentum, not carry) — to see if it behaves differently. `crossasset_steady` has also never been stress-tested OOS. The result decisively closes the feature-stacking thread: if the cross-asset features are *also* redundant once gated, that is strong evidence the gate on plain Alpha158 (`regime_voltarget`) is the ceiling and feature-stacking is a dead end for this universe/period.

## Why this matters

The regime gate is the project's one robust lever; the best recipe gates the best underlying book. iter-25 showed funding adds nothing orthogonal to the gate. Cross-asset relative-strength is the other candidate "extra signal." If it stacks → a new best recipe and a genuinely orthogonal edge. If it does not → we stop stacking features on the gate and redirect (on-chain data, a different model class, or accept the defensive ceiling). Either outcome sharpens the research direction.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One new recipe `regime_crossasset_voltarget`** = `crossasset_steady`'s book verbatim (incl. the `CrossAssetProcessor` first in `infer_processors`) + the iter-24 winning gate (`RegimeGatedTopkStrategy`, binary 200d + `vol_target=0.50`). | Isolates the single change vs `crossasset_steady` (the gate) and vs `regime_voltarget` (the cross-asset features). Mirrors iter-25's structure exactly. |
| 2 | **4-arm A/B on `zcrypto stress`** (`--seeds 8`): `steady` · `crossasset_steady` · `regime_voltarget` · `regime_crossasset_voltarget`. | Compares the combo to both parents + the baseline. `steady` + `regime_voltarget` reused from disk; `crossasset_steady` (never stress'd) + the new combo run fresh. |
| 3 | **The combo copies `crossasset_steady`'s book verbatim**, changing ONLY `strategy_config`; `topk/n_drop/hold_thresh=10/1/5`, no `wf_enabled`. | Clean isolation; drift-guarded against `resolve_recipe("crossasset_steady")` (incl. the `CrossAssetProcessor`-first `infer_processors`). |

## Component file tree

```
cli/experiment/recipes/
└── regime_crossasset_voltarget.py  # NEW: crossasset_steady's book + RegimeGatedTopkStrategy binary/200d/vol_target=0.50.
tests/
└── test_experiment_recipe.py       # EXTEND: regime_crossasset_voltarget resolves; wires the gate; book (incl.
                                    #         CrossAssetProcessor-first infer_processors) matches crossasset_steady.
README.md                           # MODIFY: Usage — add regime_crossasset_voltarget.
```

## A/B & verdict

Closeout (redis up): run `zcrypto stress` for `crossasset_steady` + `regime_crossasset_voltarget`; reuse `steady` + `regime_voltarget` from disk. 4-arm per-window long-only Sharpe + mean / worst. Verdict → `docs/iterations-history.md`:
- **Stack:** `regime_crossasset_voltarget` mean > `regime_voltarget` (0.311) AND > `crossasset_steady` → cross-asset features are orthogonal to the gate → new best recipe.
- **Redundant:** `regime_crossasset_voltarget` ≤ `regime_voltarget` → like funding, cross-asset adds nothing the gate doesn't → feature-stacking on the gate is closed; redirect future work.
- Also note whether `crossasset_steady` (ungated) generalizes OOS at all (its first stress test).

## Scope & deferred

- **In:** the 1 new recipe; the drift-guard test; the 4-arm OOS-stress A/B + verdict; README; T0017 progress note.
- **Out (stays in T0017 / future):** anti-whipsaw filter; market-neutral combo (L/S failed OOS); on-chain data (T0010); a different model class.
- **Untouched:** `RegimeGatedTopkStrategy`, `CrossAssetProcessor`, harnesses, data/cost layers.

## Closeout tasks (authored when the work is real)

- Run the 2 fresh arms; assemble the 4-arm table → record the stack-vs-redundant verdict (+ does crossasset generalize OOS?).
- iter-26 iterations-history entry; update `T0017` (crossasset-gate lever result); if feature-stacking is now conclusively closed, note the redirect.
- README `## Usage`: `regime_crossasset_voltarget`.
