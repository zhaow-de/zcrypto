# aggTrades sample — execution-realism data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build a first-class, reusable aggTrades fetcher in `cli/data` and acquire a bounded, liquidity-spanning sample into the raw-archive mirror (not the qlib dataset). Data-only; advances `T0004` → `partial`.

**Architecture:** A new `zcrypto data aggtrades PAIRS_FILE --from --to` subcommand fetches `data.binance.vision/spot/daily/aggTrades/<SYMBOL>/…` zips, sha256-validates them, and stores them in the mirror at `<backup-dir>/raw/spot/daily/aggTrades/<SYMBOL>/<YYYY>/…` (the `/<year>/` partition injected exactly as `mirror_path`/`funding_mirror_path` do). aggTrades is tick-level — it never enters the qlib `data-dir`; the future `T0004` calibration reads the raw zips. **DRY is a first-class goal:** atomic logic shared with `data download` is reused directly or extracted into a shared helper — never copy-pasted.

**Tech Stack:** Python 3.12, uv, urllib3, pytest, Typer + `CliRunner`, ruff (line length 132). Source: `data.binance.vision`.

## Global Constraints

- **DRY / reuse over copy-paste** (the binding directive for this iteration — see the Reuse Map). Where logic overlaps `data download`, reuse the generic atomic directly, or extract a shared helper behavior-preservingly; do not duplicate.
- **The qlib `data-dir` is untouched** — aggTrades lives only in the mirror (`<backup-dir>/raw`). No dataset/`index.json`/calendar/instruments change.
- **No parsing-into-trades, no calibration, no backtest wiring** — light validation only (sha256 + extractable). `T0004` → `partial`.
- ruff clean; data tests use `tests/data_fixtures.py::FakeSource` (no network); each commit gets a subagent `Reviewed-by:` before push.

## Reuse Map (DRY — read before implementing)

| Atom | Disposition |
|---|---|
| `binance._retryable_request` (HTTP GET + retry), `binance._pool`, `HttpStatusError` | **Reuse directly** — aggTrades fetch calls it with its own URL. |
| `binance.parse_checksum_file` (`.CHECKSUM` → sha256 hex) | **Reuse directly.** |
| `mirror.read_zip` / `mirror.save_zip` (path-based) | **Reuse directly** (with `aggtrades_mirror_path`). |
| `kline_archive_parts` / `kline_zip_url` / `kline_checksum_url`; `mirror.mirror_path`/`funding_mirror_path` | **Mirror the pattern** — add `aggtrades_archive_parts`/`aggtrades_zip_url`/`aggtrades_checksum_url` + `aggtrades_mirror_path` (parallel, single-source-of-truth layout). |
| `pipeline._fetch_one_date`'s **fetch-zip + fetch-checksum + sha256-validate** core | **EXTRACT** a shared `fetch_checksummed_zip(...)` (behavior-preserving) used by BOTH download (→ `parse_kline_zip`) and aggTrades (→ `validate_aggtrades_zip`). The divergent part (parse vs light-validate, and the integrity-gate-before-save when the checksum is absent) stays in each caller. |
| `pipeline._fetch_all_concurrent` (ThreadPool + progress logging) | **Reuse the concurrency/progress pattern** — generalize a `(symbol,date)`-work runner if clean; else a focused aggTrades concurrent loop calling the shared fetch atomic. Do NOT copy the kline-specific parse/merge. |
| `download_cmd` pairs-file read + `--from/--to/--backup-dir` + dry-run | **Reuse** the existing pairs-file reader + arg conventions; extract a tiny shared arg helper only if it reads clean. |

## File structure

```
cli/data/
├── binance.py     # MODIFY: aggtrades_archive_parts/zip_url/checksum_url (parallel to kline_*); Source.fetch_aggtrades_archive/fetch_aggtrades_checksum (reuse _retryable_request); EXTRACT fetch_checksummed_zip (shared with download).
├── mirror.py      # MODIFY: aggtrades_mirror_path(root, symbol, date) = root/<rel_dir>/<YYYY>/<name> via aggtrades_archive_parts (mirror mirror_path/funding_mirror_path).
├── aggtrades.py   # NEW: validate_aggtrades_zip (sha256-validated upstream; here: extracts to exactly one CSV — light, NO full row parse) + the sample-fetch orchestration (fetch→validate→mirror→manifest, idempotent).
├── pipeline.py    # MODIFY: refactor _fetch_one_date to call the extracted fetch_checksummed_zip (behavior-preserving).
└── command.py     # MODIFY: add `zcrypto data aggtrades PAIRS_FILE --from --to [--backup-dir] [--dry-run]` (reuse pairs-file read + arg conventions from download_cmd).
tests/
├── test_data_aggtrades.py   # NEW: archive-parts/URL + mirror /<year>/ path; validate (extractable, missing-checksum warn); FakeSource fetch→mirror; manifest; idempotent re-run.
├── test_data_pipeline.py    # EXTEND: the extracted fetch_checksummed_zip (sha256 pass/fail/missing); download path unchanged-green.
└── test_data_command.py     # EXTEND: `data aggtrades` arg parsing + dry-run.
README.md                    # MODIFY: Usage — the `zcrypto data aggtrades` subcommand (a bounded execution-calibration sample; raw-archive store, not the dataset).
```

