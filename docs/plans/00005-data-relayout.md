# Data Relayout (`./data` vs `BACKUP_DIR`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the `cli/data` on-disk layout into a compiled dataset at an in-repo, gitignored `./data` (`--data-dir`) and an external durable `BACKUP_DIR` (positional) holding `raw/` + `snapshots/`, preserving the atomic-commit / crash-recovery discipline exactly.

**Architecture:** Introduce a `DatasetPaths(data_dir, backup_dir)` value object and thread it through the mutation harness. **Compiled dataset, `.staging/`, and the `.commit-in-progress` marker stay on `data_dir`** (so `shutil.move(staging → live)` remains a same-filesystem atomic rename); only the zip mirror (`raw/`, de-dotted) and rollback `snapshots/` (de-dotted) move to `backup_dir` (created via `tar`, cross-FS safe). `verify_dataset` is unchanged (the marker it checks lives on `data_dir`).

**Tech Stack:** Python 3.12, Typer, pytest, uv. Spec: `docs/specs/00005-data-relayout-design.md`.

---

## Commit & review conventions (apply to every task below)

These implementation commits are **not** review-exempt (only the spec/plan/closeout-doc commits are). Per `.claude/rules/commit-messages.md`:

- Every commit ends with a blank line + `Co-Authored-By: <actual model> <noreply@anthropic.com>`.
- Every commit is **reviewed by a separate subagent before push**; amend a `Reviewed-by: <reviewer model> <noreply@anthropic.com>` trailer while the commit is still local (defer pushing until review passes).
- Task 5's breaking commit (`feat(data)!`) adds a **hyphenated** `BREAKING-CHANGE:` footer (never the space form — it breaks git-trailer parsing and silently drops the co-author trailer).

The per-step `git commit  # "<subject>"` lines below show the subject only; append the trailer(s) per the above.

## Reference: confirmed map of the refactor surface

- **Functions that gain `backup_dir` awareness:** `mirror.root_for`, `snapshots.create_snapshot`, `snapshots.prune_snapshots`, `pipeline._execute_mutation`, `pipeline._commit_staging`, `pipeline._recover_from_interrupted_commit`, the four `*_pipeline` entry points, and the `download`/`backfill` apply functions (they call `mirror.root_for`).
- **Functions UNCHANGED (compiled-only, take `data_dir`):** `index.load_index/save_index`, `qlib_writer.write_calendar/write_instruments/write_bin/read_bin`, `index.compute_sha256`, `pipeline._build_staging`, `_read_existing_pair`, `_restore_from_snapshot`, all `*_plan`, `_delist_apply`, `_rename_apply_variant1/2`, and **`verify.verify_dataset`** (marker is on `data_dir`).
- **`.commit-in-progress` and `.staging/` stay on `data_dir`** — do NOT move them to `backup_dir` (atomic-rename invariant).
- **De-dot:** `.raw` → `backup_dir/raw`, `.snapshots` → `backup_dir/snapshots`. `.staging` and `.commit-in-progress` keep their dot (on `data_dir`).
- **Tests:** 15 data test files, 160 tests. Shared fixtures in `tests/data_fixtures.py` (`FakeSource`, `CountingSource`, `synthetic_kline_csv`, `make_zip_with_checksum`) — **unchanged**. Tests construct datasets via `download_pipeline(...)` seed helpers or manual writes; many assert on `.snapshots` / `.commit-in-progress` / `.staging` / `.raw` paths.

## File Structure

