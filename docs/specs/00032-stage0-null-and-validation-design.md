# iter-34 — Stage 0: passive-beta null + validation harness (design)

**Goal:** establish a pre-registered *passive-beta null* and upgrade the measurement harness so every
later Phase-2 run reports **edge beyond beta** with honest uncertainty — the foundation that makes the
highest-EV bet (TSMOM + vol-targeting, the next iteration) trustworthy. **No edge target this iteration.**

## Context

Phase 1 (iters 9–33, `T0018`) established that daily-OHLCV cross-sectional ML ranking has no OOS edge,
and that its only survivor — a regime-gated inverse-vol majors basket (`regime_volweight_majors`,
across-window mean OOS Sharpe ~0.50) — is **beta-timing, not alpha**, and was **inflated by two
diseases**: a single-bear holdout and ~+0.38 selection bias from an 18-recipe sweep
(`docs/research/03.phase2-orientation.md` §1, §5; `02.phase1-summary.md` §7). The Phase-2 orientation
(§6 Stage 0) requires building the null + benchmark *first*: until a strategy beats a naive
200d-SMA-gated inverse-vol basket *net of costs* with a real CI, the project has demonstrated no edge.

This iteration builds that null and the machinery to measure "beyond the null" on every run.

## Non-goals (deferred)

- TSMOM / vol-targeting signal, or **any** edge bet (the immediately-following iteration).
- BTC→alt lead-lag (`T0020`), on-chain regime (`T0021`), derivatives-positioning — no new data.
- The interactive **holdout-look governance** (spending the reserved holdout is a human gate, per the
  Stage-0 review; this iteration only sets up the *trial counter* the deflation reads).

## Design overview

Two deliverables:

1. **The `beta_null` recipe** — a pre-registered, frozen naive rule (the yardstick).
2. **Three harness upgrades** — always-benchmark-vs-null, stationary-bootstrap CIs, and a trial register
   feeding a true-count deflated Sharpe.

### Component 1 — the `beta_null` recipe

A new recipe encoding the pre-registered rule. Parameters are **frozen in this spec** so the null can
never be retro-tuned (the whole point — a selection-bias-free benchmark):

- **Universe — top-10 by rolling dollar-volume (liquidity), point-in-time, monthly.** At each monthly
  rebalance rank the eligible names by trailing-N-day quote-asset dollar-volume (the `amount` kline field,
  already ingested) and take the top 10. **PIT eligibility is enforced at the data layer** — each pair's
  kline data exists only over its real listing/delisting range (`pipeline.find_available_range`), so a
  late-listed name structurally can't appear early; the static `PIT_ADDITIONS` blow-up capping (`T0005`,
  `base.with_pit_universe`) composes on top. *Market-cap ranking was preferred but is not computable* —
  the dataset has no circulating-supply data, and sourcing it would add an external, possibly-credentialed
  dependency that may not run unattended; dollar-volume is the standard crypto universe proxy, ≈ the mcap
  majors at N=10, and fully free/unattended (decisions log iter-034).
- **Strategy:** the existing `VolWeightedRegimeStrategy` (`cli/experiment/strategies/regime.py`) —
  `regime_mode="binary"`, `regime_benchmark="BTCUSDT"`, `regime_ma_window=200` (BTC 200d-SMA binary
  long/cash gate), inverse-vol weights (`weight_vol_lookback=30`), **`vol_target=0.50`** (matching the
  volweight-majors basket the null mirrors — the class default `None` is *not* used). Spot long/cash (no
  shorting). Realistic costs on (**`fee_preset="vip2_bnb"`**, the iter-19 calibrated model). *These exact
  values ARE the pre-registration — frozen here, not tunable.*
- **"Passive-beta" precisely:** the null carries *no cross-sectional / ML alpha bet*; the 200d-SMA gate is
  the minimal **beta-timing** overlay the orientation §1 defines as the right null (explicitly *not*
  buy-and-hold). So "beat the null" = "beat naive beta-timing."
- **Distinct from `regime_volweight_majors`:** mechanically similar, but `beta_null` is the *a-priori
  benchmark* (dynamic liquidity universe, frozen params), kept separate from that iter-32 sweep artifact.

**New machinery (the main recipe-side build):** recipes today take a **static** `universe` tuple, so the
**time-varying liquidity-ranked universe is new.** Cleanest shape: an offline, deterministic step that
computes the monthly top-10-by-trailing-dollar-volume membership from the kline `amount` field (composing
the existing PIT eligibility), persisted as a universe *schedule*, which the recipe + strategy consume in
place of a static tuple. (At N=10 the realized membership is expected to be near-static and ≈ the existing
`_MAJORS`; that the dynamic rule reproduces the majors is a *finding*, not a reason to hardcode the list.)

### Component 2 — harness upgrades

All three attach to the existing `zcrypto stress` (`cli/stress/command.py`, walk-forward OOS) and the
`rank`/deflated-Sharpe path (`T0002`).

1. **Always-benchmark-vs-null.** `stress` (and `experiment`) gain `--null beta_null` (default on). Every
   run also evaluates the null on the *same* windows/seeds and reports a **paired delta-vs-null**
   (candidate − null) per window and across-window. The headline verdict becomes the delta, not the raw
   Sharpe. Running `beta_null` *as* the candidate reports a ~0 delta (self-check).
