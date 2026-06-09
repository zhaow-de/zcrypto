# 00004 — `zcrypto data`: backfill, delist, rename (and status-aware download)

- **Date:** 2026-06-09
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-5
- **Scope:** Complete the `zcrypto data` subcommand suite by adding
  `backfill`, `delist`, `rename`. Refactor the iter-4 commit-discipline into
  a shared mutation harness. Make `download` and `backfill` status-aware
  (handle delisted pairs gracefully) and let `rename` synthesize a small
  zero-volume bridge across the gap between a delisted ticker and its
  successor.

## Goal

Reach a state where the `zcrypto data` suite handles the full lifecycle of a
ready-made Qlib dataset against Binance spot klines:

- `download` and `backfill` accept pairs whose Binance `status` is no longer
  `TRADING` (`BREAK`, `HALT`, etc.), fetching the available historical archive
  and leaving the pair frozen.
- `delist` removes a pair cleanly, conditionally shrinking the master calendar
  if the removal exposes new edge dates that no remaining pair covers.
- `rename` re-labels an existing pair under a new ticker — and, where the new
  ticker started trading later than the old one stopped, synthesizes a small
  zero-volume bridge so the dataset stays calendar-dense and analysis-friendly.
- Every mutating command shares one harness with the iter-4 atomic-commit and
  crash-recovery discipline. No-op invocations never write a snapshot file;
  `--dry-run` previews the plan without side effects.

## Background & constraints

- **Iter-4 baseline.** `cli/data/` carries `download`/`verify` plus
  infrastructure: snapshot+marker crash-recovery, atomic staging-then-swap
  commit, pre-flight `verify_dataset`, concurrent fetch
  (`CliConstants.FETCH_CONCURRENCY`), `_resolve_ranges` with right-edge
  reachability check, `find_first_available`. All preserved; iter-5 extends
  not rewrites.
- **Empirical findings re. delisted pairs (verified via live probes against
  Binance APIs):**
  - `exchangeInfo` retains delisted pairs with a non-`TRADING` status. For
    `MATICUSDT` today: `status="BREAK"`, `baseAsset="MATIC"`,
    `quoteAsset="USDT"`. So `validate_pairs_against_exchange` cannot rely on
    "in/out of exchangeInfo" as a delisted-pair signal; the **status field is
    the distinguisher**.
  - `data.binance.vision` keeps delisted history forever. `MATICUSDT` 1d zips
    return 200 OK from 2019-04-26 through 2024-09-10 then 404 from
    2024-09-11 onwards. `POLUSDT` 404s until 2024-09-12 then 200 from
    2024-09-13 onwards. Two-day gap with no data for either ticker.
- **Iter-4's "all pairs share one to-date" assumption is dropped.** Once
  delisted pairs are allowed in the index, different pairs naturally end at
  different days. `verify_dataset` already accommodates this (the per-pair
  date range is in `index.json`, not enforced uniform).