- **Create:** `cli/data/layout.py` — `DatasetPaths` value object.
- **Create:** `tests/test_data_layout.py` — unit tests for `DatasetPaths`.
- **Modify:** `cli/data/mirror.py` — `MIRROR_DIRNAME`, `root_for(backup_dir)`.
- **Modify:** `cli/data/snapshots.py` — `create_snapshot(data_dir, snapshots_dir, command)`, `prune_snapshots(snapshots_dir, keep)`.
- **Modify:** `cli/data/pipeline.py` — harness + entry points + apply closures take `DatasetPaths`.
- **Modify:** `cli/data/command.py` — positional `BACKUP_DIR` + `--data-dir` (default `./data`); build `DatasetPaths`.
- **Modify:** every `tests/test_data_*.py` that references the moved paths or changed signatures.
- **Create:** `data/.gitignore` (`*` + `!.gitignore`); **modify:** repo-root `.gitignore` if needed.
- **Modify:** `README.md` `## Usage` (OUT_DIR → BACKUP_DIR + `--data-dir`; document layout + migration).
- **Modify:** `docs/iterations-history.md` — closeout entry.

---

### Task 1: `DatasetPaths` value object

**Files:**
- Create: `cli/data/layout.py`
- Test: `tests/test_data_layout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_layout.py
from pathlib import Path

from cli.data.layout import DatasetPaths


def test_dataset_paths_derived_locations():
    paths = DatasetPaths(data_dir=Path("/repo/data"), backup_dir=Path("/ext/bk"))
    assert paths.raw_root == Path("/ext/bk/raw")
    assert paths.snapshots_dir == Path("/ext/bk/snapshots")
    # staging + marker stay on data_dir (same-FS atomic-rename invariant)
    assert paths.staging == Path("/repo/data/.staging")
    assert paths.marker == Path("/repo/data/.commit-in-progress")


def test_dataset_paths_is_frozen():
    paths = DatasetPaths(data_dir=Path("a"), backup_dir=Path("b"))
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.data_dir = Path("c")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_data_layout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cli.data.layout'`.

- [ ] **Step 3: Write minimal implementation**

```python
# cli/data/layout.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_COMMIT_MARKER_NAME = ".commit-in-progress"
_STAGING_NAME = ".staging"


@dataclass(frozen=True)
class DatasetPaths:
    """Two-root layout: compiled dataset (data_dir) + durable backup (backup_dir).

    The compiled dataset, the staging dir, and the commit marker all live on
    `data_dir` so the atomic commit's `shutil.move(staging -> live)` stays a
    same-filesystem rename. Only the zip mirror (`raw/`) and rollback archives
    (`snapshots/`) live on `backup_dir`.
    """

    data_dir: Path
    backup_dir: Path

    @property
    def raw_root(self) -> Path:
        return self.backup_dir / "raw"

    @property
    def snapshots_dir(self) -> Path:
        return self.backup_dir / "snapshots"

    @property
    def staging(self) -> Path:
        return self.data_dir / _STAGING_NAME

    @property
    def marker(self) -> Path:
        return self.data_dir / _COMMIT_MARKER_NAME
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_data_layout.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add cli/data/layout.py tests/test_data_layout.py
git commit  # message: "feat(data): add DatasetPaths two-root layout value object"
```

---

### Task 2: Relocate the zip mirror to `backup_dir/raw`

**Files:**
- Modify: `cli/data/mirror.py` (`MIRROR_DIRNAME`, `root_for`)
- Modify: `tests/test_data_mirror.py`

`root_for` currently takes `out_dir` and returns `out_dir / ".raw"`. Change it to take `backup_dir` and return `backup_dir / "raw"`. The only production call sites (`pipeline._download_apply`, `_backfill_apply`) are updated in Task 4; this task changes `mirror.py` + its own unit tests together so `tests/test_data_mirror.py` stays green in isolation.

- [ ] **Step 1: Update the mirror tests to the new contract**

In `tests/test_data_mirror.py`, change every `mirror.root_for(<dir>)` call to pass a backup dir and expect `<backup_dir>/raw` (no leading dot). E.g. a test that did `assert mirror.root_for(tmp_path) == tmp_path / ".raw"` becomes `assert mirror.root_for(tmp_path) == tmp_path / "raw"`. Update the e2e mirror-download test to point the mirror root at a `backup_dir` (a second `tmp_path`-derived dir) — the zip-layout assertions under `<root>/spot/daily/klines/...` are unchanged.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_data_mirror.py -v`
Expected: FAIL (asserts expect `raw`, code still returns `.raw`).

- [ ] **Step 3: Edit `cli/data/mirror.py`**

```python
MIRROR_DIRNAME = "raw"  # was ".raw"; the mirror now lives under BACKUP_DIR, de-dotted


