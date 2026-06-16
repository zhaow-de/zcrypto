# 00005 — `zcrypto data`: split compiled dataset (`./data`) from backup (`BACKUP_DIR`)

- **Date:** 2026-06-17
- **Status:** Approved design (pre-plan)
- **Iteration:** iter-6
- **Scope:** Restructure the `cli/data` on-disk layout into two roots — an
  in-repo, gitignored **compiled dataset** at `./data`, and an external,
  durable **`BACKUP_DIR`** holding `raw/` + `snapshots/`. Rename the positional
  `OUT_DIR` → `BACKUP_DIR`, de-dot `raw`/`snapshots`, thread both roots through
  the pipeline via a small `DatasetPaths` abstraction, and document a one-time
  manual migration. No new data features; the atomic-commit / crash-recovery
  discipline is preserved exactly.

## Goal

Reach a state where `cli/data` writes the **compiled** Qlib dataset
(`calendars/`, `instruments/`, `features/`, `index.json`, plus — from iter-7 —
Qlib's `cache/`, and the transient `.staging/` + `.commit-in-progress` marker)
to an in-repo, gitignored `./data`, while the **durable backup** — the
downloaded-zip mirror (`raw/`) and the rollback snapshots (`snapshots/`) — lives
in an external `BACKUP_DIR`. The CLI positional becomes `BACKUP_DIR`; a new
`--data-dir` option (default `./data`) names the compiled root. After this
change exactly one data directory lives outside the repo root.

Rationale for which side is which: the downloaded zips and rollback snapshots
are **expensive to reacquire** and must survive a repo wipe → external
`BACKUP_DIR`. The compiled bins + Qlib cache are **cheap to rebuild** from the
mirror → gitignored `./data`. The forthcoming experiment command (spec `00006`)
points Qlib at `./data` and lets Qlib write its disk cache to the
default `<provider>/cache` = `./data/cache`, with no special relocation and no
collision with `data verify`.

## Background & constraints

- **iter-5 baseline.** `cli/data/` has `download` / `verify` / `backfill` /
  `delist` / `rename` under a shared `_execute_mutation` harness with
  snapshot+marker crash recovery, atomic staging-then-swap commit, pre-flight
  `verify_dataset`, concurrent fetch, a local zip mirror (`.raw`), snapshots
  (`.snapshots`), staging (`.staging`), and a commit marker
  (`.commit-in-progress`). All preserved; iter-6 **relocates**, not rewrites.
- **Today everything derives from a single `out_dir`.** `.raw` / `.snapshots` /
  `.staging` / `.commit-in-progress` are dot-prefixed siblings of the compiled
  dirs. Snapshot / verify / commit operate on a **named allowlist**
  (`SNAPSHOT_ITEMS = calendars, instruments, features, index.json`) — the dot
  prefix is convention, **not** the exclusion mechanism. De-dotting `raw` /
  `snapshots` is therefore safe once they live in a separate root.
- **Correctness invariant (discovered in iter-5 code).** `_commit_staging`
  swaps `staging → live` with `shutil.move` (`pipeline.py`), which is atomic
  **only within one filesystem**. Therefore `.staging/` and the
  `.commit-in-progress` marker **must remain on `./data`'s filesystem**.
  Snapshots may live in `BACKUP_DIR` because `create_snapshot` /
  `_restore_from_snapshot` are `tar` create / extract (copy-based), not renames.
- **`verify` already ignores non-allowlisted entries.** `verify_dataset` walks
  only `features/**.bin`, `calendars/`, `instruments/`, and `index.json` (plus
  the `.commit-in-progress` check). Top-level `cache/` and `.staging/` inside
  `./data` are **not** orphan-flagged — confirmed in `verify.py`. No verify
  change is needed for cache; that knob is enabled in spec `00006`.
- **Breaking change.** Both the positional-argument meaning and the on-disk
  layout change. No backward-compat shim; a one-time **manual** migration is
  documented. Commit `feat(data)!`; `cz bump` per `.cz.toml`.
- **Content format unchanged.** Only directory *locations* move. `index.json`
  schema, bin format, and `SCHEMA_VERSION` are untouched.
- **Repo rules unchanged.** README `## Usage` updated in the same change;
  `docs/iterations-history.md` closeout entry; branch + PR per
  `branch-workflow.md` / `pull-requests.md`.

## Decisions (resolved during brainstorming)

| Fork | Decision |
| --- | --- |
| Compiled root | `./data`, in-repo, **gitignored**. Exposed as `--data-dir` (default `./data`) — **not** a hardcoded constant, so tests can redirect it to a tmp dir. |
| Backup root | `BACKUP_DIR` — positional, required, replaces `OUT_DIR` on the four mutating commands. Holds `raw/` + `snapshots/`. Created if absent. |
| De-dotting | `.raw` → `raw/`, `.snapshots` → `snapshots/` (they leave `./data` entirely; exclusion was allowlist-based). `.staging` and `.commit-in-progress` **stay dotted in `./data`**. |
| Staging filesystem | `staging/` + marker stay on `./data` (same-FS rename invariant). Snapshots cross to `BACKUP_DIR` (tar copy). |
| Cache | Qlib default `./data/cache`; covered by `gitignore /data/`; `verify` already ignores it. **No cache code in this spec** — enabled in `00006`. |
| `verify` command | Operates on `--data-dir` (default `./data`); **no** `BACKUP_DIR` positional (it validates only the compiled dataset). |
| Path plumbing | Introduce `DatasetPaths(data_dir, backup_dir)` with derived `raw_root` / `snapshots_dir` / `staging` / `marker`; thread it through `pipeline` / `snapshots` / `mirror` in place of the raw `out_dir`. |
| Migration | One-time **manual** `mv`, documented in README + iterations-history. No `data migrate` subcommand. |

## The two-root layout

```
./data/                         # compiled dataset — in-repo, GITIGNORED
├── calendars/  instruments/  features/  index.json
├── cache/                      # Qlib disk cache (added in spec 00006)
├── .staging/                   # transient build dir (same FS → atomic swap)
└── .commit-in-progress         # transient recovery marker

BACKUP_DIR/                     # external, durable (e.g. ../zcrypto-data)
├── raw/                        # downloaded-zip mirror (was .raw)
└── snapshots/                  # rollback tar.gz archives (was .snapshots)
```

## `DatasetPaths`

A small dataclass constructed at the CLI boundary and threaded everywhere
`out_dir` is used today:

```python
@dataclass(frozen=True)
class DatasetPaths:
    data_dir: Path        # compiled dataset (--data-dir, default ./data)
    backup_dir: Path      # raw/ + snapshots/ (positional BACKUP_DIR)

    @property
    def raw_root(self) -> Path:       return self.backup_dir / "raw"
    @property
    def snapshots_dir(self) -> Path:  return self.backup_dir / "snapshots"
    @property
    def staging(self) -> Path:        return self.data_dir / ".staging"
    @property
    def marker(self) -> Path:         return self.data_dir / ".commit-in-progress"
```

## CLI surface

```
zcrypto data download BACKUP_DIR PAIRS_FILE [--data-dir ./data] [--interval 1d] [--from ...] [--to ...] [--dry-run]
zcrypto data backfill BACKUP_DIR            [--data-dir ./data] [--interval 1d] [--to ...] [--dry-run]
zcrypto data delist   BACKUP_DIR SYMBOL     [--data-dir ./data] [--dry-run]
zcrypto data rename   BACKUP_DIR OLD NEW    [--data-dir ./data] [--dry-run]
zcrypto data verify                         [--data-dir ./data] [--silent]
```

- **`BACKUP_DIR`** (positional) replaces `OUT_DIR` on the four mutators — the
  directory that receives `raw/` + `snapshots/`; created if absent.
- **`--data-dir`** (default `./data`) names the compiled dataset; created if
  absent.
- **`verify`** drops the positional entirely: it validates only the compiled
  dataset at `--data-dir`.
- The **inversion** is deliberate: previously the positional was where
  *everything* lived; now the positional is the *backup*, and the compiled data
  has a fixed default home (`./data`) that the backtest command also reads.

`PAIRS_FILE`, `--from/--to`, `--dry-run`, `--silent`, and bare-`zcrypto data`
help behavior are all unchanged from iter-5.

## Module changes

- **`mirror.py`** — `MIRROR_DIRNAME = "raw"` (was `".raw"`); `root_for(paths)`
  returns `paths.raw_root` (`BACKUP_DIR/raw`). Path-building (`mirror_path`,
  `read_zip`, `save_zip`) unchanged below the root.
- **`snapshots.py`** — `create_snapshot` / `prune_snapshots` operate on
  `paths.snapshots_dir` (`BACKUP_DIR/snapshots`); read the `SNAPSHOT_ITEMS` from
  `data_dir`, write the archive to `BACKUP_DIR/snapshots`. `SNAPSHOT_ITEMS`
  unchanged.
- **`pipeline.py`** — `_execute_mutation`, `_commit_staging`,
  `_recover_from_interrupted_commit`, `_restore_from_snapshot`, `_build_staging`,
  `_read_existing_pair`, and every `*_plan` / `*_apply` take `DatasetPaths` (or
  `data_dir` + `backup_dir`). `staging = paths.staging`; `marker = paths.marker`.
  The `shutil.move` swaps stay **within `data_dir`** (invariant preserved).
  Snapshot create / restore target `BACKUP_DIR`; `_restore_from_snapshot` reads
  `BACKUP_DIR/snapshots/<name>` and extracts over `data_dir`.
- **`verify.py`** — `verify_dataset(data_dir)`: logic unchanged (already scans
  only compiled subdirs). Operator-facing messages that mention `.snapshots/`
  are reworded to "the backup dir's `snapshots/`".
- **`command.py`** — positional `BACKUP_DIR`; `--data-dir` option default
  `./data`; build `DatasetPaths` and pass it down. `verify_cmd` uses
  `--data-dir` only.
- **`config.py` / constants** — no change beyond the dir-name constant;
  `SCHEMA_VERSION` unchanged.

## Atomic-commit invariant (explicit)

The commit sequence after the relayout, with the filesystem boundary called out:

1. `create_snapshot` → `BACKUP_DIR/snapshots/<stamp>-<cmd>.tar.gz` (tmp +
   `os.replace` **within** `BACKUP_DIR/snapshots`; tar copy — cross-FS safe).
2. write `.commit-in-progress` → `data_dir` (tmp + `os.replace` within
   `data_dir`).
3. `shutil.move(staging/<name> → data_dir/<name>)` for `calendars` /
   `instruments` / `features`, then atomic `index.json` write — **all within
   `data_dir`'s filesystem** (atomic renames).
4. On any failure / crash: recovery reads the marker (`data_dir`), restores from
   `BACKUP_DIR/snapshots/<name>` over `data_dir`.

No cross-filesystem rename ever occurs in the critical path. **Operational
note:** recovery requires `BACKUP_DIR` to be present and pointing at the same
location used for the interrupted run (documented; same class of assumption as
iter-5's single-writer rule).

## Migration (one-time, manual)

Assuming the existing dataset is at `../zcrypto-data` and it becomes the
`BACKUP_DIR`:

```bash
mkdir -p ./data
mv ../zcrypto-data/calendars ../zcrypto-data/instruments \
   ../zcrypto-data/features  ../zcrypto-data/index.json   ./data/
mv ../zcrypto-data/.raw        ../zcrypto-data/raw
mv ../zcrypto-data/.snapshots  ../zcrypto-data/snapshots
uv run zcrypto data verify                 # validates ./data
```

If a `.staging/` or `.commit-in-progress` exists (an interrupted prior run),
recover with the **iter-5** build first (or remove after inspection) before
migrating. Documented in README + the iterations-history entry.

## `.gitignore`

Create a **committed `data/.gitignore`** that ignores everything but itself, so
the directory is **retained** in the repo while all its contents (compiled bins,
`cache/`, `.staging/`, the marker) stay untracked:

```gitignore
*
!.gitignore
```

(Spec `00006` adds the analogous `runs/.gitignore`.) This means `./data` exists
immediately after clone — `mkdir -p ./data` in the migration is then a harmless
no-op, and `--data-dir`'s default target is always present.

## Testing strategy

- **Two-root fixtures.** Every `cli/data` test constructs a tmp `data_dir` + tmp
  `backup_dir` (two `tmp_path` dirs). `FakeSource` injection unchanged.
- **Relocation assertions.** Snapshots land in `BACKUP_DIR/snapshots`; the zip
  mirror in `BACKUP_DIR/raw`; staging + marker in `data_dir`. Crash-recovery
  restores `data_dir` from a `BACKUP_DIR` snapshot. `verify` validates `data_dir`
  and ignores a stray `data_dir/cache` + `.staging`.
- **Migration test.** Build an old-layout dataset, perform the documented `mv`
  steps (via a test helper), assert `verify` passes on the new `./data` and a
  follow-up `backfill` works end-to-end.
- **Regression.** The full iter-5 suite passes after the path refactor (it is
  the regression net for the `DatasetPaths` threading).
- **Coverage discipline** unchanged: every public surface keeps a happy-path +
  refusal test.

## Out of scope

- The backtest command, Qlib disk-cache enablement, and fingerprint busting
  (spec `00006`).
- Any new data features (sub-daily intervals, multi-writer locking, a
  `prune`/`wipe` command).
- A `data migrate` subcommand — manual `mv` suffices for a one-time move.
- Changing the on-disk content format / `SCHEMA_VERSION` (only locations move).

## References

- iter-5 spec / plan: `docs/specs/00004-data-backfill-delist-rename-design.md`,
  `docs/plans/00004-data-backfill-delist-rename.md`
- iter-4 data-prep spec (layout + invariants): `docs/specs/00003-data-prep-design.md`
- Consumer of `./data`: spec `00006` (experiment skeleton)
- Rules: `.claude/rules/branch-workflow.md`, `pull-requests.md`,
  `commit-messages.md`, `readme-usage.md`, `iterations-history.md`
