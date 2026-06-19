# 00009 — Honest survivorship framing for `zcrypto experiment`

- **Date:** 2026-06-18
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-10
- **Scope:** Surface a **survivorship caveat** in the experiment's outputs
  (`run_meta.json`, `report.html`, stdout) so results are read with the right
  prior, and **re-scope open-topic `T0005`** to reflect the data-acquisition
  reality. This is *honest framing only* — **no data, universe, or
  backtest-logic change**. The caveats surface is a concise **pointer** to the
  open-topic; `docs/open-topics/*` remains the single source of truth for the gap
  and its fix roadmap.
- **Depends on:** spec `00006` (experiment harness) and `00008` (CPCV).
- **Addresses (partially, by framing):** open-topic `T0005` (point-in-time
  universe / survivorship). The topic stays **open** — no fix step is performed.

## Goal

`zcrypto experiment` makes its survivorship limitation impossible to miss: every
run records and displays a short caveat — universe is today's surviving pairs,
historically-delisted pairs are absent, so both the CPCV path distribution and
the holdout are optimistically inflated — pointing readers to `T0005` for the
full analysis and fix roadmap. Nothing about the computation changes; only its
honesty does.

## Background & constraints

- **Why now / why only framing.** Investigation for `T0005` established: the
  **listing side of point-in-time is already handled** (qlib returns rows only
  where data exists, so a pair is never traded before it listed); the real bias
  is the **universe selection** (the 19 pairs are today's survivors) and the
  fact that we hold **zero delisted-pair data** while `zcrypto data delist`
  *deletes* a pair's history. A genuine fix therefore requires acquiring
  historically-delisted pairs' data + retaining delist dates + a delisting-loss
  model — a substantial follow-up. The user chose to **frame honestly now and
  defer the real fix**, so this iteration adds no false sense of progress.
- **Single source of truth (SSOT).** `docs/open-topics/*` is the canonical
  record of gaps and roadmap topics. The caveats surface must **reference** the
  topic, not restate its content — each caveat carries the topic id + a one-line
  summary; the full explanation and the fix roadmap live **only** in
  `docs/open-topics/T0005`.
- **Caveat scope = survivorship only.** The iter-9 methodology review flagged two
  CPCV-interpretation notes (the path band is *indicative* not a CI; the
  holdout-vs-path cue conflates overfitting with regime shift). They are now
  **captured in `T0002`** (its *Interpretation caveats* section); surfacing them
  via the caveats mechanism is **deferred to that topic's work**, so iter-10 stays
  survivorship-only (SSOT: surface only caveats that have a topic).
- **Repo rules unchanged.** README `## Usage` note + `docs/iterations-history.md`
  closeout + the `T0005` content update; branch + PR into `develop`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Scope | **Honest framing only** — no data, universe, or backtest-logic change. |
| SSOT | Caveats **reference** open-topics (topic id + one-line summary); no roadmap/gap text is duplicated outside `docs/open-topics/`. |
| Caveat set | **Survivorship only** (`T0005`). CPCV-interpretation caveats now tracked in `T0002` (*Interpretation caveats*); surfacing them is deferred to that topic's work (SSOT: surface only caveats that have a topic). |
| Surfaces | `run_meta.json` `caveats` list + `report.html` title subtitle marker + one stdout line. Present on **both** the default (CPCV) and `--quick` runs. |
| Wording home | A single small module `cli/experiment/caveats.py` so the text lives in exactly one place (avoids a `report.py` ↔ `command.py` import tangle). |
| `T0005` status | Stays **open** (no fix step done); its Findings/next-steps are sharpened to the reality. |

## Components

```
cli/experiment/
├── caveats.py    # NEW: EXPERIMENT_CAVEATS (list of {topic, summary}) + SURVIVORSHIP_MARKER (short string)
├── command.py    # MODIFY: run_meta["caveats"] = EXPERIMENT_CAVEATS; one stdout caveat line
└── report.py     # MODIFY: append SURVIVORSHIP_MARKER as a title subtitle
```

### `cli/experiment/caveats.py` (new)

```python
"""Run-time caveats surfaced in experiment outputs.

These are concise POINTERS to docs/open-topics/* (the single source of truth for
gaps and roadmap). Do not restate a topic's analysis or fix plan here — only a
one-line summary and the topic id a reader follows for the full picture.
"""

SURVIVORSHIP = {
    "topic": "T0005",
    "summary": (
        "universe is survivorship-biased — today's surviving pairs only; "
        "historically-delisted pairs are absent, so the CPCV paths and the holdout "
        "are optimistically inflated (listing dates are respected). "
        "See docs/open-topics/T0005-point-in-time-universe.md."
    ),
}

# All caveats applicable to an experiment run (extend as topics warrant).
EXPERIMENT_CAVEATS = [SURVIVORSHIP]

# Short marker for the report subtitle and the stdout line.
SURVIVORSHIP_MARKER = "survivorship-biased universe — see open-topic T0005"
```

### `run_meta.json`

Add one key to the existing manifest dict in `command.py`:

```jsonc
"caveats": [ { "topic": "T0005", "summary": "universe is survivorship-biased — …" } ]
```

A list (extensible) of `{topic, summary}` objects. Persisted in every bundle
(default and `--quick`).

### `report.html`

`build_report` appends the marker to the figure title as a subtitle, e.g.
`"<recipe>: 10,000 → XXXX USDT<br><sub>⚠ survivorship-biased universe — see open-topic T0005</sub>"`.
Always shown (3- and 4-panel).

### stdout

One line in the `command.py` summary (after the headline / metrics, both run
modes), built from the shared marker (`f"⚠ {SURVIVORSHIP_MARKER}"`):
`⚠ survivorship-biased universe — see open-topic T0005`. Keeping it derived from
`SURVIVORSHIP_MARKER` ensures the report subtitle and the stdout line never drift.

## SSOT & `T0005` re-scope

`docs/open-topics/T0005-point-in-time-universe.md` stays the canonical topic
(status **open**). Update it in this iteration (closeout) to:

- **Findings** — record the reality check: listing is already handled by data
  absence; the bias is the survivor-only universe; `zcrypto data delist` deletes
  history; the panel holds zero delisted-pair data; iter-10 added an honest
  caveat to the experiment outputs but changed no results.
- **Suggested next steps** — sharpen to the real roadmap: acquire historically
  delisted Binance USDT pairs (enumerate `data.binance.vision` for symbols whose
  archives end before today) → make `delist` retain-with-end-date (or keep a
  delisted registry) → build point-in-time membership over the expanded panel →
  add a delisting-loss assumption → re-measure PIT-vs-survivor baseline.

No roadmap or gap detail is copied into `caveats.py` or `run_meta.json` — those
only point here.

## Testing strategy

- **Report unit test** (no redis, `tests/test_experiment_report.py`): the figure
  title contains `SURVIVORSHIP_MARKER` (present for both `cv=None` and `cv` given).
- **Command tests** (redis-gated, `tests/test_experiment_command.py`): a default
  run's `run_meta.json` has a `caveats` list whose entry references topic `T0005`;
  the stdout contains the survivorship line; the **`--quick`** run also writes the
  `caveats` and prints the line (the caveat is run-mode-independent).
- **Caveats unit test** (no redis, new `tests/test_experiment_caveats.py`):
  `EXPERIMENT_CAVEATS` is a non-empty list of `{topic, summary}` and includes the
  `T0005` survivorship entry; `SURVIVORSHIP_MARKER` is non-empty.

## Out of scope (deferred → open-topic `T0005`)

- Acquiring historically-delisted pairs' data; `delist`-retain / a delisted
  registry; point-in-time membership over an expanded panel; a delisting-loss
  assumption; re-measuring PIT-vs-survivor. (All remain `T0005`'s open roadmap.)

## Closeout (executed at end of iteration, per the rules)

- README `## Usage` — a sentence that the experiment emits a survivorship caveat
  and `run_meta.json` records a `caveats` list.
- `docs/iterations-history.md` — the iter-10 entry.
- `docs/open-topics/T0005-point-in-time-universe.md` — the Findings/next-steps
  update above (topic stays open).

## References

- Open-topic: `docs/open-topics/T0005-point-in-time-universe.md` (SSOT).
- Prereqs: spec `00006` (experiment), `00008` (CPCV).
- Research roadmap: `docs/research/01.binance-eea-spot-quant.md` §3, §12
  (survivorship bias).