def root_for(backup_dir: Path) -> Path:
    """Mirror root for a dataset: ``<backup_dir>/raw``.

    The downloaded-zip mirror lives in the external backup dir (durable, the
    expensive-to-reacquire artifact), separate from the compiled dataset.
    """
    return backup_dir / MIRROR_DIRNAME
```

Update the module docstring's reference to `.raw`/`.snapshots`/`.staging` accordingly (mirror lives in the backup dir now).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_data_mirror.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/data/mirror.py tests/test_data_mirror.py
git commit  # "refactor(data): mirror root moves to BACKUP_DIR/raw (de-dotted)"
```

---

### Task 3: Relocate snapshots to `backup_dir/snapshots`

**Files:**
- Modify: `cli/data/snapshots.py`
- Modify: `tests/test_data_snapshots.py`

New signatures:
- `create_snapshot(data_dir: Path, snapshots_dir: Path, command: str) -> Path` — read `SNAPSHOT_ITEMS` from `data_dir`, write the archive into `snapshots_dir` (de-dotted; create if absent).
- `prune_snapshots(snapshots_dir: Path, keep: int = SNAPSHOT_KEEP) -> list[Path]` — operate on `snapshots_dir`.

- [ ] **Step 1: Update the snapshot tests to the new contract**

In `tests/test_data_snapshots.py`: the `_populate(out_dir)` helper still writes the compiled files into a `data_dir`. Introduce a `snapshots_dir` (a separate `tmp_path` subdir). Change `create_snapshot(out_dir, cmd)` → `create_snapshot(data_dir, snapshots_dir, cmd)` and assert the archive lands in `snapshots_dir`. Change `prune_snapshots(out_dir)` → `prune_snapshots(snapshots_dir)`. The "SNAPSHOT_ITEMS only" / retention / atomic-write / monotone-stamp assertions are unchanged except for the path root.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_data_snapshots.py -v`
Expected: FAIL (signature / path mismatch).

- [ ] **Step 3: Edit `cli/data/snapshots.py`**

```python
def create_snapshot(data_dir: Path, snapshots_dir: Path, command: str) -> Path:
    """Pack the compiled dataset files into ``<snapshots_dir>/<stamp>-<cmd>.tar.gz`` atomically."""
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = snapshots_dir / f"{stamp}-{command}.tar.gz"
    tmp = archive.with_suffix(archive.suffix + ".tmp")
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for name in SNAPSHOT_ITEMS:
                p = data_dir / name
                if p.exists():
                    tar.add(p, arcname=name)
        os.replace(tmp, archive)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return archive