2. **Stationary-bootstrap CIs.** A `stationary_bootstrap_ci()` (Politis–Romano stationary bootstrap, mean
   block length a parameter; varying block length probes **dependence-stress** — sensitivity to the
   autocorrelation/persistence assumption, *not* unseen-regime stress) producing a CI on the Sharpe of the
   candidate, the null, and — **paired** — the **delta**. *Paired = the same resample index draw applied
   jointly to the candidate and null series, then `delta = SR_cand − SR_null` per resample* (they ride the
   same beta/regime and are strongly positively correlated, so joint resampling tightens the delta CI;
   independent resampling would inflate it). Complements (does not replace) the existing CPCV path distribution.
3. **Trial register → true-count deflated Sharpe.** A pre-registered append-only register (e.g.
   `runs/trials.jsonl`) logging one entry per recipe×config evaluation (id, recipe, config hash, timestamp,
   Sharpe), **de-duplicated on config hash** so a repeated identical run (e.g. the `beta_null` self-check)
   doesn't inflate the count. The deflated Sharpe (Bailey–López de Prado, extending the Phase-1 `rank` /
   `stats.deflated_sharpe`) consumes the **cumulative trial Sharpe distribution** — both the count *and*
   the cross-trial dispersion `var(SR_trials)` that `expected_max_sharpe` needs — read across all
   invocations, not the count alone. This iteration registers the first trials, establishing the
   distribution from #1; the report carries a one-line honesty note that mixing structurally different
   recipes makes the dispersion estimate heterogeneous.

## Data flow

`klines (amount) → offline liquidity-rank → monthly top-10 PIT universe schedule → beta_null recipe →
VolWeightedRegimeStrategy backtest (per stress window/seed) → per-window Sharpe + return series →
(a) paired delta-vs-null, (b) stationary-bootstrap CIs on candidate/null/delta, (c) trial-register append
→ deflated Sharpe on the true cumulative count → stress report.`

## Validation / methodology

- "Edge beyond beta" = **delta-vs-null** and its bootstrap CI, reported every run (orientation §5.1).
- CPCV stays primary for the path distribution; the stationary bootstrap adds a **sampling / dependence-stress
  CI** it doesn't give. A block bootstrap resamples the *observed* return path, so it quantifies sampling
  uncertainty *within* the realized regime mix — it **mitigates, does not cure, the single-regime problem**
  (it cannot manufacture unseen regimes). Say so in the report; don't let the CI imply OOD-regime coverage.
- The null's measured OOS Sharpe + its bootstrap CI is **recorded once as the canonical yardstick**.

## Success criteria (done = observable)

- `beta_null` resolves, runs end-to-end through `stress`, and its OOS Sharpe + bootstrap CI are recorded
  as the yardstick (with the realized monthly universe membership logged).
- `zcrypto stress --recipe X` emits, for any X: per-window + across-window **delta-vs-null**, **bootstrap
  CIs** (candidate / null / delta), and a **deflated Sharpe on the true cumulative trial distribution
  (count + dispersion)**.
- The trial register exists and is appended to; the self-check (`beta_null` vs `beta_null` ≈ 0 delta) passes.
- Tests green; ruff clean.

## Testing (TDD)

- **`stationary_bootstrap_ci`** — unit: on iid normal returns the bootstrap-implied SE ≈ the analytic
  Sharpe SE (Lo 2002, ~√((1 + SR²/2)/n)); a block-correlated series widens it vs iid (≥1000 resamples;
  sanity, not exact).
- **delta-vs-null** — on a synthetic candidate/null pair with a known gap, the delta + its sign/CI match,
  and the **paired** CI is **tighter** than an independent-resample CI (guards against resampling the two
  series independently).
- **trial register** — append + cumulative-count; deflated Sharpe uses the cumulative count (not per-run).
- **liquidity universe schedule** — deterministic top-10 from a synthetic `amount` panel; PIT eligibility
  respected (a name listed late can't appear early); reproducible across runs.
- **`beta_null` drift-guard** — config equals the pre-registered rule (universe rule, gate, weighting,
  costs), mirroring the Phase-1 recipe drift-guards.
- Harness integration: a small fixture `stress --recipe beta_null --null beta_null` → ~0 delta, finite CIs.

## Risks / notes

- **The dynamic liquidity universe is the only notable new engineering** (everything else reuses the
  existing strategy + harness). The dynamic liquidity rule is the **committed pre-registration** (the
  static `_MAJORS` list was considered and rejected as a hand-pick, not a rule — decisions log iter-034);
  this note exists only to make the added engineering explicit, the one scope/effort item to confirm at
  the review gate.
- N=10 and the 200d/inverse-vol params are **pre-registered, not tuned**; the spec is the registration.
- Single-regime fragility persists (orientation §7) — Stage 0 makes uncertainty *visible*, it does not
  remove it.

## Closeout tasks (authored at closeout, not now)

- `README.md` Usage: document the new `--null` option on `stress` (and `experiment` if wired) — see
  `.claude/rules/readme-usage.md`.
- `docs/iterations-history.md`: append the **iter-34** entry (what landed: `beta_null`, the liquidity
  universe schedule, the three harness upgrades, the recorded null yardstick + its CI).
- Confirm the `.tmp/decisions.md` iter-034 entries are reflected.