- **Reviewer-trailer convention.** Per
  `.claude/rules/commit-messages.md` (landed in PR #15), each commit carries
  its own `Reviewed-by:` trailer amended while still local; force-push on
  the feature branch is fine.
- **Repo rules unchanged.** README `## Usage` updated in the same change;
  `docs/iterations-history.md` entry as the closeout task; branch + PR per
  `branch-workflow.md` / `pull-requests.md`; open topics per
  `open-topics.md`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Iteration scope | `backfill` + `delist` + `rename` + status-aware extensions to `download` / `backfill`. All in one iteration. |
| Snapshot on no-op | No snapshot file written when nothing mutates — applies to all four mutators (download/backfill/delist/rename). Iter-4's download is brought in line as part of the harness refactor. |
| `--dry-run` semantics | Preview only. Skips recovery, runs pre-flight verify, computes the full plan, prints summary to stdout via `typer.echo`. No snapshot, no marker, no staging dir created. Errors out if a `.commit-in-progress` marker is present. |
| Calendar on delist | **Conditional shrink** — trim calendar edges if (and only if) the removed pair was the unique cover for the earliest or latest dates. Front-trim rewrites every remaining bin's start-index header; back-trim leaves headers untouched. |
| Delist refusals | Refuse on last-pair (would empty the dataset) and gap-creating (calendar union becomes non-contiguous). Operator's workaround: `rm -rf` for the former, manual reconciliation for the latter. |
| Confirmation discipline | No `--yes` flag. Mutations proceed by default (snapshot is the safety net). `--dry-run` is the speedbump for typo-prone invocations. |
| Status field as the gate | `validate_pairs_against_exchange` reads `status`. `TRADING` keeps iter-4 semantics. Non-`TRADING` → treat as historical archive: download fetches `[first_available, last_available]`; backfill silently skips. |
| Rename variants | Variant 1: only OLD in index — re-label + synthesize gap. Variant 2: both OLD and NEW in index — merge OLD's history into NEW's slot, synthesize gap, drop OLD's entry. Both share the same CLI and the same synthetic-fill semantics. |
| Synthetic-fill marker in index | **No** dedicated metadata field. Synthetic rows are valid zero-volume bars indistinguishable in content from real zero-volume days. Audit trail lives in logs + iterations-history. (Re-open if analyses need to mask synthetic days.) |
| Architectural shape | Extract a shared mutation harness `_execute_mutation(out_dir, cmd_name, plan_fn, apply_fn, *, dry_run)`. Refactor iter-4's `download_pipeline` to use it. |

## CLI surface

Three new subcommands registered on the existing `data_app`:

```
zcrypto data backfill OUT_DIR [--to YYYY-MM-DD] [--dry-run]
zcrypto data delist   OUT_DIR SYMBOL [--dry-run]
zcrypto data rename   OUT_DIR OLD_SYMBOL NEW_SYMBOL [--dry-run]
```

- `OUT_DIR` (all): mandatory; the existing dataset to mutate (or seed for a
  fresh download).
- `--to YYYY-MM-DD` (`backfill` only): right-edge date, default = yesterday
  UTC. Validated at parse time via the same regex + `dt.date.fromisoformat`
  pattern as iter-4. Must be `<= yesterday UTC`.
- `SYMBOL` / `OLD_SYMBOL` / `NEW_SYMBOL`: uppercase-normalized at parse time
  (matches iter-4's `download` pair-file handling).
- `--dry-run` (all three new + existing `download`/`backfill`): preview only.

Bare `zcrypto data` continues to print group help and exit (iter-4 behavior,
no change).

`--silent` is **not** propagated to mutating commands — silence is a `verify`
property only. Mutating commands always log their summary line.

## Architecture: the mutation harness

All four mutating commands (download/backfill/delist/rename) share one
private helper in `cli/data/pipeline.py`:

```python
def _execute_mutation(
    out_dir: Path,
    cmd_name: str,           # "download" | "backfill" | "delist" | "rename"
    plan_fn,                 # Path -> Plan  (read-only; computes what would change)
    apply_fn,                # (Path, Path, Plan) -> None  (writes new state into staging)
    *,
    dry_run: bool = False,
) -> None:
    ...
```

Each command supplies:

- `plan_fn(out_dir) -> Plan` — read-only inspection. Returns a per-command
  `Plan` dataclass with `is_noop: bool` and `dry_run_summary() -> str`. May
  hit the network (for backfill / rename / status-aware download — to read
  exchangeInfo and probe archive availability).
- `apply_fn(out_dir, staging, plan)` — writes the new dataset state into the
  staging directory. Pure-local I/O plus, where relevant, calls to
  `_fetch_all_concurrent` (download/backfill).

The harness performs, in this exact order:

1. `out_dir.mkdir(parents=True, exist_ok=True)`.
2. **Real run only**: `_recover_from_interrupted_commit(out_dir)`. Dry-run
   errors here if the `.commit-in-progress` marker is present
   (`PipelineError("commit-in-progress marker present; cannot dry-run until
   prior commit is recovered. Re-run without --dry-run to auto-recover.")`).
3. Pre-flight `verify_dataset(out_dir)`; abort with `PipelineError` if
   `ok=False` and not `is_empty`.
4. `plan = plan_fn(out_dir)`.
5. **No-op short-circuit**: if `plan.is_noop`, log
   `info: {cmd_name}: nothing to do` (or `typer.echo` under `--dry-run`) and
   return. **No snapshot, no marker, no staging dir.**
6. **Dry-run short-circuit**: if `dry_run`, `typer.echo(plan.dry_run_summary())`
   and return. **No snapshot, no marker, no staging dir.**
7. **Real run**: snapshot taken via `create_snapshot(out_dir, cmd_name)` —
   tar.gz named `<UTCstamp>-<cmd_name>.tar.gz` (replaces iter-4's hardcoded
   `"download"`). Marker written via `_write_commit_marker(out_dir,
   snapshot.name)`. Staging built via `apply_fn`. Post-verify on staging.
   Atomic commit via `_commit_staging`. Marker unlinked. Staging cleaned up
   via the existing `finally` discipline.

The four pipeline functions become thin closures around `_execute_mutation`:

```python
def download_pipeline(out_dir, pairs_file, interval, arg_from, arg_to,
                     source, *, dry_run=False):
    plan_fn = lambda d: _download_plan(d, pairs_file, interval,
                                       arg_from, arg_to, source)
    apply_fn = lambda d, s, p: _download_apply(d, s, p, source)
    _execute_mutation(out_dir, "download", plan_fn, apply_fn, dry_run=dry_run)

# backfill_pipeline / delist_pipeline / rename_pipeline analogously
```

Iter-4's `download_pipeline` is refactored to fit this shape — the meat
(resolve-ranges, fetch, build-staging) moves into `_download_plan` and
`_download_apply`; the discipline (recover, verify, commit) moves to the
harness. The 113 iter-4 tests are the regression net.

`_commit_staging` itself stays internally as in iter-4 (snapshot + marker +
moves + atomic index write + rollback on failure), with one signature
change: it accepts `cmd_name` so snapshot filenames reflect the command.

## Five design changes

### Change A — Status-aware `validate_pairs_against_exchange`

Iter-4's check: `symbol in exchangeInfo`. Iter-5: read `status` from the
exchangeInfo symbol entry. Classification:

- `status == "TRADING"` → iter-4 path: fetch up to `arg_to`.
- `status != "TRADING"` (`BREAK`, `HALT`, `END`, `AUCTION_MATCH`, …) → treat
  as **delisted historical pair**: fetch only what `data.binance.vision`
  holds; no extension beyond `last_available`.

The base/quote assets always come from exchangeInfo regardless of status.

Iter-4's `_resolve_ranges` now consumes the classification when computing
per-pair date ranges (see Changes C, D).

### Change B — `find_available_range`

New helper alongside iter-4's `find_first_available`:

```python
def find_available_range(
    source: Source,
    symbol: str,
    interval: str,
    lo: dt.date,
    hi: dt.date,
) -> tuple[dt.date, dt.date] | None:
    """Return (first_available, last_available) within [lo, hi], or None if
    no kline zip exists in that range. Uses two bounded binary searches:
    one downward for first_available, one upward for last_available."""
```

Used by `download` for delisted pairs (where the right edge isn't `arg_to`
but the archive's last day) and by `rename` for probing the new ticker's
first archive day.

### Change C — `data download` tolerates delisted pairs

If pairs.txt names a non-`TRADING` symbol:

1. `validate_pairs_against_exchange` records it with `status=<non-TRADING>`
   and the correct base/quote.
2. For each non-`TRADING` pair in `_resolve_ranges`'s new-pair branch:
   - `find_available_range(sym, interval, arg_from, arg_to)` → range
     `[first_available, last_available]`. None → `PipelineError`.
   - Per-pair plan uses `effective_to = last_available` (not `arg_to`).
3. The pair lands in the index with `to = last_available`. Calendar covers
   the union; verify accepts non-uniform `to` dates per-pair.
4. Logged at info level:
   `MATICUSDT: status=BREAK on Binance; fetching only historical archive
   [<first>..<last>], no extension possible.`

For `TRADING` pairs, iter-4 behavior is preserved unchanged: truncation
guard (`--to < calendar.to` → `PipelineError`), right-edge reachability
check (still actionable: points to `rename` / `delist`).

### Change D — `data backfill` silently skips delisted pairs

`_resolve_ranges` consults the status classification before probing
reachability:

- `TRADING` → existing reachability check. If reachable at `arg_to`, plan
  fetches `[index.to + 1, arg_to]`. If unreachable, the iter-4
  `PipelineError` still fires (this now narrowly covers archive lag or true
  outages, not the renamed/delisted case).
- non-`TRADING` → log
  `info: {sym}: status={status} on Binance; nothing to extend.`, skip the
  pair. **No** `PipelineError`. The dataset retains the pair frozen at its
  current `to`.

When every pair is skipped or otherwise empty-ranged, the harness's no-op
short-circuit fires — no snapshot written.

### Change E — `data rename` with two variants

The CLI is one shape; the apply step differs based on whether `NEW` already
exists in the index.

**Common pre-flight (both variants):**

1. Load index. Validate `OLD ∈ index`. If not → `PipelineError(f"{OLD} not
   in index; nothing to rename")`.
2. Validate `OLD != NEW`. If equal → `PipelineError("old_symbol equals
   new_symbol; no change requested")`.
3. Fetch Binance `exchangeInfo`. Look up `NEW`. If not present →
   `PipelineError(f"{NEW} not found on Binance (exchangeInfo); not a valid
   symbol")`.
4. Extract `new_base_asset`, `new_quote_asset` from exchangeInfo. Status
   field is **not** gated here — operator may rename even if NEW is also
   delisted (e.g. for naming hygiene on a fully-historical dataset).
5. Detect variant: `NEW ∈ index` → Variant 2 (merge); else → Variant 1
   (single rename + fill).
6. Determine `new_first` (the date the renamed pair's bin should pick up
   after the synthetic gap):
   - **Variant 1**:
     `find_available_range(NEW, interval, OLD.index.to + 1, yesterday_utc)`.
     `None` → `PipelineError(f"{NEW} has no daily archive available on
     data.binance.vision yet (likely too early after listing). Try again
     tomorrow.")`. Otherwise unpack `(new_first, _)`.
   - **Variant 2**: `new_first = NEW.index.from` (read from the index; no
     network probe needed — the operator already curated NEW's range when
     they downloaded it, and we honor it). Archive availability is implied
     by NEW being in the index.
7. Sanity check overlap: `new_first <= OLD.index.to` → `PipelineError(f"
   rename has overlapping data: OLD ends {OLD.index.to} but NEW starts
   {new_first}; manual resolution required")`. (Variant 2's typical case
   has `OLD.to + 1 <= NEW.from` so the check passes silently; the refusal
   catches an operator who explicitly downloaded NEW with a too-early
   `--from`.)
8. Compute `gap_dates = [OLD.index.to + 1 .. new_first - 1]` (inclusive
   both ends; may be empty).

**Variant 1 — single rename + fill (`NEW ∉ index`):**

Apply step:

- If `gap_dates == []`: copy `features/<old_lower>/` →
  `staging/features/<new_lower>/` byte-for-byte. Calendar unchanged.
- If `gap_dates != []`:
  - Read OLD's last close: the float32 at offset `4 + (rows-1)*4` of
    `features/<old_lower>/close.day.bin`.
  - For each of the 11 fields, append `len(gap_dates)` synthetic float32
    values to the renamed bin's content during the copy-into-staging step:
    - `open`, `high`, `low`, `close`, `vwap` → `synthetic_locked_ohlc`
      (OLD's last close, repeated).
    - `volume`, `amount`, `trades`, `taker_buy_base`,
      `taker_buy_amount` → `0.0`.
    - `factor` → `1.0` (matches the existing constant-factor invariant).
  - Calendar:
    `new_calendar = old_calendar ∪ gap_dates` (sorted, dedup). If other
    pairs' `to` already covers `gap_dates`, the calendar is unchanged;
    otherwise it grows. Bin start-index headers are **not** touched (no
    front-trim under rename).
- Update `instruments/all.txt`: the renamed pair's line changes from
  `OLD <from> <OLD.to>` → `NEW <from> <new_first - 1>`.
- Update `index.json`: pair entry's key/symbol → `NEW`;
  `base_asset = new_base_asset`; `quote_asset = new_quote_asset`;
  `intervals[*].to = new_first - 1`; per-field `sha256` and `size_bytes`
  recomputed (bin contents changed iff gap_dates non-empty);
  `header_start_index` unchanged; `files[*].path` rewritten from
  `features/<old_lower>/...` to `features/<new_lower>/...`.

**Variant 2 — merge two existing entries (`NEW ∈ index`):**

The "operator downloaded MATIC and POL separately, now wants one continuous
series" case.

Apply step:

- Read OLD's and NEW's existing bins (per field).
- Synthetic gap fill: same locked-OHLC / zero-volume strategy as Variant 1,
  for `gap_dates`.
- Concatenate per field: `OLD.bin → synthetic_gap → NEW.bin`. Write the
  result to `staging/features/<new_lower>/<field>.day.bin`.
- Compute the new pair range: `[min(OLD.from, NEW.from), NEW.to]`.
- Compute new bin `start_index`: position of `min(OLD.from, NEW.from)` in
  the new calendar (typically lower than NEW's old start_index, because
  NEW's bin now extends backward).
- Calendar:
  `new_calendar = old_calendar ∪ gap_dates ∪ OLD's range` (sorted, dedup).
  If OLD's range was already covered by other pairs, calendar may not grow.
- For every **other** pair (not OLD, not NEW): copy its `features/<sym>/`
  unchanged. **If new_calendar has a front-trim relative to old_calendar,
  rewrite every remaining bin's start-index header** (subtract front_trim).
  This is the same header-rewrite as `delist`. In the typical merge case
  (NEW gains older history, no calendar front-trim), no other-pair headers
  change.
- `instruments/all.txt`: OLD's line removed; NEW's line updated to the new
  range.
- `index.json`: OLD's entry removed; NEW's entry updated with the new
  range, new base/quote, recomputed file sha256/size/header.

Refusals beyond the common pre-flight: none specific to Variant 2 — the
overlap check in step 7 catches the "merge would double-count some dates"
case.

**Dry-run output (both variants)** is human-readable via `typer.echo`,
naming the rename, the variant, the gap days, the synthetic-fill row count,
the calendar effect, and the snapshot path the real run would take.

## Per-command behavior summary

### `backfill`

- **Pre-flight (harness)**: recover, verify (must pass, may be `is_empty`
  only if seeded later — but backfill on empty errors at plan step 1).
- **Plan**: load index (`PipelineError` if empty or none); fetch
  exchangeInfo; classify each pair by status; for `TRADING` pairs run
  reachability + range; for non-`TRADING` pairs skip with info log; build
  per-pair date lists. If every list is empty → `Plan.is_noop = True`.
- **Apply**: `_fetch_all_concurrent` (iter-4 unchanged) + per-pair gap
  check + `_build_staging`.

### `delist`

- **Pre-flight (harness)**: recover, verify.
- **Plan**: load index; validate `SYMBOL ∈ index`; compute remaining;
  refuse last-pair; compute new calendar bounds; refuse gap-creating;
  decide front-trim / back-trim / rewrite_headers. No-network.
- **Apply**: copy remaining pairs' `features/<sym>/` to staging; if
  rewrite_headers, edit each bin's header; write new calendar, new
  instruments, new index.

### `rename`

- See Change E. Variants 1 and 2 share the pre-flight; apply differs.

## Error handling & logging

The iter-4 error model carries forward unchanged, with these specifics for
the new commands and the harness:

| Category | Raised by | Operator sees |
|---|---|---|
| Pre-flight verify fails (not is_empty) | harness step 3 | `refusing to mutate <out_dir>: dataset is not in a verified state. Problems: [...]. Resolve manually (restore from .snapshots/, or remove the orphan files) before re-running.` |
| Dry-run + leftover `.commit-in-progress` marker | harness step 2 | `commit-in-progress marker present; cannot dry-run until prior commit is recovered. Re-run without --dry-run to auto-recover.` |
| Command refusal (per-command pre-flight) | each command's `plan_fn` | single-line message identifying symbol + reason + suggested next action (see Section "Change E" and "Per-command" tables). |
| Network failure in plan | exchangeInfo / `exists_kline` | `PipelineError(f"network error during pre-flight: {e}")` (wraps original via `from e`). |
| Network failure in fetch | `_fetch_all_concurrent` | iter-4: first failure cancels queued futures, propagates as `PipelineError(f"{sym} {date}: fetch failed: {e}")`. |
| Mid-commit failure | `_commit_staging` | iter-4 atomicity preserved (in-process rollback + on-kill marker-based recovery). |

**Logging convention** (unchanged from iter-4):

- `logger.info/warning/error` → structured JSONL logger (`-l logs.jsonl`).
  Runtime events: "fetching N zips for SYM", "skipped SYM (status=BREAK)",
  "snapshot saved at <path>", commit summary.
- `typer.echo` → stdout, human-readable. **Only** for `--dry-run` plan
  summaries and end-of-run success lines. Never routine runtime events.
- `typer.echo(..., err=True)` → stderr. CLI handler emits caught
  `PipelineError`s here, then exits 1.

**Snapshot on mutation only.** All four mutators short-circuit before the
harness's commit phase when the plan is no-op (download/backfill with all
ranges empty; delist with symbol-not-in-index error path; rename with
old==new error path). The commit-time snapshot is the only snapshot taken;
on commit failure the snapshot remains in `.snapshots/` as benign
disaster-recovery insurance (rolls out via the keep-7 rotation).

**Operational precondition for rename** (documented, not enforced): run
`data backfill` immediately before `data rename` so OLD's `index.to`
reflects OLD's last real trading day. Stale local `index.to` means the
synthetic fill silently covers dates when OLD was actually trading,
distorting analysis for those dates. One-line discipline; cheap to follow.

**Long-gap acknowledgment.** When the synthetic-fill range exceeds 7 days
(configurable as `CliConstants.RENAME_SYNTH_WARN_DAYS = 7`), the warning is
louder — verbatim text in the rename log line, urging dry-run-first.
Iter-5 does not refuse arbitrarily long gaps; some legitimate
delisting-and-relisting takes months.

**Single-writer assumption** carries forward from iter-4. Concurrent
invocations against the same `OUT_DIR` are not supported.

## Testing strategy

All behavior remains fully offline via `FakeSource` injection. Fixture
extensions in `tests/data_fixtures.py`:

- `FakeSource.add_pair(symbol, base, quote, *, status="TRADING")` — gain
  the `status` kwarg; the `exchange_info` stub returns it in the symbol
  dict.
- Existing `add_kline` / `exists_kline` / `fetch_kline_zip` /
  `fetch_kline_checksum` already model the archive-availability story
  correctly; `find_available_range` works against the same inventory.
- `CountingSource(FakeSource)` (iter-4) keeps working.

New / extended test files:

- `tests/test_data_backfill.py` — happy path, no-op idempotency (verify
  **no snapshot file written**), `--dry-run` (verify no snapshot, exact
  echo content), Change D (non-TRADING pair silently skipped, info log
  captured), preserved iter-4 right-edge error path for TRADING pairs.
- `tests/test_data_delist.py` — happy path (no calendar trim), front-trim
  (verify bin start-index headers updated and sha256 changed), back-trim
  (verify calendar shortened and headers untouched), refusal:
  not-in-index, last-pair, gap-creating, `--dry-run`.
- `tests/test_data_rename.py` — Variant 1 no gap; Variant 1 with gap
  (assert exact synthetic byte content for all 11 fields); Variant 2 merge
  (assert concatenated bin content + header recomputation); refusals: NEW
  not in exchangeInfo, NEW no archive yet, overlap; `--dry-run` for both
  variants.
- `tests/test_data_pipeline.py` — extensions: `find_available_range` (first
  found, last found, none in range); `validate_pairs_against_exchange`
  status routing (TRADING vs BREAK); mutation harness unit tests (no-op
  short-circuit verified by snapshot-file absence, dry-run short-circuit,
  marker-present-at-dry-run refusal, recovery happens before pre-flight
  on real runs).
- `tests/test_data_command.py` — CLI shape: `data backfill` / `delist` /
  `rename` print group/cmd help; `--dry-run` accepted on all three;
  positional args parsed; error path (`PipelineError` → stderr + exit 1).
- `tests/test_data_download.py` (new, splitting download-specific tests
  off from the catch-all pipeline file) — Change C: pairs.txt with one
  delisted symbol fetches the truncated `[first, last]` range; mixed
  TRADING + delisted produces non-uniform per-pair `to` dates; iter-4's
  truncation guard still fires for `--to < calendar.to` on TRADING pairs.

End-to-end scenarios (added to a new `tests/test_data_e2e.py` or appended
to `test_data_pipeline.py`):

1. **Fresh full history of a delisted/renamed asset.** pairs.txt with
   `MATICUSDT + POLUSDT`; one `data download` brings both in (Change C);
   `data rename MATICUSDT POLUSDT` runs Variant 2 merge; final dataset has
   POL with continuous history end-to-end.
2. **Ongoing dataset survives mid-window rename.** start with `MATICUSDT`
   in index extending to 2024-09-10; FakeSource simulates the BREAK
   status + POL archive availability; `data backfill` skips MATIC
   silently; `data rename` runs Variant 1 with 2-day gap; subsequent
   `data backfill` extends POL forward normally.
3. **Pure delisted snapshot.** pairs.txt with `MATICUSDT` only; download
   Change C; verify reports `ok`; subsequent `backfill` is a no-op
   (silently skips); dataset is a frozen historical archive.

**Regression discipline.** All 113 iter-4 tests must continue to pass. The
mutation-harness refactor is covered by the existing iter-4 download
suite. Iter-5 adds an expected ~40-60 new tests; target final count is
~155-170 passing.

**Coverage targets** unchanged from iter-4: no per-file thresholds. The
discipline is *every public surface has at least one happy-path test and
one refusal test*, validated at code-quality review.

## Out of scope (iter-6 fodder)

- Intervals other than `1d` (still validated and rejected at parse time as
  iter-4).
- Monthly-archive bulk fetcher optimization (decided dropped during
  iter-4; left documented here for context, not deferred).
- An explicit `synthetic_dates` field in `index.json` for downstream
  analysis to mask synthetic rows. Defer until a real analysis needs it;
  open-topic if it bites.
- Multi-writer / advisory-lock for concurrent invocations against one
  `OUT_DIR`.
- A `data prune` or `data wipe` command for clearing the dataset entirely.
  Operator's `rm -rf OUT_DIR` is acceptable today.
- Rename Variant 3 (`OLD ∉ index, NEW ∉ index`, "download MATIC's
  historical data INTO POL's slot in one step"). Operator can do this via
  download (with MATIC + POL) → rename Variant 2; no need for a third
  variant.

## References

- iter-4 spec: `docs/specs/00003-data-prep-design.md`
- iter-4 plan: `docs/plans/00003-data-download-verify.md`
- iter-4 iterations entry: `docs/iterations-history.md` (search "iter-4")
- Commit-messages rule (per-commit Reviewed-by): `.claude/rules/commit-messages.md`
- PR-template structure: `.github/pull_request_template.md` and
  `.claude/rules/pull-requests.md`
- Open-topics convention: `.claude/rules/open-topics.md`
- Binance public-data layout:
  https://github.com/binance/binance-public-data/blob/master/README.md
- Binance exchangeInfo (status field):
  https://api.binance.com/api/v3/exchangeInfo