def prune_snapshots(snapshots_dir: Path, keep: int = SNAPSHOT_KEEP) -> list[Path]:
    """Keep newest `keep` archives in `snapshots_dir`; remove older. Return removed paths."""
    if not snapshots_dir.is_dir():
        return []
    archives = sorted(snapshots_dir.glob("*.tar.gz"))
    if len(archives) <= keep:
        return []
    removed = archives[: len(archives) - keep]
    for p in removed:
        p.unlink()
    return removed
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_data_snapshots.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/data/snapshots.py tests/test_data_snapshots.py
git commit  # "refactor(data): snapshots move to BACKUP_DIR/snapshots (de-dotted)"
```

---

### Task 4: Thread `DatasetPaths` through the pipeline harness + entry points

**Files:**
- Modify: `cli/data/pipeline.py`
- Modify: `cli/data/verify.py` (stale `.snapshots/` operator message only — signature unchanged)

This is the interlocking core. It changes signatures that cascade to `command.py` (Task 5) and the pipeline-driven tests (Task 6); **the full suite is RED between Task 4 and Task 6** — that is expected and called out at the green checkpoint in Task 7. Do the whole of `pipeline.py` in this one task/commit.

Exact changes (keep all behavior identical; only relocate paths + thread `paths`):

- [ ] **Step 1: `_execute_mutation`** → `def _execute_mutation(paths: DatasetPaths, cmd_name: str, plan_fn, apply_fn, *, dry_run=False)`:
  - `paths.data_dir.mkdir(parents=True, exist_ok=True)` and `paths.backup_dir.mkdir(parents=True, exist_ok=True)`.
  - Recovery: `_recover_from_interrupted_commit(paths)`. Dry-run marker check: `paths.marker`.
  - Pre-flight: `verify_dataset(paths.data_dir)` (unchanged signature).
  - `plan = plan_fn(paths.data_dir)`.
  - `staging = paths.staging` (on `data_dir`); same rmtree/mkdir dance.
  - `apply_fn(paths, staging, plan)` (apply closures now receive `paths`).
  - Post-verify: `verify_dataset(staging)`.
  - `_commit_staging(paths, staging, cmd_name=cmd_name)`.
- [ ] **Step 2: `_write_commit_marker`** → `def _write_commit_marker(paths: DatasetPaths, snapshot_name: str)`: write `paths.marker` (data_dir; tmp+os.replace).
- [ ] **Step 3: `_recover_from_interrupted_commit`** → `def _recover_from_interrupted_commit(paths: DatasetPaths)`: read `paths.marker`; resolve snapshot at `paths.snapshots_dir / snap_name`; `_restore_from_snapshot(paths.data_dir, snap)`; `paths.marker.unlink()`. Keep the same empty-marker / missing-snapshot `PipelineError` messages (update the `.snapshots/` text to "the backup dir's snapshots/").
- [ ] **Step 4: `_commit_staging`** → `def _commit_staging(paths: DatasetPaths, staging: Path, *, cmd_name="download")`:
  - `snapshot = create_snapshot(paths.data_dir, paths.snapshots_dir, cmd_name)`.
  - `prune_snapshots(paths.snapshots_dir)`.
  - `_write_commit_marker(paths, snapshot.name)`.
  - moves `staging/<name> → paths.data_dir/<name>` for `calendars`/`instruments`/`features` (unchanged — same FS); `save_index(paths.data_dir, ...)`.
  - rollback path: `_restore_from_snapshot(paths.data_dir, snapshot)`; `paths.marker.unlink(missing_ok=True)`.
- [ ] **Step 5: apply functions** receive `paths`:
  - `_download_apply(paths, staging, plan, source)`: `mirror.root_for(paths.backup_dir)`; `_build_staging(paths.data_dir, staging, ...)`.
  - `_backfill_apply(paths, staging, plan, source, interval)`: `mirror.root_for(paths.backup_dir)`; `_build_staging(paths.data_dir, ...)`.
  - `_delist_apply(paths, staging, plan)`: uses `paths.data_dir` only (reads compiled features, writes staging).
  - `_rename_apply_variant1(paths, staging, plan)` / `_rename_apply_variant2(paths, staging, plan)`: use `paths.data_dir` for live reads (`features/`, `calendars/day.txt` via `_load_calendar_dates(paths.data_dir / "calendars" / "day.txt")`) + `staging`.
  - The `*_plan` functions keep `(data_dir, ...)` — call them with `paths.data_dir`.
- [ ] **Step 6: entry points** → take `DatasetPaths`:
  - `download_pipeline(paths, pairs_file, interval, from_date, to_date, source, *, dry_run=False)`
  - `backfill_pipeline(paths, interval, arg_to, source, *, dry_run=False)`
  - `delist_pipeline(paths, symbol, *, dry_run=False)`
  - `rename_pipeline(paths, old_symbol, new_symbol, source, *, dry_run=False)`
  - Each builds concrete closures, e.g. download: `plan_fn = lambda data_dir: _download_plan(data_dir, pairs_file, interval, from_date, to_date, source)` + `apply_fn = lambda paths, s, p: _download_apply(paths, s, p, source)`; backfill: `apply_fn = lambda paths, s, p: _backfill_apply(paths, s, p, source, interval)`; delist: `apply_fn = lambda paths, s, p: _delist_apply(paths, s, p)`; rename: `apply_fn = lambda paths, s, p: _rename_apply(paths, s, p)` — then `_execute_mutation(paths, "<x>", plan_fn, apply_fn, dry_run=dry_run)`.
- [ ] **Step 7: add the import** `from cli.data.layout import DatasetPaths` and drop the now-unused `_COMMIT_MARKER` literal in favor of `paths.marker` (or keep the constant in `layout.py`; remove the local one in `pipeline.py` if unused). Run `uv run ruff check --fix cli/data/pipeline.py`.
- [ ] **Step 7b: Fix stale `.snapshots/` operator messages.** Reword the pre-flight `PipelineError` text in `cli/data/verify.py` ("Restore from `.snapshots/`") and any remaining `.snapshots/` reference in `pipeline.py` messages to "restore from the backup dir's `snapshots/`" — operators must not be pointed at a path that no longer exists under `data_dir`. (`verify_dataset`'s signature is unchanged; only the message string.)

- [ ] **Step 8: Commit** (suite is red until Task 6 — that's expected):

```bash
git add cli/data/pipeline.py
git commit  # "refactor(data): thread DatasetPaths through the mutation harness"
```

---

### Task 5: CLI surface — `BACKUP_DIR` positional + `--data-dir`

**Files:**
- Modify: `cli/data/command.py`

- [ ] **Step 1: Rewrite each command's args.** For `download`/`backfill`/`delist`/`rename`: rename the `out_dir` positional to `backup_dir: Path = typer.Argument(..., help="Backup dir (raw/ + snapshots/); created if absent.", file_okay=False)`, add `data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Compiled dataset dir (default ./data).", file_okay=False)`, build `paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)`, and call the entry point with `paths`. For `verify`: replace the `out_dir` positional with `data_dir: Path = typer.Option(Path("data"), "--data-dir", ...)`, call `verify_dataset(data_dir, fail_on_gap=True)`. Keep `--dry-run` / `--silent` / `--from` / `--to` / `--interval` exactly as they are. Update the success-line `typer.echo` messages to reference `data_dir` (the dataset) where they currently print `out_dir`.

