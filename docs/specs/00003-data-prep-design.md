# 00003 — `zcrypto data`: Binance → Qlib dataset (download & verify)

- **Date:** 2026-06-09
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-4
- **Scope:** Add a `zcrypto data` command group with `download` (fetch Binance
  spot 1d klines → a ready-made Qlib dataset + `index.json`) and `verify`
  (read-only re-validation). `backfill`, `delist`, `rename` are deferred to a
  later iteration.

## Goal

Produce a **consistent, ready-made Qlib dataset** from Binance spot klines so
that Qlib experiments/backtests need no further data conversion. `download`
fetches daily 1d klines from `data.binance.vision`, checksum-validates them,
converts to Qlib's binary file format (calendar + instruments + per-field
bins), and maintains an `index.json` describing the dataset. `verify`
re-validates an existing dataset against that index and all invariants, and is
also exposed as a plain function any Qlib pipeline can call before a run.

## Background & constraints

- **Existing Qlib writer.** `cli/example/dataset.py::build_provider` already
  writes a *replace-only* Qlib dataset (`calendars/day.txt`,
  `instruments/all.txt`, `features/<sym>/<field>.day.bin` as little-endian
  float32 with a start-index header). The new writer is an **append-aware**
  sibling of essentially this code (full rebuild in a staging dir, then swap).
- **CLI patterns.** `cli/__main__.py` is a Typer app; subcommands register on
  it, and heavy imports (qlib/pandas/numpy) are deferred inside functions so
  `zcrypto --version`/`--help` stay fast. The root callback already routes
  `--log`/`--log-level` (parsed before subcommands), so the new commands get
  logging for free.
- **Binance public data.** Spot klines live at
  `https://data.binance.vision/data/spot/daily/klines/<SYMBOL>/<interval>/<SYMBOL>-<interval>-<YYYY-MM-DD>.zip`,
  each with a sibling `…<YYYY-MM-DD>.zip.CHECKSUM` (sha256). The trading-pair
  list and base/quote tickers come from
  `https://api.binance.com/api/v3/exchangeInfo` (`.symbols[]`).
- **Research motivation.** `docs/research/01.binance-eea-spot-quant.md`: a
  cross-sectional Alpha158 ranker over ~20 USDC pairs, daily bars, 3–5 years of
  history. Daily frequency and multi-year history drive the design.
- **Repo rules.** README `## Usage` updated in the same change
  (`readme-usage.md`); `docs/iterations-history.md` entry as the final plan
  task; branch + PR per `branch-workflow.md` / `pull-requests.md`; open topics
  per `open-topics.md`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Iteration scope | `data` (help parent) + `download` + `verify`. Defer `backfill`/`delist`/`rename`. |
| Fetch partitioning | **Daily-only** (one zip + `.CHECKSUM` per day), sequential. Slow multi-year load accepted; concurrency/monthly archives deferred (open topic). |
| Bin fields | **Full klines + derived `vwap` + `factor`** (11 fields) — front-loaded so a slow re-download is never needed to add a column. |
| `download` vs existing data | **Reconcile to the pairs file** (new pair → full history; existing → time-extend; indexed pair absent from file → error). Every decision logged. |
| Snapshots | Every mutating subcommand snapshots first; **one archive** per snapshot (`.snapshots/<stamp>-<cmd>.tar.gz`), newest **7** kept. |
| Layout / atomicity | **qlib-native dir** (`provider_uri` = out-dir); stage → validate → snapshot → replace (`index.json` last). |
| `index.json` per-pair `to` | **Omitted** — right edge is `calendar.to` for all pairs by construction. |
| `index.json` per-pair `rows` | **Kept** — varies per pair (ragged left edge); useful denormalization; `verify` enforces consistency. |
| CLI mandatory args | **Positional** (`OUT_DIR`, `PAIRS_FILE`). |
| Help scoping | **git-like** — one level per group; full nested reference only in README `## Usage`. |
| Date args | Strict `YYYY-MM-DD` validated at parse time (regex + real-calendar parse). |
| `verify` shape | A pure `verify_dataset(out_dir) -> VerifyReport` function + thin CLI wrapper; `--silent` = exit-code-only. |
| HTTP client | stdlib `urllib.request`; fetching behind a `Source` interface for test injection (no network in tests). |

## CLI surface

```
zcrypto data                       # no subcommand → print this group's help, exit 0
zcrypto data download OUT_DIR PAIRS_FILE [--interval 1d]
                                          [--from 2020-01-01]
                                          [--to <yesterday, UTC>]
zcrypto data verify   OUT_DIR [--silent]
```

