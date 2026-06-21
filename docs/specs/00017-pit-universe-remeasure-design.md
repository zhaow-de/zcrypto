# Point-in-time universe + survivorship re-measure — Design

**Iteration:** iter-18
**Resolves open-topic:** `T0005` (point-in-time universe / survivorship) → **`resolved`** at closeout — the experiment-side de-bias that completes the survivorship-free harness on top of iter-16's data substrate.
**Depends on:** iter-16 (the delisted majors in the dataset), iter-14 (the multi-seed holdout A/B), the recon below.
**Parks:** force-liquidate-to-cash → a new follow-up open-topic.

## Context — what

iter-16 acquired the survivorship-free **data substrate** (10 ever-top-25 delisted/faded majors with real ranges). `T0005` is still partial: the experiment still trades the **survivor** universe (each recipe's hardcoded 19-pair `universe` tuple), so every past result remains survivorship-inflated. This iteration adds the experiment-side de-bias — a **point-in-time universe** (the survivors + the delisted majors + the Terra LUNA blow-up) — and **re-measures every recipe PIT-vs-survivor** to deliver the honest verdict, resolving `T0005`.

**Recon (done — sizes this iteration):** a backtest forced to hold a delisted pair (`NANOUSDT`) through its 2022-01-24 delisting showed qlib **freezes** the position at its last marked value — the mark-to-market loss while the coin had data flows straight into the portfolio (NANO's decline → −31%), with no error and no silent drop. So **the delisting-loss is already captured by qlib's default behavior**; no custom engine is needed for the verdict. (The frozen capital can't redeploy — a conservative imperfection, parked as a follow-up.)

## Why this matters

Research §3/§12: a "currently listed" universe inflates historical results via survivorship; a held delisted coin drops 50-90% before liquidation. Every recipe verdict to date (iter-12/13/14) was measured survivor-only. Until we re-measure on the point-in-time universe — holding the coins that *died* — no result is trustworthy. This is the rigor gate that makes any future positive result believable; it also data-enables `T0007`'s LUNA/FTX stress pass.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Terra LUNA acquisition (data):** the old-LUNA blow-up is entirely in `LUNAUSDT[2020 .. ~2022-05-27]` (recon: $6→$80→$0.00005 crash, then the symbol is *reused* for Luna 2.0 at $2.53). Acquire it via `download LUNAUSDT --to <Luna-2.0-launch boundary>` (capped before Luna 2.0; `--allow-interior-gaps` for any crash-halt days) → `rename LUNAUSDT → LUNCUSDT` → append the live `LUNCUSDT` tail (zombie). RECON: the exact boundary (~2022-05-28) + the real-`LUNCUSDT` listing date. | The capped `--to` excludes Luna 2.0; the rename gives old-LUNA its canonical Luna-Classic identity (`LUNCUSDT` is live, so `backfill` extends it naturally). Reuses existing commands — no new code. The crash (the survivorship event) is captured; the tail rides along untraded. |
| 2 | **PIT universe via a `--pit-universe` flag** (default off) on `zcrypto experiment`: when set, the run's universe = `recipe.universe + PIT_ADDITIONS`, where `PIT_ADDITIONS` is a shared constant of the iter-16 delisted majors + Terra `LUNCUSDT`. | DRY realization of "PIT-variant every recipe" — one universe-additions constant + one flag, applied to any recipe, vs duplicating 5 recipes. Point-in-time membership is then free: qlib loads each pair only within its `[listing, delisting]` range (model trains *and* trades the survivorship-free panel). |
| 3 | **Delisting-loss = qlib's freeze (no code).** The recon validated it captures the mark-to-market loss to the last close. The verdict uses it as-is. | The headline T0005 requirement (the loss is realized) is met by qlib's default. Building a custom delisting engine for the verdict would be premature. |
| 4 | **Re-measure ALL active recipes survivor-vs-PIT** (`skeleton`, `steady`, `alpha360_steady`, `crossasset_steady`, `regime_steady`) via the iter-14 **multi-seed holdout** (`--seeds 16`, fast) → per-recipe survivorship-inflation distribution; `rank`/CPCV as available. | The bias affects every recipe; re-measuring all de-biases all past verdicts. Multi-seed (not single-run) so the inflation is read against the seed-noise band (iter-14 discipline). |
| 5 | **Force-liquidate-to-cash is parked**, not built — a new open-topic (the frozen delisting position can't redeploy capital; a refinement that would make the PIT verdict slightly *less* pessimistic). | The freeze captures the loss conservatively (the right direction). Redeployment realism is a separable refinement, not needed for the resolution. |

## Component file tree

```
cli/experiment/
├── recipes/base.py   # MODIFY (or a new pit.py): PIT_ADDITIONS constant (iter-16 delisted majors + LUNCUSDT) + a helper that returns recipe.universe + PIT_ADDITIONS.
├── command.py        # MODIFY: add `--pit-universe` flag to `experiment`; when set, override the run's universe (recipe.universe + PIT_ADDITIONS) at the cpcv/scaffold/multiseed call sites.
├── cpcv.py / scaffold.py / multiseed.py  # MODIFY: thread the effective universe (instruments=...) so the flag flows to handler + backtest. Survivor path (flag off) byte-identical.
└── (no delisting-loss code — qlib's freeze is used as-is)
tests/
├── test_experiment_command.py   # EXTEND: --pit-universe expands the universe (recipe.universe + PIT_ADDITIONS); default off = unchanged.
├── test_experiment_*.py         # EXTEND (redis-gated): a PIT run loads the delisted majors; survivor run byte-identical.
README.md                        # MODIFY: Usage — the `--pit-universe` flag.
data/pairs.txt + ./data          # (closeout) acquire Terra LUNA into the real dataset.
```

## Terra acquisition (operational, reusing iter-16 commands)

1. Add `LUNAUSDT` + `LUNCUSDT` to the pairs file; `download` capped: `LUNAUSDT --to <boundary>` (the rest to today) — RECON the boundary; use `--allow-interior-gaps` if the May-2022 crash has halt-day 404s.
2. `zcrypto data rename LUNAUSDT LUNCUSDT` (the field-agnostic rename, iter-15) — merges old-LUNA[..boundary] + live LUNCUSDT[listing..], gap NaN.
3. `verify` → `LUNCUSDT` spans the crash → today; add `LUNCUSDT` to `PIT_ADDITIONS`.

## Re-measure & verdict

For each of the 5 recipes: run the multi-seed holdout **survivor** (flag off) and **PIT** (flag on) at `--seeds 16` (fast). Record, per recipe: the holdout-metric distribution (ending value, Sharpe, PSR) survivor vs PIT, and the **survivorship inflation** = how much the PIT distribution sits below the survivor one (read against the seed-noise band). Expected: PIT is uniformly worse (the held blow-ups drag returns); the magnitude is the headline number. The verdict lands in `docs/iterations-history.md` + the recipe docstrings; `T0005` → resolved.

## Scope & deferred

- **In:** Terra LUNA acquisition; the `PIT_ADDITIONS` constant + `--pit-universe` flag (threaded through cpcv/scaffold/multiseed); the all-recipe survivor-vs-PIT multi-seed re-measure + verdict; `T0005` → resolved.
- **Out (parked open-topic):** force-liquidate-to-cash (redeploy frozen delisting capital).
- **Out (separate):** `T0007` multi-window/crisis stress (now data-enabled); the funding feature (`T0010`); the `T0004` execution calibration.
- **Untouched:** the data acquisition pipeline (Terra reuses existing commands); the recipes' models/labels/strategies; `exchange_kwargs` (freeze is qlib's default).

## Closeout tasks (authored when the work is real)

- Acquire Terra LUNA into the real `./data` (the capped download + rename); `verify` the `LUNCUSDT` range (the crash → today). Run all 5 recipes survivor-vs-PIT (`--seeds 16`) → the per-recipe survivorship-inflation verdict.
- Flip `T0005` → `resolved` (follow the archive convention if PR #50 is merged by then — move to `docs/open-topics/archive/`; else in place). The verdict in `docs/iterations-history.md` + the recipe docstrings (superseding the survivor-only numbers).
- Open the parked **force-liquidate-to-cash** open-topic (the frozen-capital refinement).
- README `## Usage`: the `--pit-universe` flag.