- [ ] **Step 2: Add the import** `from cli.data.layout import DatasetPaths` and run `uv run ruff check --fix cli/data/command.py`.

- [ ] **Step 3: Commit** (still red until Task 6):

```bash
git add cli/data/command.py
git commit  # "feat(data)!: positional BACKUP_DIR + --data-dir (default ./data)"
```

Note the `!` — this is a breaking CLI change.

---

### Task 6: Update the data test suite to the two-root layout

**Files:**
- Modify: `tests/test_data_pipeline.py`, `test_data_download.py`, `test_data_backfill.py`, `test_data_delist.py`, `test_data_rename.py`, `test_data_e2e.py`, `test_data_command.py`. (`test_data_verify.py`, `test_data_qlib_writer.py`, `test_data_index.py`, `test_data_klines.py`, `test_data_binance.py`, `test_data_config.py` need **no** change — they touch only compiled-dir or pure functions.)

Mechanical translation rules (apply per file; the suite is the safety net):

- [ ] **Step 1:** Where a test made `out = tmp_path / "ds"` and called a `*_pipeline(out, ...)`, introduce `data_dir = tmp_path / "data"` and `backup_dir = tmp_path / "bk"`, build `paths = DatasetPaths(data_dir=data_dir, backup_dir=backup_dir)`, and call `*_pipeline(paths, ...)`. Seed helpers (`_seed_source`, `_bootstrap_two_pairs`, `_seed_three_pairs_uniform`, `_seed_single_pair`, `_seed_two_pairs_for_merge`, etc.) gain a `paths` (or `(data_dir, backup_dir)`) parameter and pass it through.
- [ ] **Step 2:** Path assertions translate:
  - `out / ".snapshots"` → `backup_dir / "snapshots"`
  - `out / ".raw"` → `backup_dir / "raw"`
  - `out / ".staging"` → `data_dir / ".staging"`  *(stays on data_dir)*
  - `out / ".commit-in-progress"` → `data_dir / ".commit-in-progress"`  *(stays on data_dir)*
  - `out / "index.json"`, `out / "calendars" | "instruments" | "features"` → `data_dir / ...`
  - `verify_dataset(out)` → `verify_dataset(data_dir)`; `load_index(out)` → `load_index(data_dir)`.