---

## Task 1: aggTrades fetch primitives + mirror path (mirror the kline pattern)

**Files:** Modify `cli/data/binance.py`, `cli/data/mirror.py`, `tests/data_fixtures.py`; Test `tests/test_data_aggtrades.py`.

**Interfaces (produces):** `aggtrades_archive_parts(symbol, date) -> (rel_dir, name)`, `aggtrades_zip_url`/`aggtrades_checksum_url`, `Source.fetch_aggtrades_archive(symbol, date) -> bytes`/`fetch_aggtrades_checksum(symbol, date) -> str|None`, `mirror.aggtrades_mirror_path(root, symbol, date) -> Path`.

- [ ] **Step 1: Failing tests** — `aggtrades_archive_parts` → `("spot/daily/aggTrades/BTCUSDT", "BTCUSDT-aggTrades-2025-03-03.zip")` (no interval, unlike klines); `aggtrades_zip_url` is `BASE_URL/data/...`; `aggtrades_mirror_path(root, "BTCUSDT", date(2025,3,3))` → `root/spot/daily/aggTrades/BTCUSDT/2025/BTCUSDT-aggTrades-2025-03-03.zip` (the `/<year>/`); `FakeSource.fetch_aggtrades_archive` returns registered bytes.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the URL builders (mirror `kline_archive_parts`/`kline_zip_url`; path `spot/daily/aggTrades/<SYMBOL>` — no interval); `Source.fetch_aggtrades_archive`/`fetch_aggtrades_checksum` on the Protocol + `BinanceSource` (**reuse `_retryable_request`**, 404→None like `fetch_kline_checksum`); `aggtrades_mirror_path` (reuse `aggtrades_archive_parts` + `/str(date.year)/`, exactly like `mirror_path`); `FakeSource.fetch_aggtrades_archive`/`add_aggtrades`.
- [ ] **Step 4: Run — expect PASS + ruff.**
- [ ] **Step 5: Commit** — `feat(data): add aggTrades fetch primitives + year-partitioned mirror path` (+ `Co-Authored-By: Claude Opus 4.8`).

---

## Task 2: Extract the shared fetch+checksum atomic (DRY) + the light aggTrades validator

**Files:** Modify `cli/data/binance.py` (or `pipeline.py` — wherever the extracted helper reads cleanest), `cli/data/pipeline.py` (refactor `_fetch_one_date`); Create `cli/data/aggtrades.py`; Test `tests/test_data_pipeline.py`, `tests/test_data_aggtrades.py`.

**Interfaces (produces):** `fetch_checksummed_zip(fetch_zip_fn, fetch_checksum_fn) -> tuple[bytes, bool]` (bytes + `checksum_validated`); `aggtrades.validate_aggtrades_zip(raw: bytes) -> None` (raises on a non-extractable / multi-CSV zip).

- [ ] **Step 1: Failing tests** — (a) `fetch_checksummed_zip`: with a matching checksum → `(bytes, True)`; sha256 mismatch → raises; absent checksum (`None`) → `(bytes, False)` (caller gates). (b) `validate_aggtrades_zip`: a valid single-CSV zip passes; a corrupt/empty zip raises. (c) A regression assertion that `_fetch_one_date` still behaves identically (reuse an existing pipeline test).
- [ ] **Step 2: Run — expect FAIL** (the new tests).
- [ ] **Step 3: Implement** — extract `fetch_checksummed_zip` from `_fetch_one_date`'s fetch-zip + fetch-checksum + sha256-compare core; refactor `_fetch_one_date` to call it then `parse_kline_zip` (the missing-checksum→parse-is-the-gate and save-after-gate logic stays in `_fetch_one_date`). Add `aggtrades.validate_aggtrades_zip` (zipfile: extracts to exactly one CSV; no row parse). **Behavior-preserving:** the full existing `tests/test_data_pipeline.py` + `test_data_e2e.py` must stay green.
- [ ] **Step 4: Run — expect PASS + ruff** (new tests + the whole data suite green — download unchanged).
- [ ] **Step 5: Commit** — `refactor(data): extract shared fetch_checksummed_zip; add aggTrades zip validator`.

---

## Task 3: `zcrypto data aggtrades` subcommand — sample fetch + manifest

**Files:** Modify `cli/data/aggtrades.py` (the orchestration), `cli/data/command.py`; Modify `README.md`; Test `tests/test_data_aggtrades.py`, `tests/test_data_command.py`.