- **Help is git-like.** Bare `zcrypto` → root help (first-level commands
  `example`, `data` + root options only). Bare `zcrypto data` → the group's help
  (`download`, `verify` + their options only) — no recursion into grandchildren,
  no root noise. Implemented by an `invoke_without_command=True` callback on the
  `data` sub-app that prints `ctx.get_help()` and exits; Click already scopes a
  group's help to one level. The full nested picture lives **only** in README
  `## Usage`.
- **Positional** `OUT_DIR`, `PAIRS_FILE` (download) and `OUT_DIR` (verify).
- `--interval` default `1d`; **anything other than `1d` → log a NotSupported
  error and exit** (non-zero).
- `--from` default `2020-01-01`; `--to` default **yesterday** (UTC).
- **Date validation at parse time** via a Typer callback: regex
  `^\d{4}-\d{2}-\d{2}$` **and** a real-calendar parse (so `20260609` and
  `2026-13-40` are rejected immediately, before any I/O). `--from ≤ --to`
  enforced up front.
- **Pairs file:** one symbol per line (`BTCUSDT`), blank lines allowed, no
  header, **≥1 symbol required**. Unreadable / empty / zero-pairs → error, exit.
  Any symbol absent from `exchangeInfo` → error (listing the offenders), exit.

## On-disk layout (`provider_uri` = out-dir)

```
OUT_DIR/
  calendars/day.txt                        # dense: every date global_min..calendar.to
  instruments/all.txt                      # SYMBOL<TAB>from<TAB>to   (uppercase)
  features/<symbol_lower>/<field>.day.bin   # 11 bins per pair; <f4; start-index header
  index.json                               # our bookkeeping (Qlib ignores it)
  .snapshots/<stamp>-<cmd>.tar.gz          # rolling; newest 7 retained
  .staging/                                # transient; present only mid-run
```

`features/<f>.day.bin` and `calendars/day.txt` already namespace by Qlib freq
(`day`); a future `1h` interval is additive (`<f>.<freq>.bin`,
`calendars/<freq>.txt`), never a migration. Qlib reads only
`calendars/`/`instruments/`/`features/`, so `.snapshots/` and `.staging/` are
invisible to it.

## `index.json` schema

```json
{
  "schema_version": 1,
  "updated_at": "2026-06-09T12:00:00Z",
  "calendar": { "freq": "day", "from": "2020-01-01", "to": "2026-06-08", "days": 2351 },
  "pairs": {
    "BTCUSDT": {
      "base_asset": "BTC",
      "quote_asset": "USDT",
      "intervals": {
        "1d": {
          "from": "2020-01-01",
          "rows": 2351,
          "fields": {
            "open":            { "bin": "features/btcusdt/open.day.bin",            "sha256": "…", "updated_at": "…" },
            "high":            { "bin": "features/btcusdt/high.day.bin",            "sha256": "…", "updated_at": "…" },
            "low":             { "bin": "features/btcusdt/low.day.bin",             "sha256": "…", "updated_at": "…" },
            "close":           { "bin": "features/btcusdt/close.day.bin",           "sha256": "…", "updated_at": "…" },
            "volume":          { "bin": "features/btcusdt/volume.day.bin",          "sha256": "…", "updated_at": "…" },
            "amount":          { "bin": "features/btcusdt/amount.day.bin",          "sha256": "…", "updated_at": "…" },
            "trades":          { "bin": "features/btcusdt/trades.day.bin",          "sha256": "…", "updated_at": "…" },
            "taker_buy_base":  { "bin": "features/btcusdt/taker_buy_base.day.bin",  "sha256": "…", "updated_at": "…" },
            "taker_buy_amount":{ "bin": "features/btcusdt/taker_buy_amount.day.bin","sha256": "…", "updated_at": "…" },
            "vwap":            { "bin": "features/btcusdt/vwap.day.bin",            "sha256": "…", "updated_at": "…" },
            "factor":          { "bin": "features/btcusdt/factor.day.bin",          "sha256": "…", "updated_at": "…" }
          }
        }
      }
    }
  },
  "other_files": {
    "calendars/day.txt":   { "sha256": "…", "updated_at": "…" },
    "instruments/all.txt": { "sha256": "…", "updated_at": "…" }
  }
}
```

- **Right edge is global:** every pair's effective to-date is `calendar.to`;
  there is deliberately **no** per-pair `to` field to drift out of sync.