- [ ] **Step 3:** For `test_data_command.py` (CliRunner): invoke `["data", "download", str(backup_dir), str(pairs), "--data-dir", str(data_dir)]` etc.; `["data", "verify", "--data-dir", str(data_dir)]`. Assert on `data_dir` contents.
- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all 160 + the 2 new layout tests).

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit  # "test(data): adapt suite to DatasetPaths two-root layout"
```

---

### Task 7: gitignore, README, migration docs

**Files:**
- Create: `data/.gitignore`
- Modify: `README.md`
- (Verify repo-root `.gitignore` doesn't already exclude `data/`.)

- [ ] **Step 1: Create `data/.gitignore`**

```gitignore
*
!.gitignore
```

- [ ] **Step 2: Rewrite the `## Usage` `zcrypto data` section** in `README.md`: every `OUT_DIR` → `BACKUP_DIR`; add the `--data-dir` option (default `./data`) to all five subcommands; `verify` drops the positional and gains `--data-dir`. Add a short "Layout & migration" note documenting the two-root layout and the one-time manual `mv` (verbatim from spec `00005`'s Migration section). Do **not** hand-edit the mdformat TOC.

- [ ] **Step 3: Run formatting + the README/usage check**

Run: `uv run pre-commit run --files README.md data/.gitignore`
Expected: hooks pass (mdformat may reflow — re-stage if so).

- [ ] **Step 4: Commit**

```bash
git add README.md data/.gitignore
git commit  # "docs(data): document BACKUP_DIR + ./data layout and migration"
```

---

### Task 8: Full-suite verification + iterations-history closeout

**Files:**
- Modify: `docs/iterations-history.md`

- [ ] **Step 1: Run the full gate**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest -q`
Expected: all green — 160 tests pass (158 existing + the 2 new layout tests).

- [ ] **Step 2: Append the iterations-history entry** — a new `## <YYYY-MM-DD> — iter-6: data relayout` section with bullets covering: the two-root split (`./data` compiled vs `BACKUP_DIR` raw/+snapshots/), `DatasetPaths`, the de-dotting, the preserved same-FS atomic-commit invariant (staging + marker stay on `data_dir`), the breaking CLI change (`OUT_DIR`→`BACKUP_DIR` + `--data-dir`), `data/.gitignore`, and the manual-migration note.

- [ ] **Step 3: Commit**

```bash
git add docs/iterations-history.md
git commit  # "docs: iter-6 data-relayout iterations-history entry"
```

- [ ] **Step 4:** Open the PR into `develop` per `pull-requests.md` (title `feat(data): iter-6 — split compiled dataset from external BACKUP_DIR`). *(Handled at the finishing-a-development-branch step, not here.)*

---

## Self-review notes

- **Spec coverage:** two-root layout (Tasks 1–6), de-dotting (2,3,6), atomic invariant preserved (Task 4 keeps staging+marker on `data_dir`), CLI inversion (Task 5), `data/.gitignore` (7), migration (7), iterations-history (8). ✓
- **Invariant guard:** Task 4 explicitly keeps `staging`/`marker` on `data_dir` — do not relocate them to `backup_dir` (would break `shutil.move` atomicity).
- **Red window:** Tasks 4–5 leave the suite red by design; Task 6 restores green. The orchestrator should treat Task 6's full-suite pass as the gate, not the intermediate commits.
- **Out of scope:** the `experiment` command, qlib cache, and `runs/.gitignore` — those are spec/plan `00006`.
