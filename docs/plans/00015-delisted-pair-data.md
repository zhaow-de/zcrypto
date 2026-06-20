# Survivorship-free delisted-pair data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Acquire the curated blown-up top-25-ever USDT majors into the dataset (via the *existing* `download`, since Binance keeps delisted symbols as `BREAK`) so the panel is survivorship-free; confirm `verify` reports them; rename `delist`→`drop`. Data-only; advances `T0005` → `partial`.

**Architecture:** The RECON established that delisted majors stay in `exchangeInfo` as `status="BREAK"` and the existing non-`TRADING` discovery fetches them archive-only — so no *not-in-`exchangeInfo`* change. The one enhancement needed surfaced from the real acquisition: the survivorship-critical blow-ups were trading-*halted* mid-collapse (FTT 2022-11-16, FTX), leaving interior 404 gaps the strict download rejects. The iteration is: (1) `delist`→`drop` rename; (2) `verify` confirmation for archive-only `TO<today` pairs; (3) an opt-in **`--allow-interior-gaps`** flag that NaN-fills interior 404s (reusing `rename`'s synthetic-NaN), default off so regular `download` stays strict; (4) a closeout that acquires the curated majors via `download … --allow-interior-gaps` and records coverage.

**Tech Stack:** Python 3.12, uv, pandas, pytest, Typer + `CliRunner`, ruff (line length 132). Data source: `data.binance.vision` (no qlib/redis in the data layer).

## Global Constraints

- **Regular `download`/`backfill` stay byte-identical** — the interior-gap tolerance is **opt-in (`--allow-interior-gaps`, default off)**; with the flag off, an interior 404 is still a hard error, exactly as today. The existing `TRADING`/`BREAK` discovery is reused for range-finding.
- **`drop` (ex-`delist`) delete-mechanics are unchanged** — only the command/function name + help text change; **no `!`, no major bump** (plain `refactor(data): …`), no back-compat alias.
- **No experiment/recipe/universe change** — the acquired majors sit in the dataset for a future iteration; no recipe's `universe` tuple changes here.
- ruff clean; data tests use `tests/data_fixtures.py::FakeSource` (no network); each commit gets a subagent `Reviewed-by:` before push.

## File structure

```
cli/data/
├── command.py     # MODIFY: rename `delist` command → `drop` (+ help reframe as pair-removal).
├── pipeline.py    # MODIFY: rename delist_pipeline → drop_pipeline (mechanics unchanged).
└── verify.py      # MODIFY (only if a test shows it's needed): accept + report archive-only pairs with TO < today.
tests/
├── test_data_delist.py   # RENAME → test_data_drop.py: same delete-mechanics assertions, delist→drop.
└── test_data_verify.py   # EXTEND: an archive-only (TO<today) pair passes verify + is reported.
README.md                 # MODIFY: Usage — delisted (BREAK/archive-only) majors in the dataset; delist→drop rename.
docs/open-topics/…        # MODIFY (closeout): T0005 → partial; note T0007 data-enabled.
docs/iterations-history.md# MODIFY (closeout): iter-16 entry.
```

---

## Task 1: Rename `delist` → `drop`

**Files:** Modify `cli/data/command.py` (`@data_app.command("delist")` / `delist_cmd` → `drop`), `cli/data/pipeline.py` (`delist_pipeline` → `drop_pipeline` + its import in `command.py`); Rename `tests/test_data_delist.py` → `tests/test_data_drop.py`; Modify `README.md`.

**Design:** Pure rename — the delete mechanics (`rmtree` + conditional calendar shrink) are unchanged. The command verb, function name, help text, echo strings, and tests change; no back-compat alias.

- [ ] **Step 1: Update tests first** — rename `tests/test_data_delist.py` → `tests/test_data_drop.py`; change the invoked command `"delist"` → `"drop"` and `delist_pipeline` → `drop_pipeline` references; the assertions (delete mechanics) are unchanged.
- [ ] **Step 2: Run — expect FAIL** (`drop` command / `drop_pipeline` don't exist yet): `uv run pytest tests/test_data_drop.py -q`.
- [ ] **Step 3: Implement** the rename: `pipeline.py` `delist_pipeline` → `drop_pipeline`; `command.py` import + `@data_app.command("drop")` + `drop_cmd` + help/echo text reframed as "remove a pair from the dataset" (drop the "delisting" framing); update `README.md` Usage (the `zcrypto data delist` subsection → `drop`, reframed as pair-removal, not market-delisting).
- [ ] **Step 4: Run — expect PASS + ruff** (`uv run pytest tests/test_data_drop.py -q`; `git grep -n 'delist' cli/` returns nothing — no stray identifiers).
- [ ] **Step 5: Commit** — `refactor(data): rename delist command to drop` (no `!`; + `Co-Authored-By: Claude Opus 4.8`).

---

## Task 2: `verify` accepts + reports archive-only delisted pairs

**Files:** Modify `cli/data/verify.py` (only if the test shows it's needed); Test `tests/test_data_verify.py`.

**Design:** A delisted/`BREAK` pair has `TO < today` and no recent data. `verify_dataset` must treat this as valid (its absence from the recent calendar is expected, covered by survivors — the interior-gap completeness check keys on whole-calendar coverage by *any* pair) and **report** the pair's range as coverage. This is likely already true for archive-only pairs, but today's 19 are all `TRADING`, so it may be untested — Step 1's test confirms it; implement only if it fails.

- [ ] **Step 1: Failing/confirming test** `tests/test_data_verify.py` (FakeSource): a dataset with a delisted pair (`TO < today`, e.g. ends 2022) plus survivors covering to ~today → `verify_dataset(...).ok` is True, and the report lists the delisted pair's range; a corrupt delisted bin still fails. Mirror the existing verify-test fixtures.
- [ ] **Step 2: Run** `uv run pytest tests/test_data_verify.py -q`. If it PASSES, verify already handles it — keep the test as a regression guard, note it, skip Steps 3. If it FAILS, proceed.
- [ ] **Step 3: Implement** (only if Step 2 failed) the minimal acceptance/report change in `verify.py`.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `test(data): verify accepts and reports archive-only delisted pairs` (or `feat(data): …` if a code change was needed).

---

## Task 3: `--allow-interior-gaps` download flag (interior 404 → NaN suspension)

**Files:** Modify `cli/data/command.py` (add the flag to `download`), `cli/data/pipeline.py` (thread it into the fetch; NaN-fill an interior 404 when set); Test `tests/test_data_pipeline.py`.

**Design:** A `--allow-interior-gaps` flag (default `False`) on `zcrypto data download`, threaded into `download_pipeline` + the fetch. Flag **off** (default): an interior 404 (a date *within* a pair's resolved `[from, to]`) is a hard error — exactly as today. Flag **on**: that date becomes a **NaN suspension row** (reuse the synthetic-NaN mechanic `rename` uses — `_FIELD_SYNTH` / the suspension row), and each gap day is logged as a **WARNING**. Regular `download`/`backfill` (flag off) are byte-identical.

- [ ] **Step 1: Failing tests** `tests/test_data_pipeline.py` (FakeSource — a pair whose `exists_kline` is True over a range EXCEPT one interior date that 404s):
  - WITH `allow_interior_gaps=True`: `download_pipeline` writes the pair over its full `[from, to]` with a NaN row at the gap date (`read_bin` shows NaN there) + a warning is logged; the pair is otherwise complete.
  - WITHOUT the flag (default): the same interior 404 raises the existing hard error (regular download unchanged).
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** — add `--allow-interior-gaps` to `command.py`'s `download` (default False); thread `allow_interior_gaps: bool = False` through `download_pipeline` → the fetch (`_fetch_one_date` / `_fetch_all_concurrent`); when set, an interior 404 within `[from, to]` yields a synthetic NaN row (reuse the rename synth-NaN helper) + a per-gap `logger.warning`. RECON: confirm where the fetch raises on a 404 + the rename synth-NaN helper to reuse.
- [ ] **Step 4: Run — expect PASS + ruff** (the existing pipeline tests stay green — flag-off behavior unchanged).
- [ ] **Step 5: Commit** — `feat(data): --allow-interior-gaps download flag (interior 404 → NaN suspension)`.

---

## Task 4: Closeout — acquire the real delisted majors + docs

**Files:** real `./data` (acquire); Modify `docs/open-topics/T0005-point-in-time-universe.md` + `docs/open-topics/README.md`; `README.md` (if not fully covered in Tasks 1/3); `docs/iterations-history.md`.

- [ ] **Step 1: Finalize the curated list + acquire (with the flag).** The cut is the spec's RECON set, FTT included now: `FTTUSDT, WAVESUSDT, DASHUSDT, ZECUSDT, QTUMUSDT, OMGUSDT, XEMUSDT, BTGUSDT, NANOUSDT, ICXUSDT` (Terra `LUNC/USTC` deferred — symbol-reuse). They're already in `data/pairs.txt` (the augmented universe). Run `uv run zcrypto data download data/pairs.txt --allow-interior-gaps` against the real `./data` — `TRADING` targets get full history (FTT's 2022-11-16 halt → NaN), `BREAK` targets fetch archive-only over their real range. Record which acquired + each one's `[listing, delisting]` range + any NaN gap days.
- [ ] **Step 2: Verify coverage.** `uv run zcrypto data verify` → confirm each acquired delisted major is reported with its real range (the "data ready" evidence); confirm no `problems`.
- [ ] **Step 3: Flip `T0005` → `partial`** — front-matter `open → partial`; add `## Done so far` (the data substrate: the curated delisted majors acquired with real ranges; the RECON that Binance keeps delisted symbols as `BREAK`; the `delist`→`drop` rename; iter-16 / spec `00015`); trim `## Suggested next steps` to the experiment-side remainder (expand `recipe.universe` to PIT membership; delisting-loss = liquidate-at-last-close; re-measure PIT vs survivor → resolved). Move its bullet `## Open → ## Partially done` in `docs/open-topics/README.md`; note `T0007`'s LUNA/FTX pass is now data-enabled.
- [ ] **Step 4: README + iterations-history.** README Usage: the dataset can include delisted (`BREAK`/archive-only) majors; the `delist`→`drop` rename (land here if Task 1 didn't fully cover it; mdformat owns the TOC). iter-16 iterations-history entry: the RECON (Binance keeps delisted as `BREAK`; the not-in-`exchangeInfo` enhancement was scoped out per YAGNI), the curated delisted majors acquired (with the real coverage ranges), the `verify` confirmation, the `delist`→`drop` rename, `T0005` → partial, `T0007` data-enabled.
- [ ] **Step 5: Commit** — `docs(data): iter-16 closeout — delisted-major coverage, T0005 partial, iterations-history`.

---

## Self-review

- **Spec coverage:** `delist`→`drop` rename, no `!` (Task 1) ✓; `verify` accepts/reports archive-only TO<today (Task 2) ✓; `--allow-interior-gaps` flag, default off, interior 404 → NaN, regular download byte-identical (Task 3) ✓; acquire curated majors via `download … --allow-interior-gaps` + T0005→partial + T0007 note + README + iterations-history (Task 4) ✓; data-only (no recipe/universe/delisting-loss/re-measure) ✓; not-in-`exchangeInfo` enhancement dropped per RECON/YAGNI ✓.
- **Type consistency:** `drop_pipeline` (ex-`delist_pipeline`) signature unchanged; `download_pipeline` gains `allow_interior_gaps: bool = False` (default preserves today's behavior); the fetch reuses the existing rename synth-NaN helper.
- **Risk flags:** Task 2 was a no-op (verify already handles archive-only — done). The interior-gap flag (Task 3) is the iteration's real code change — its key invariant is **flag-off = byte-identical** (a test asserts the same interior 404 still hard-errors without the flag). Task 4 acquisition hits the live archive (the FTT halt-gap is the known case; others surfaced during the real run are NaN-filled by the flag).