- **`rows` is per-pair** (the ragged left edge moves with each pair's `from`),
  kept as a human-friendly denormalization; `verify` guarantees it never drifts
  (see Verify).
- **`other_files`** tracks the non-bin dataset files (`calendars/day.txt`,
  `instruments/all.txt`); the per-field bins — also files — are tracked under
  each pair's `fields`, hence the name.
- Timestamps are UTC ISO-8601 with a trailing `Z`.

## Fields (11) and Binance kline mapping

Binance 1d kline CSV columns (0-indexed): `0 open_time, 1 open, 2 high, 3 low,
4 close, 5 volume, 6 close_time, 7 quote_asset_volume, 8 count, 9
taker_buy_base_asset_volume, 10 taker_buy_quote_asset_volume, 11 ignore`. Some
recent files carry a header row — the parser detects and skips it (first cell
non-numeric).

| Bin field | Source | Notes |
| --- | --- | --- |
| `open`/`high`/`low`/`close` | cols 1–4 | |
| `volume` | col 5 | base-asset volume |
| `amount` | col 7 | quote-asset volume (turnover) |
| `trades` | col 8 | trade count |
| `taker_buy_base` | col 9 | |
| `taker_buy_amount` | col 10 | taker-buy quote volume |
| `vwap` | derived | `amount / volume`; if `volume == 0` → `close` |
| `factor` | constant | `1.0` (no corporate actions in crypto spot) |

`date` ← `open_time` (ms epoch) → UTC `YYYY-MM-DD` (for 1d, the day's 00:00 UTC
boundary). Each bin is `<f4` little-endian: `[start_index_header, v0, v1, …]`
where `start_index_header = calendar.index(pair.from)` per Qlib's `dump_bin`
convention.

## `download` pipeline

1. **Parse + validate inputs.** Read the pairs file (strip, drop blanks, dedupe,
   require ≥1). Fetch `exchangeInfo` once; validate every listed symbol exists;
   capture each pair's `base_asset`/`quote_asset`. Validate `--interval == 1d`.
2. **Resolve per-pair date ranges** (reconcile-to-file; every decision logged):
   - `to = --to` (default yesterday, UTC).
   - **First-available date** for a pair is found by **binary search** over
     `data.binance.vision` (availability is monotone after listing) — ~12 probes
     instead of thousands of leading 404s. `effective_from = max(--from,
     first_available)`; if `> --from`, **log a warning** ("data starts
     YYYY-MM-DD, later than requested").
   - **New pair** (not in index): full history `effective_from..to`.
   - **Existing pair:** `--from ≤ index.to` → **warn + adjust**
     `effective_from = index.to + 1` (no overlap); `--from == index.to + 1` →
     contiguous, fine; `--from > index.to + 1` → **gap error**, exit.
   - **Indexed pair absent from the pairs file** → **error**, exit, pointing to
     `delist`/`rename` (iteration 2).
   - Require every pair's max-available date `≥ to` (else it likely renamed or
     delisted) so the common right edge is reachable.
3. **Fetch + check** each day in `[effective_from, to]`: GET
   `…/<SYM>-1d-<date>.zip` and `…<date>.zip.CHECKSUM`, verify sha256
   (**mismatch → error, exit**), unzip, parse the single row. The fetched date
   sequence must be **gap-free** — any internal missing day → **error, exit**.
   (Leading absence before listing is already handled in step 2.)
4. **Stage.** In `OUT_DIR/.staging/`, rebuild the **full** dataset = existing
   rows (if any) **+** new rows per pair → union calendar (dense), write
   `calendars/day.txt`, `instruments/all.txt`, all bins, compute per-field
   sha256, write `index.json`. *"Append" semantics = old data retained + new
   dates added; bins are rebuilt in staging then swapped (a full rebuild is
   trivial at daily-bar sizes and sidesteps fragile in-place byte-appends).*
5. **Validate staging** — decode every bin, re-check gap-free calendar, common
   to-date, per-field checksums, `rows`/length consistency (same checks `verify`
   runs).
6. **Commit.** Snapshot the current live fileset → `.snapshots/<stamp>-download.tar.gz`
   (prune to newest 7); replace live files from staging, writing `index.json`
   **last** as the commit marker; clear `.staging/`. Any error in steps 1–5
   leaves the live dir **pristine**; a crash in the sub-second step-6 move is
   recoverable from the snapshot just taken.
7. **stdout vs log.** Operational detail (per-pair decisions, adjustments,
   per-file progress) and warnings → **log**. One concise final summary (pairs
   processed, new days added, resulting `from..to`) → **stdout**.

## `verify`

`cli/data/verify.py::verify_dataset(out_dir: Path) -> VerifyReport` performs all
checks and **returns** a structured result (`ok: bool` + an ordered list of
problems) — it prints nothing, so any Qlib pipeline can call it directly before
a run. The CLI command wraps it: renders a human-readable report to **stdout**
(detail to the log) and sets the exit code; **`--silent`** renders nothing and
conveys the result via exit code only (0 = valid, non-zero = any problem).

Checks (read-only; changes nothing):

1. `index.json` parses and `schema_version` is known.
2. Every file named in the index exists; recomputed sha256 matches.
3. **Per pair-interval consistency:**
   - `rows == len(calendar) − calendar.index(from)` (i.e.
     `index(calendar.to) − index(from) + 1`);
   - each field's bin file is exactly `(rows + 1) × 4` bytes, and its
     start-index header `== calendar.index(from)`.
4. **Invariants:** calendar is dense/contiguous (no missing day); all pairs
   share the right edge `calendar.to` (enforced transitively by the `rows`/bin
   checks in step 3); `instruments/all.txt` lists exactly the index's pairs,
   each with `start == index from` and `end == calendar.to`.
5. **Orphans:** files on disk under `features/`/`calendars/`/`instruments/` not
   referenced by the index are reported.

## Snapshots

Before any mutating subcommand changes files, the **entire relevant fileset**
(`calendars/`, `instruments/`, `features/`, `index.json`) is packed into a
**single archive** `OUT_DIR/.snapshots/<UTCstamp>-<cmd>.tar.gz` (e.g.
`20260609T120000Z-download.tar.gz`). Only the newest **7** snapshots are
retained (older pruned). `.snapshots/` and `.staging/` are themselves excluded
from snapshots. (Iteration 2's `backfill`/`delist`/`rename` reuse this same
mechanism.)

## Module layout (`cli/data/`)

- `command.py` — Typer sub-app (`data` group callback + `download` + `verify`).
- `binance.py` — fetching behind a small `Source` interface (URL build,
  download, sha256 checksum, unzip, `exchangeInfo`); stdlib `urllib.request`.
- `klines.py` — kline CSV schema, header detection, `vwap`, gap checks.
- `qlib_writer.py` — append-aware calendar/instruments/bin writer + decoder.
- `index.py` — `index.json` schema read/write + invariant helpers.
- `snapshots.py` — snapshot (tar.gz) + prune-to-7.
- `pipeline.py` — `download` orchestration (reconcile → fetch → stage →
  validate → commit).
- `verify.py` — `verify_dataset()` + `VerifyReport`.
- `config.py` — `BASE_URL`, `EXCHANGE_INFO_URL`, `FIELDS`,
  `SUPPORTED_INTERVALS = {"1d"}`, `SNAPSHOT_KEEP = 7`.

Registered via `app.add_typer(data_app, name="data")` in `cli/__main__.py`.
Heavy imports (pandas/numpy) deferred inside functions.

## Testing

- **No network.** Fetching sits behind a `Source` interface; tests inject a
  **fake source** serving local fixture zips/CSVs (+ a fixture `exchangeInfo`).
- **Unit:** kline parse/header-skip/`vwap`/gap; `qlib_writer` write→decode
  round-trip incl. start-index header; `index` read/write + invariant helpers;
  `snapshots` prune-to-7; pairs-file parsing/validation; date-arg validation
  (reject `20260609`, `2026-13-40`, `--from > --to`).
- **Integration:** `download` into a temp dir with a fake source (2–3 synthetic
  pairs, ragged left edge) → `verify` passes; re-run `download` to extend
  (overlap-adjust path); each error path (internal gap, checksum mismatch,
  unknown symbol, non-`1d` interval, indexed-pair-absent-from-file,
  pair-not-reaching-`to`). `verify --silent` exit codes (0 valid / non-zero on a
  tampered bin).

## Assumptions & deferred

- **`.CHECKSUM` URL = `<zip-url>.CHECKSUM`** for the same file (confirmed).
- **Daily-only fetch is slow** for multi-year loads (accepted) — propose an
  **open topic** (concurrency / monthly-archive bulk) per `open-topics.md`
  during implementation.
- `factor ≡ 1.0` and the `vwap` zero-volume fallback (`→ close`) are
  conventions, not upstream-derived.

## Out of scope

- `backfill`, `delist`, `rename` (iteration 2).
- Intervals other than `1d` (validated and rejected for now).
- Concurrent/parallel downloading; monthly-archive bulk fetch.
- Adjusted prices / corporate-action factors beyond the constant `1.0`.
- Any Qlib modeling/experiment wiring that consumes the dataset.

## Closeout (repo rules)

- Spec: `docs/specs/00003-data-prep-design.md`; plan reuses serial `00003` under
  `docs/plans/`.
- Final plan task appends a `docs/iterations-history.md` entry.
- Branch `feat/data-download-verify` off `develop`; **first commit (already
  landed) is the research doc + mdformat wiring**, riding along. PR titled
  `feat(data): iter-4 — data download & verify` into `develop`.
- Per-commit `Co-Authored-By:` trailers; `Reviewed-by:` trailers collected on
  the closeout commit per `commit-messages.md` if review subagents sign off.