**Design:** `fetch_aggtrades_sample(paths, source, pairs, from, to) -> manifest`: for each (pair, date) over `[from, to]`, mirror-hit → skip (idempotent); miss → `fetch_checksummed_zip` (Task 2) → if not checksum-validated, `validate_aggtrades_zip` as the integrity gate → `mirror.save_zip(aggtrades_mirror_path(...))`. Reuse the `_fetch_all_concurrent` concurrency/progress pattern (generalized or a focused loop — no kline-specific copy). Write `aggtrades-manifest.json` (pairs, `[from,to]`, per-pair fetched dates + bytes) in the mirror's aggTrades root.

- [ ] **Step 1: Failing tests** (FakeSource): `data aggtrades` fetches the listed pairs over the window → zips land at the `/<year>/` mirror paths; a re-run is idempotent (already-present zips skipped, 0 re-fetched); the manifest records pairs/window/bytes; `--dry-run` previews without fetching.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `fetch_aggtrades_sample` + the `aggtrades` Typer command (reuse `download_cmd`'s pairs-file reader + `--from/--to/--backup-dir/--dry-run` conventions); update `README.md` Usage (the subcommand — purpose: a bounded execution-calibration sample stored in the raw mirror, not the qlib dataset).
- [ ] **Step 4: Run — expect PASS + ruff** (`uv run pytest tests/test_data_aggtrades.py tests/test_data_command.py -q`).
- [ ] **Step 5: Commit** — `feat(data): add `zcrypto data aggtrades` subcommand (bounded sample + manifest)`.

---

## Task 4: Closeout — fetch the real sample + docs

**Files:** real mirror (`<backup-dir>/raw`); Modify `docs/open-topics/T0004-execution-slippage-fills.md` + `docs/open-topics/README.md`; `README.md` (if not covered in Task 3); `docs/iterations-history.md`.

- [ ] **Step 1: Finalize the sample + fetch.** Cut: `BTCUSDT`/`ETHUSDT` (deep), `SOLUSDT` (high-mid), `LINKUSDT`/`ATOMUSDT` (mid), `PEPEUSDT` (thin) — finalize the ~5-6; window ≈ 3 months in 2024-25 covering a calm + a volatile stretch (post-PEPE-listing). Run `uv run zcrypto data aggtrades <pairs> --from <D1> --to <D2>` against the real mirror; record the manifest (pairs × window × total bytes ≈ ~10-15 GB) as the "data ready" evidence; confirm an idempotent re-run writes nothing.
- [ ] **Step 2: Flip `T0004` → `partial`** — front-matter `open → partial`; `## Done so far` (the reusable aggTrades fetcher + the bounded liquidity-spanning sample in the mirror; the manifest; iter-17 / spec `00016`); trim `## Suggested next steps` to the calibration + application remainder (parse the sample; size-scaled slippage curve + maker-fill probability; wire into `exchange_kwargs`; re-measure vs the 12-bps baseline → resolved) + the separable data-free parametric term. Move its bullet `## Open → ## Partially done` in `docs/open-topics/README.md`.
- [ ] **Step 3: README + iterations-history.** README Usage: the `data aggtrades` subcommand (land here if Task 3 didn't fully cover it; mdformat owns the TOC). iter-17 iterations-history entry: the reusable fetcher (+ the shared `fetch_checksummed_zip` extraction — DRY with download), the year-partitioned aggTrades mirror, the `data aggtrades` subcommand + manifest, the real bounded-sample coverage, `T0004` → partial.
- [ ] **Step 4: Commit** — `docs(data): iter-17 closeout — aggTrades sample, T0004 partial, iterations-history`.

---

## Self-review

- **Spec coverage:** reusable fetcher mirroring klines (Task 1) ✓; raw-archive mirror storage with `/<year>/` (Task 1) ✓; light validation, no full parse (Task 2) ✓; dedicated `data aggtrades` subcommand + manifest, idempotent (Task 3) ✓; bounded liquidity-spanning sample acquired (Task 4) ✓; `T0004` → partial, calibration/application deferred (Task 4) ✓; qlib data-dir untouched ✓.
- **DRY:** the Reuse Map is the spec of this; the one genuine extraction (`fetch_checksummed_zip`) is its own behavior-preserving task (Task 2) with a download-unchanged regression gate; everything else reuses generic atoms directly or mirrors the established builder pattern — no copy-paste.
- **Type consistency:** `aggtrades_archive_parts(symbol, date)` (no interval, unlike `kline_archive_parts(symbol, interval, date)`); `aggtrades_mirror_path(root, symbol, date)`; `fetch_checksummed_zip(fetch_zip_fn, fetch_checksum_fn) -> (bytes, bool)`; `validate_aggtrades_zip(bytes) -> None` — consistent across tasks.
- **Risk flags:** Task 2's extraction touches `download`'s hot path — the binding guard is the full data suite staying green (download byte-identical). Task 4 hits the live archive (~10-15 GB, minutes-to-tens-of-minutes) — backgroundable; idempotent so resumable.
