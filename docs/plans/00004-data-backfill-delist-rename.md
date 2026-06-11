# iter-5 — Data Backfill / Delist / Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `zcrypto data backfill`, `zcrypto data delist`, `zcrypto data rename` (with two variants: single-rename-plus-fill, and merge-two-existing), per `docs/specs/00004-data-backfill-delist-rename-design.md`. Refactor iter-4's commit-discipline into a shared mutation harness used by all four mutators (download / backfill / delist / rename). Make `download` and `backfill` status-aware so delisted Binance pairs (`status != "TRADING"`) are handled gracefully.

**Architecture:** Extend `cli/data/`. Introduce one private `_execute_mutation(out_dir, cmd_name, plan_fn, apply_fn, *, dry_run)` helper in `cli/data/pipeline.py` that encapsulates the iter-4 discipline (recover → pre-flight verify → plan → no-op short-circuit → dry-run short-circuit → snapshot → marker → apply → post-verify → commit → marker cleanup). Each mutator command supplies a `plan_fn` (read-only) and `apply_fn` (writes staging). Iter-4's `download_pipeline` is refactored to fit this shape; iter-5's new pipelines slot in identically. Snapshots are now per-command (named `<UTCstamp>-<cmd>.tar.gz`).

**Tech Stack:** Python 3.12 · Typer · pandas / numpy (deferred imports) · stdlib `urllib.request`, `tarfile`, `zipfile`, `hashlib`, `dataclasses`, `json` · pytest · ruff · pre-commit (mdformat / yamllint / ruff). Same as iter-4, nothing new.

---

## File Structure

**Modify (source):**

| File | Change |
| --- | --- |
| `cli/data/pipeline.py` | Add: `_execute_mutation`, `Plan` Protocol, `find_available_range`, `_backfill_plan`/`_backfill_apply`/`backfill_pipeline`, `_delist_plan`/`_delist_apply`/`delist_pipeline`, `_rename_plan`/`_rename_apply`/`rename_pipeline`. Refactor: `download_pipeline` to call `_execute_mutation`; `validate_pairs_against_exchange` to read `status`; `_commit_staging` + `create_snapshot` to accept `cmd_name`. |
| `cli/data/command.py` | Add `backfill_cmd` / `delist_cmd` / `rename_cmd` Typer subcommands with `--dry-run` flag. Add `--dry-run` to existing `download_cmd`. |
| `cli/data/verify.py` | No code changes (the `is_empty` and per-pair non-uniform `to` already work; iter-5 just exercises them more). |
| `tests/data_fixtures.py` | `FakeSource.add_pair` gains `status="TRADING"` kwarg; `exchange_info` stub returns the status in each symbol dict. |
| `README.md` | Append `data backfill` / `data delist` / `data rename` documentation to the `## Usage` section; document `--dry-run`; note status-aware behavior of `download` / `backfill`. |
| `docs/iterations-history.md` | Append iter-5 entry as the closeout commit. |

**Create (tests):**

| File | Responsibility |
| --- | --- |
| `tests/test_data_backfill.py` | `backfill_pipeline` happy / no-op / `--dry-run` / status=BREAK silently skipped / `TRADING` pair unreachable still errors. |
| `tests/test_data_delist.py` | `delist_pipeline` happy / front-trim / back-trim / refusal:not-in-index / refusal:last-pair / refusal:gap-creating / `--dry-run`. |
| `tests/test_data_rename.py` | `rename_pipeline` Variant 1 (no gap, with gap, refusals, `--dry-run`); Variant 2 (merge, `--dry-run`). |
| `tests/test_data_e2e.py` | Three end-to-end scenarios from spec Section "Testing strategy". |

**Extend (tests):**

| File | New tests |
| --- | --- |
| `tests/test_data_pipeline.py` | `find_available_range` (first / last / none); `validate_pairs_against_exchange` status routing; `_execute_mutation` harness unit tests (no-op, dry-run, marker-on-dry-run, recovery-before-verify). |
| `tests/test_data_command.py` | CLI smoke for `backfill` / `delist` / `rename` (help, `--dry-run`, parse errors). |

**Total files touched: 8 modified, 4 created. Test count target: ~155–170 (113 iter-4 baseline + 40–60 new).**

---

## Task ordering & dependencies

```
T1 harness scaffolding  ──┬──> T2 refactor download onto harness
                          │
T3 status field + validate routing ──┬──> T5 download Change C
T4 find_available_range  ────────────┘
                          ┌──────────────────────────────────────┐
T2 + T3 + T4 ────────────>│ T6 backfill                          │
                          │ T7 delist                            │
                          │ T8 rename Variant 1                  │
                          │ T9 rename Variant 2                  │
                          └──────────────────────────────────────┘
                                                                  │
                                                                  v
                                            T10 README + iterations-history closeout
```

Tasks 6–9 are mostly independent of each other after T2/T3/T4 ship; the orchestrator may sequence them in the listed order for review tractability. T1+T2 are the riskiest (largest impact on existing tests); they go first.

Each task has its own commit (or commits, for review-driven fixes). Per-commit `Reviewed-by:` trailers amended while local before push. Force-push allowed on this branch per `.claude/rules/commit-messages.md`.

---

## Task 1 — Mutation harness scaffolding

**Files:**

- Modify: `cli/data/pipeline.py` (add `_execute_mutation`, `Plan` Protocol, plus a no-op default `Plan` for tests)
- Create: `tests/test_data_pipeline.py` extension — new tests `test_execute_mutation_*`

**Concept:** Introduce the harness in isolation, before any pipeline uses it. Define the `Plan` Protocol and the `_execute_mutation` orchestration. Wire to a stub plan/apply for unit testing. No behavior change in existing commands.

### Steps

- [ ] **Step 1.1: Write the failing tests for the harness behavior**

Add to `tests/test_data_pipeline.py`:

```python
class _StubPlan:
    """Test-only Plan with controllable noop/summary."""

    def __init__(self, *, is_noop: bool = False, summary: str = "(stub)"):
        self.is_noop = is_noop
        self._summary = summary

    def dry_run_summary(self) -> str:
        return self._summary


def test_execute_mutation_pre_flight_fails_aborts_with_pipeline_error(tmp_path):
    """If verify_dataset returns ok=False (and is_empty=False), harness raises before plan_fn runs."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    # Partial / broken state: components without index.json
    (out / "calendars").mkdir()
    (out / "calendars" / "day.txt").write_text("2024-01-01\n")

    plan_fn = lambda d: pytest.fail("plan_fn must not be called on broken dataset")
    apply_fn = lambda d, s, p: pytest.fail("apply_fn must not be called")

    from cli.data.pipeline import _execute_mutation, PipelineError

    with pytest.raises(PipelineError, match=r"refusing to mutate"):
        _execute_mutation(out, "fakecmd", plan_fn, apply_fn, dry_run=False)


def test_execute_mutation_dry_run_with_marker_aborts(tmp_path):
    """Dry-run errors if a .commit-in-progress marker is present (recovery would mutate)."""
    out = tmp_path / "ds"
    out.mkdir(parents=True)
    (out / ".commit-in-progress").write_text("some-snapshot.tar.gz\n")

    from cli.data.pipeline import _execute_mutation, PipelineError

    with pytest.raises(PipelineError, match=r"commit-in-progress marker"):
        _execute_mutation(out, "fakecmd",
                          plan_fn=lambda d: _StubPlan(),
                          apply_fn=lambda d, s, p: None,
                          dry_run=True)


def test_execute_mutation_noop_no_snapshot_no_marker(tmp_path):
    """No-op plan → harness logs and returns; no snapshot, no marker, no staging dir."""
    out = tmp_path / "ds"
    # Empty dir is allowed (is_empty=True passes pre-flight)
    out.mkdir(parents=True)

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(out, "fakecmd",
                      plan_fn=lambda d: _StubPlan(is_noop=True),
                      apply_fn=lambda d, s, p: pytest.fail("apply must not be called"),
                      dry_run=False)
    assert not (out / ".snapshots").exists() or not list((out / ".snapshots").glob("*.tar.gz"))
    assert not (out / ".commit-in-progress").exists()
    assert not (out / ".staging").exists()


def test_execute_mutation_dry_run_prints_summary_no_side_effects(tmp_path, capsys):
    """--dry-run with a non-noop plan prints the summary; no snapshot."""
    out = tmp_path / "ds"
    out.mkdir(parents=True)

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(out, "fakecmd",
                      plan_fn=lambda d: _StubPlan(is_noop=False, summary="DRY-RUN: would do stuff"),
                      apply_fn=lambda d, s, p: pytest.fail("apply must not run under dry-run"),
                      dry_run=True)
    captured = capsys.readouterr()
    assert "DRY-RUN: would do stuff" in captured.out
    assert not (out / ".snapshots").exists() or not list((out / ".snapshots").glob("*.tar.gz"))


def test_execute_mutation_real_run_invokes_apply_and_commits(tmp_path):
    """Real run: apply_fn writes a minimal valid dataset into staging; harness commits it."""
    # We need a minimal staging-builder that produces a verify-clean state.
    # Build minimal index + calendars + instruments + features for ONE pair.
    out = tmp_path / "ds"
    out.mkdir(parents=True)

    import cli.data.config as _cfg
    from cli.data.qlib_writer import write_calendar, write_instruments, write_bin
    from cli.data.index import IndexData, CalendarEntry, PairEntry, PairIntervalEntry, FieldEntry, FileEntry, save_index, compute_sha256, utc_now_iso
    import datetime as dt

    def apply_minimal(out_dir, staging, plan):
        (staging / "calendars").mkdir(parents=True)
        write_calendar(staging / "calendars", [dt.date(2024, 1, 1)])
        (staging / "instruments").mkdir(parents=True)
        write_instruments(staging / "instruments", {"BTCUSDT": (dt.date(2024, 1, 1), dt.date(2024, 1, 1))})
        (staging / "features" / "btcusdt").mkdir(parents=True)
        for field in _cfg.FIELDS:
            path = staging / "features" / "btcusdt" / f"{field}.day.bin"
            write_bin(path, [1.0], start_index=0)
        # Minimal index
        files = []
        for field in _cfg.FIELDS:
            path = staging / "features" / "btcusdt" / f"{field}.day.bin"
            files.append(FieldEntry(field=field, file=FileEntry(
                path=f"features/btcusdt/{field}.day.bin",
                sha256=compute_sha256(path),
                size_bytes=path.stat().st_size,
                header_start_index=0,
            )))
        # ... (the test stub just needs a verify-clean index — actual fields vary)
        # Save plain dict-y index; details follow iter-4's existing save_index
        save_index(staging, IndexData(
            schema_version=1,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            calendar=CalendarEntry(
                interval="1d",
                dates_from="2024-01-01",
                dates_to="2024-01-01",
                file=FileEntry(
                    path="calendars/day.txt",
                    sha256=compute_sha256(staging / "calendars" / "day.txt"),
                    size_bytes=(staging / "calendars" / "day.txt").stat().st_size,
                    header_start_index=0,
                ),
            ),
            instruments_file=FileEntry(
                path="instruments/all.txt",
                sha256=compute_sha256(staging / "instruments" / "all.txt"),
                size_bytes=(staging / "instruments" / "all.txt").stat().st_size,
                header_start_index=0,
            ),
            pairs=[PairEntry(
                symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
                intervals={"1d": PairIntervalEntry(
                    interval="1d",
                    rows=1,
                    dates_from="2024-01-01",
                    dates_to="2024-01-01",
                    files=files,
                )},
            )],
        ))

    from cli.data.pipeline import _execute_mutation

    _execute_mutation(out, "fakecmd",
                      plan_fn=lambda d: _StubPlan(is_noop=False),
                      apply_fn=apply_minimal,
                      dry_run=False)

    assert (out / "index.json").exists()
    assert (out / "features" / "btcusdt").is_dir()
    # Snapshot exists and is named with cmd_name
    snaps = list((out / ".snapshots").glob("*-fakecmd.tar.gz"))
    assert len(snaps) == 1, f"expected one snapshot tagged with cmd_name, got {snaps}"
    # Marker cleaned up
    assert not (out / ".commit-in-progress").exists()
    assert not (out / ".staging").exists()
```

- [ ] **Step 1.2: Run the tests; expect failures (no `_execute_mutation` yet)**

```
uv run pytest tests/test_data_pipeline.py -k test_execute_mutation -v
```

Expected: 5 failures, all `ImportError: cannot import name '_execute_mutation' ...` or similar.

- [ ] **Step 1.3: Implement the harness in `cli/data/pipeline.py`**

Place near the top of the file (alongside `PipelineError`), before the existing public pipelines:

```python
from typing import Protocol, Callable

class Plan(Protocol):
    """Per-command plan dataclass shape. Each command defines its own
    concrete dataclass implementing this Protocol."""
    is_noop: bool

    def dry_run_summary(self) -> str: ...


def _execute_mutation(
    out_dir: Path,
    cmd_name: str,
    plan_fn: Callable[[Path], Plan],
    apply_fn: Callable[[Path, Path, Plan], None],
    *,
    dry_run: bool = False,
) -> None:
    """Shared mutation discipline: pre-flight (verify + recovery) → plan →
    no-op short-circuit → dry-run short-circuit → snapshot → marker → apply
    → post-verify → atomic commit → marker cleanup.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        _recover_from_interrupted_commit(out_dir)
    else:
        if (out_dir / _COMMIT_MARKER).exists():
            raise PipelineError(
                f"commit-in-progress marker present at {out_dir / _COMMIT_MARKER}; "
                "cannot dry-run until prior commit is recovered. "
                "Re-run without --dry-run to auto-recover."
            )

    pre = verify_dataset(out_dir)
    if not pre.ok:
        raise PipelineError(
            f"refusing to mutate {out_dir}: dataset is not in a verified state. "
            f"Problems: {pre.problems}. Resolve manually (restore from .snapshots/, "
            "or remove the orphan files) before re-running."
        )

    plan = plan_fn(out_dir)

    if plan.is_noop:
        msg = f"{cmd_name}: nothing to do"
        if dry_run:
            typer.echo(f"DRY-RUN: {msg}.")
        else:
            logger.info(msg)
        return

    if dry_run:
        typer.echo(plan.dry_run_summary())
        return

    staging = out_dir / ".staging"
    if staging.exists():
        _shutil.rmtree(staging)
    staging.mkdir()
    try:
        apply_fn(out_dir, staging, plan)
        post = verify_dataset(staging)
        if not post.ok:
            raise PipelineError(
                f"staging fails verify after apply: {post.problems}"
            )
        _commit_staging(out_dir, staging, cmd_name=cmd_name)
    finally:
        if staging.exists():
            _shutil.rmtree(staging)
```

Also extend `_commit_staging` and `create_snapshot` signatures to take `cmd_name`:

- `create_snapshot(out_dir, cmd_name)` already takes a command string in iter-4 (`"download"` hardcoded); now the caller passes through. **No signature change to `create_snapshot` itself** — just thread the value through.
- `_commit_staging(out_dir, staging, cmd_name="download")` adds a keyword arg, defaulting to `"download"` so the existing `download_pipeline` doesn't break before Task 2 lands the refactor. Internally, `create_snapshot(out_dir, cmd_name)` uses the threaded value.

Required imports (already present in iter-4): `typer`, `logger`, `_COMMIT_MARKER`, `_shutil` (alias of `shutil`), `verify_dataset`, `_recover_from_interrupted_commit`, `_commit_staging`, `PipelineError`.

- [ ] **Step 1.4: Run the tests; expect pass**

```
uv run pytest tests/test_data_pipeline.py -k test_execute_mutation -v
uv run pytest tests/ -q       # the existing 113 iter-4 tests must still pass
```

Expected: 5 new + 113 baseline = 118 pass.

- [ ] **Step 1.5: Commit**

```bash
git add cli/data/pipeline.py tests/test_data_pipeline.py
git commit -m "$(cat <<'CM'
feat(data): add mutation harness for shared commit discipline

Introduces _execute_mutation(out_dir, cmd_name, plan_fn, apply_fn, *,
dry_run) which encapsulates the recover → pre-flight verify → plan →
no-op short-circuit → dry-run short-circuit → snapshot → marker → apply
→ post-verify → commit discipline. Each future mutator (download,
backfill, delist, rename) plugs in a plan_fn + apply_fn pair.

create_snapshot already accepts a command name; _commit_staging gains a
keyword cmd_name (default "download") so iter-4's download_pipeline keeps
working until task 2 refactors it onto the harness.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

After review subagent approves, amend with `Reviewed-by: Claude Sonnet 4.6` trailer (per `.claude/rules/commit-messages.md`).

---

## Task 2 — Refactor `download_pipeline` onto the harness; add `--dry-run`

**Files:**

- Modify: `cli/data/pipeline.py` (split `download_pipeline` into `_download_plan`, `_download_apply`, and a thin closure)
- Modify: `cli/data/command.py` (add `--dry-run` flag to `download_cmd`)
- Add: `tests/test_data_pipeline.py` tests for `download --dry-run` and download no-op
- Add: `tests/test_data_command.py` tests for `--dry-run` CLI

**Concept:** Move the recover + verify + plan-vs-build separation into the harness shape, preserving all 113 iter-4 tests. The new `_download_plan` returns a `DownloadPlan` dataclass with `is_noop` set when `_resolve_ranges` produces empty per-pair ranges.

### Steps

- [ ] **Step 2.1: Write failing tests for download --dry-run and download no-op short-circuit**

Add to `tests/test_data_pipeline.py`:

```python
def test_download_no_op_skips_snapshot(tmp_path, capsys):
    """If pairs.txt + dates resolve to no fetches, download is a no-op: no snapshot, no commit."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    # First download
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))

    # Second download with same args — should be no-op
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5), src)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, \
        f"expected no new snapshot on no-op, got: before={snaps_before} after={snaps_after}"


def test_download_dry_run_prints_plan_no_mutation(tmp_path, capsys):
    """--dry-run skips snapshot, prints summary, leaves dataset untouched."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 5))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 5),
                      src, dry_run=True)

    # No dataset created
    assert not (out / "index.json").exists()
    assert not (out / ".snapshots").exists() or not list((out / ".snapshots").glob("*.tar.gz"))
    # Output captured
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out or "would" in captured.out.lower() or "BTCUSDT" in captured.out


def test_download_snapshot_filename_uses_download_cmd_name(tmp_path):
    """The snapshot tar.gz is named <stamp>-download.tar.gz, not just <stamp>.tar.gz."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")
    out = tmp_path / "ds"
    src = _seed_source(dt.date(2024, 1, 1), dt.date(2024, 1, 2))

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 2), src)
    snaps = list((out / ".snapshots").glob("*-download.tar.gz"))
    assert len(snaps) == 1
```

Add to `tests/test_data_command.py`:

```python
def test_data_download_dry_run_flag_accepted(tmp_path, monkeypatch):
    """`data download --dry-run` parses; calls download_pipeline with dry_run=True."""
    captured = {}

    def fake_download_pipeline(*args, dry_run=False, **kw):
        captured["dry_run"] = dry_run

    from cli.data import command as cmd_mod
    monkeypatch.setattr(cmd_mod, "download_pipeline", fake_download_pipeline)
    monkeypatch.setattr(cmd_mod, "BinanceSource", lambda: object())

    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\n")

    result = runner.invoke(app, ["data", "download", str(tmp_path / "ds"), str(pairs),
                                 "--from", "2024-01-01", "--to", "2024-01-02", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert captured["dry_run"] is True
```

- [ ] **Step 2.2: Run the failing tests**

```
uv run pytest tests/test_data_pipeline.py::test_download_no_op_skips_snapshot tests/test_data_pipeline.py::test_download_dry_run_prints_plan_no_mutation tests/test_data_pipeline.py::test_download_snapshot_filename_uses_download_cmd_name tests/test_data_command.py::test_data_download_dry_run_flag_accepted -v
```

Expected: failures (no `dry_run` kw on `download_pipeline`; no `--dry-run` Typer flag; iter-4 always snapshots).

- [ ] **Step 2.3: Refactor `download_pipeline`**

Replace the existing `download_pipeline` body with:

```python
from dataclasses import dataclass

@dataclass
class DownloadPlan:
    """Per-pair fetch plan for download / backfill (shared shape)."""
    per_pair: dict[str, _PerPair]           # symbol → (effective_from, effective_to, ...)
    new_calendar: list[dt.date]             # union of old + new dates
    is_noop: bool

    def dry_run_summary(self) -> str:
        if self.is_noop:
            return "DRY-RUN: download: nothing to do."
        lines = ["DRY-RUN: download plan:"]
        for sym, p in self.per_pair.items():
            n = (p.effective_to - p.effective_from).days + 1
            lines.append(f"  {sym}: {p.effective_from} → {p.effective_to} ({n} zips)")
        lines.append(f"Calendar would span {self.new_calendar[0]} → {self.new_calendar[-1]} ({len(self.new_calendar)} days).")
        return "\n".join(lines)


def _download_plan(
    out_dir: Path,
    pairs_file: Path,
    interval: str,
    arg_from: dt.date,
    arg_to: dt.date,
    source: Source,
) -> DownloadPlan:
    # The existing pre-flight checks: parse_pairs_file + validate_pairs_against_exchange + _resolve_ranges
    requested = parse_pairs_file(pairs_file)
    exchange_info = source.fetch_exchange_info()
    classified = validate_pairs_against_exchange(requested, exchange_info)
    # _resolve_ranges currently takes indexed pairs from the live dir:
    indexed = {}
    live_index = load_index(out_dir)
    if live_index is not None:
        for p in live_index.pairs:
            indexed[p.symbol] = p
    per_pair = _resolve_ranges(
        requested=requested,
        classified=classified,
        indexed_pairs=indexed,
        interval=interval,
        arg_from=arg_from,
        arg_to=arg_to,
        source=source,
        live_calendar=(live_index.calendar.dates_to if live_index else None),
    )
    is_noop = all(len(p.dates) == 0 for p in per_pair.values())
    # The new calendar is the union; for no-op it's just the existing one
    if is_noop and live_index is not None:
        new_cal = _calendar_dates_from_index(live_index)
    else:
        new_cal = _compute_new_calendar(per_pair, live_index)
    return DownloadPlan(per_pair=per_pair, new_calendar=new_cal, is_noop=is_noop)


def _download_apply(out_dir: Path, staging: Path, plan: DownloadPlan, source: Source, interval: str) -> None:
    # Existing fetch + build_staging logic
    fetched = _fetch_all_concurrent(source, plan.per_pair, interval,
                                    CliConstants.FETCH_CONCURRENCY)
    _build_staging(out_dir=out_dir, staging=staging,
                   per_pair=plan.per_pair, fetched=fetched,
                   new_calendar=plan.new_calendar)


def download_pipeline(
    out_dir: Path,
    pairs_file: Path,
    interval: str,
    arg_from: dt.date,
    arg_to: dt.date,
    source: Source,
    *,
    dry_run: bool = False,
) -> None:
    plan_fn = lambda d: _download_plan(d, pairs_file, interval, arg_from, arg_to, source)
    apply_fn = lambda d, s, p: _download_apply(d, s, p, source, interval)
    _execute_mutation(out_dir, "download", plan_fn, apply_fn, dry_run=dry_run)
```

(Where helpers `_compute_new_calendar`, `_calendar_dates_from_index` are tiny utilities extracted from the existing `_build_staging`/`load_index` flow. If they don't exist as separate functions today, factor them out as part of this task — keep them small.)

- [ ] **Step 2.4: Add `--dry-run` to `download_cmd` in `cli/data/command.py`**

```python
@data_app.command("download")
def download_cmd(
    out_dir: Path = typer.Argument(...),
    pairs_file: Path = typer.Argument(...),
    interval: str = typer.Option("1d", "--interval"),
    arg_from_str: str = typer.Option("2020-01-01", "--from", callback=_from_callback),
    arg_to_str: str = typer.Option(None, "--to", callback=_to_callback),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan without mutating the dataset."),
) -> None:
    arg_from = dt.date.fromisoformat(arg_from_str)
    arg_to = dt.date.fromisoformat(arg_to_str) if arg_to_str else (dt.date.today() - dt.timedelta(days=1))
    try:
        download_pipeline(out_dir, pairs_file, interval, arg_from, arg_to,
                          BinanceSource(), dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
```

- [ ] **Step 2.5: Run all tests**

```
uv run pytest -q
```

Expected: 113 baseline + ~4 new = ~117 passing. **Any iter-4 download test failing here is a refactor regression — must be debugged before commit.**

- [ ] **Step 2.6: Commit**

```bash
git add cli/data/pipeline.py cli/data/command.py tests/test_data_pipeline.py tests/test_data_command.py
git commit -m "$(cat <<'CM'
refactor(data): refactor download_pipeline onto mutation harness, add --dry-run

Splits download_pipeline into _download_plan and _download_apply; the
public function is now a thin closure around _execute_mutation. Adds the
no-op short-circuit (download with all date ranges empty no longer
snapshots an identical-content rebuild). Adds --dry-run to the CLI.

Snapshot file is now named <stamp>-download.tar.gz consistently via the
harness-threaded cmd_name (was already the case but is now load-bearing
for the multi-mutator world).

Regression net: all 113 iter-4 tests continue to pass.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

Amend `Reviewed-by:` after spec + code-quality review pass.

---

## Task 3 — Status field: FakeSource + validate_pairs_against_exchange

**Files:**

- Modify: `tests/data_fixtures.py` (status kwarg on `add_pair`; exchange_info returns status)
- Modify: `cli/data/pipeline.py` (`validate_pairs_against_exchange` returns status; classification dict shape changes)
- Add: `tests/test_data_pipeline.py` tests for status routing

### Steps

- [ ] **Step 3.1: Write failing tests for status routing**

```python
def test_validate_pairs_classifies_trading_pair(tmp_path):
    """A TRADING pair returns (base, quote, 'TRADING')."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")  # default status="TRADING"

    from cli.data.pipeline import validate_pairs_against_exchange
    classified = validate_pairs_against_exchange(["BTCUSDT"], src.fetch_exchange_info())
    assert classified == {"BTCUSDT": ("BTC", "USDT", "TRADING")}


def test_validate_pairs_classifies_break_pair():
    """A status=BREAK pair is returned with 'BREAK', not filtered out."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")

    from cli.data.pipeline import validate_pairs_against_exchange
    classified = validate_pairs_against_exchange(["MATICUSDT"], src.fetch_exchange_info())
    assert classified == {"MATICUSDT": ("MATIC", "USDT", "BREAK")}


def test_validate_pairs_unknown_symbol_errors():
    """An unknown symbol still errors (iter-4 behavior preserved)."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")

    from cli.data.pipeline import validate_pairs_against_exchange, PipelineError
    with pytest.raises(PipelineError, match=r"not in exchange|unknown"):
        validate_pairs_against_exchange(["XYZUSDT"], src.fetch_exchange_info())
```

- [ ] **Step 3.2: Run failing tests**

```
uv run pytest tests/test_data_pipeline.py -k test_validate_pairs_classifies -v
```

- [ ] **Step 3.3: Modify FakeSource**

`tests/data_fixtures.py`:

```python
def add_pair(self, symbol: str, base: str, quote: str, *, status: str = "TRADING") -> None:
    self._pairs[symbol] = {"baseAsset": base, "quoteAsset": quote, "status": status, "symbol": symbol}

def fetch_exchange_info(self) -> list[dict]:
    # Return a list of symbol dicts (matching Binance's exchangeInfo.symbols shape)
    return list(self._pairs.values())
```

(Adapt to the existing FakeSource internals; key insight is the `status` field flowing through.)

- [ ] **Step 3.4: Update `validate_pairs_against_exchange`**

Return type changes from `dict[str, tuple[str, str]]` to `dict[str, tuple[str, str, str]]` (base, quote, status). Update the iter-4 callers — there's currently only one in `_download_plan` (via `_resolve_ranges`); pass status forward.

```python
def validate_pairs_against_exchange(pairs: list[str], exchange_info: list[dict]) -> dict[str, tuple[str, str, str]]:
    by_symbol = {s["symbol"]: s for s in exchange_info}
    out = {}
    for sym in pairs:
        if sym not in by_symbol:
            raise PipelineError(f"{sym}: not in Binance exchangeInfo (unknown symbol)")
        s = by_symbol[sym]
        out[sym] = (s["baseAsset"], s["quoteAsset"], s.get("status", "TRADING"))
    return out
```

(Note: don't gate on status here — that's the caller's responsibility based on Change C/D semantics.)

- [ ] **Step 3.5: Run all tests**

```
uv run pytest -q
```

Expected: 117 baseline + 3 new = ~120 pass. Iter-4 callers must adapt to the new tuple shape — confirm `_resolve_ranges` still works.

- [ ] **Step 3.6: Commit**

```bash
git add tests/data_fixtures.py cli/data/pipeline.py tests/test_data_pipeline.py
git commit -m "$(cat <<'CM'
feat(data): make validate_pairs_against_exchange status-aware

Returns (base_asset, quote_asset, status) per symbol, with status read
from Binance exchangeInfo (TRADING / BREAK / HALT / etc.). Callers gate
on status to decide between "fetch up to arg_to" (TRADING) and "treat as
historical archive" (non-TRADING) — the gating logic itself lands in the
next two tasks (download + backfill).

FakeSource's add_pair gains a status kwarg (default TRADING) so tests can
model delisted pairs without network.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 4 — `find_available_range`

**Files:**

- Modify: `cli/data/pipeline.py` (add helper)
- Add: `tests/test_data_pipeline.py` tests

### Steps

- [ ] **Step 4.1: Write failing tests**

```python
def test_find_available_range_finds_first_and_last(tmp_path):
    """A pair with data on [2024-09-13, 2024-09-15] returns that exact range."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("POLUSDT", "POL", "USDT")
    for d in (dt.date(2024, 9, 13), dt.date(2024, 9, 14), dt.date(2024, 9, 15)):
        src.add_kline("POLUSDT", "1d", d)

    from cli.data.pipeline import find_available_range
    rng = find_available_range(src, "POLUSDT", "1d",
                               dt.date(2024, 9, 10), dt.date(2024, 9, 20))
    assert rng == (dt.date(2024, 9, 13), dt.date(2024, 9, 15))


def test_find_available_range_no_data_returns_none(tmp_path):
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # no add_kline calls

    from cli.data.pipeline import find_available_range
    assert find_available_range(src, "MATICUSDT", "1d",
                                dt.date(2020, 1, 1), dt.date(2024, 12, 31)) is None


def test_find_available_range_delisted_pair_finds_historical(tmp_path):
    """MATICUSDT-shaped case: data from 2020-01-01 to 2024-09-10, none after."""
    from tests.data_fixtures import FakeSource

    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    for d_range in [(dt.date(2020, 1, 1), dt.date(2020, 1, 5)),
                    (dt.date(2024, 9, 5), dt.date(2024, 9, 10))]:
        d = d_range[0]
        while d <= d_range[1]:
            src.add_kline("MATICUSDT", "1d", d)
            d += dt.timedelta(days=1)

    from cli.data.pipeline import find_available_range
    rng = find_available_range(src, "MATICUSDT", "1d",
                               dt.date(2019, 1, 1), dt.date(2025, 1, 1))
    assert rng[0] == dt.date(2020, 1, 1)
    assert rng[1] == dt.date(2024, 9, 10)
```

Note: the "delisted finds historical" test seeds two non-contiguous date clusters. `find_available_range`'s binary search assumes contiguous data; this test verifies the function still returns the bounding range. (Internal gaps surface elsewhere via `assert_no_internal_gaps`.)

- [ ] **Step 4.2: Run failing tests**

```
uv run pytest tests/test_data_pipeline.py -k test_find_available_range -v
```

- [ ] **Step 4.3: Implement `find_available_range`**

```python
def find_available_range(
    source: Source,
    symbol: str,
    interval: str,
    lo: dt.date,
    hi: dt.date,
) -> tuple[dt.date, dt.date] | None:
    """Two binary searches: first_available downward, last_available upward.
    Returns None if no zip exists in [lo, hi].
    """
    if lo > hi:
        return None
    # First, confirm something exists at any point. Probe lo, hi, midpoint.
    probes = [lo, hi, lo + (hi - lo) / 2]
    # Conceptually: if lo or hi has data, we have an anchor; otherwise probe a few points
    # within [lo, hi] to find SOMETHING. Production note: a fully linear-scan fallback
    # is acceptable here since this function is only called during pre-flight (one symbol).
    # Implementer: feel free to use a simpler O(N) scan if N is bounded (N = days in range);
    # the binary-search optimization matters mainly for find_first_available's hi-anchor case.

    # Practical implementation: reuse iter-4's find_first_available behavior:
    # 1) Find first_available via the same downward bisect from any known-present date.
    # 2) Find last_available via an upward bisect from the same anchor.

    # Step A: find an anchor — any date with data
    anchor = None
    if source.exists_kline(symbol, interval, hi):
        anchor = hi
    elif source.exists_kline(symbol, interval, lo):
        anchor = lo
    else:
        # Linear-ish scan via doubling intervals to find an anchor
        # (Or implement a full bisect — implementer chooses; document the choice.)
        cursor = lo
        while cursor <= hi:
            if source.exists_kline(symbol, interval, cursor):
                anchor = cursor
                break
            cursor += dt.timedelta(days=max(1, (hi - cursor).days // 16))
        if anchor is None:
            return None

    # Step B: bisect downward from anchor to find first_available
    first = _bisect_first_available(source, symbol, interval, lo, anchor)
    # Step C: bisect upward from anchor to find last_available
    last = _bisect_last_available(source, symbol, interval, anchor, hi)
    return (first, last)


def _bisect_first_available(source, symbol, interval, lo, anchor):
    """Anchor is known to have data; bisect leftward for the earliest available."""
    while lo < anchor:
        mid = lo + (anchor - lo) // 2
        if source.exists_kline(symbol, interval, mid):
            anchor = mid
        else:
            lo = mid + dt.timedelta(days=1)
    return anchor


def _bisect_last_available(source, symbol, interval, anchor, hi):
    """Anchor is known to have data; bisect rightward for the latest available."""
    while anchor < hi:
        mid = anchor + (hi - anchor + dt.timedelta(days=1)) // 2
        if source.exists_kline(symbol, interval, mid):
            anchor = mid
        else:
            hi = mid - dt.timedelta(days=1)
    return anchor
```

(Implementer note: there are subtleties around timedelta division and edge cases — write the bisect carefully and ensure the tests exercise lo==hi, single-day, and lo > hi.)

- [ ] **Step 4.4: Run all tests**

```
uv run pytest -q
```

- [ ] **Step 4.5: Commit**

```bash
git add cli/data/pipeline.py tests/test_data_pipeline.py
git commit -m "$(cat <<'CM'
feat(data): add find_available_range helper

Returns (first_available, last_available) within [lo, hi] via two bounded
binary searches. None when no zip exists in range. Powers download for
delisted pairs (next task) and rename's NEW first-archive probe.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 5 — Change C: `download` tolerates delisted pairs

**Files:**

- Modify: `cli/data/pipeline.py` (`_resolve_ranges` / `_download_plan` uses status + `find_available_range` for non-TRADING)
- Add: `tests/test_data_download.py` (or extend `test_data_pipeline.py`)

### Steps

- [ ] **Step 5.1: Write failing tests**

```python
def test_download_delisted_pair_fetches_historical_range(tmp_path):
    """MATICUSDT (status=BREAK) → download fetches its [first, last] archive, no extension to arg_to."""
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("MATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # Seed archive: data on 2020-01-01..2020-01-05 only
    for d in (dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(5)):
        src.add_kline("MATICUSDT", "1d", d)

    download_pipeline(out, pairs, "1d", dt.date(2019, 1, 1), dt.date(2024, 1, 1), src)

    report = verify_dataset(out)
    assert report.ok
    idx = load_index(out)
    pair = next(p for p in idx.pairs if p.symbol == "MATICUSDT")
    interval = pair.intervals["1d"]
    assert interval.dates_from == "2020-01-01"
    assert interval.dates_to == "2020-01-05"  # NOT arg_to


def test_download_mixed_trading_and_delisted_pairs_yields_non_uniform_to_dates(tmp_path):
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nMATICUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(10)):
        src.add_kline("BTCUSDT", "1d", d)
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(5)):
        src.add_kline("MATICUSDT", "1d", d)

    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dt.date(2024, 1, 10), src)
    idx = load_index(out)
    btc = next(p for p in idx.pairs if p.symbol == "BTCUSDT").intervals["1d"]
    mat = next(p for p in idx.pairs if p.symbol == "MATICUSDT").intervals["1d"]
    assert btc.dates_to == "2024-01-10"
    assert mat.dates_to == "2024-01-05"
```

- [ ] **Step 5.2: Run failing tests**

- [ ] **Step 5.3: Update `_resolve_ranges`**

In the "new pair" branch (pair not in indexed_pairs), gate on the classified status:

```python
if status == "TRADING":
    # iter-4 path: find_first_available(lo=arg_from, hi=arg_to), error if None
    first = find_first_available(source, sym, interval, arg_from, arg_to)
    if first is None:
        raise PipelineError(f"{sym}: no kline data available in [{arg_from}, {arg_to}]")
    eff_from, eff_to = first, arg_to
else:
    # Change C: non-TRADING → find available range, fetch [first, last]
    rng = find_available_range(source, sym, interval, arg_from, arg_to)
    if rng is None:
        raise PipelineError(f"{sym}: status={status} but no kline data in [{arg_from}, {arg_to}]")
    eff_from, eff_to = rng
    logger.info(f"{sym}: status={status} on Binance; fetching only historical archive "
                f"[{eff_from}..{eff_to}], no extension possible.")

per_pair[sym] = _PerPair(symbol=sym, base=base, quote=quote,
                        effective_from=eff_from, effective_to=eff_to,
                        dates=[eff_from + dt.timedelta(days=i)
                               for i in range((eff_to - eff_from).days + 1)])
```

For pairs already in the index (the "existing pair" branch), Change D handles status (next task). For this task only the "new pair" branch is updated.

- [ ] **Step 5.4: Run all tests**

- [ ] **Step 5.5: Commit**

```bash
git add cli/data/pipeline.py tests/test_data_download.py tests/test_data_pipeline.py
git commit -m "$(cat <<'CM'
feat(data): download tolerates delisted pairs (status-aware new-pair branch)

For new pairs (not in index), the resolve-ranges step now routes on the
classified Binance status: TRADING keeps iter-4 semantics (fetch up to
--to with the original truncation guard); non-TRADING (BREAK, HALT, ...)
uses find_available_range to fetch only the historical archive [first,
last] and logs an info line that no further extension is possible.

Datasets can now contain pairs with non-uniform `to` dates — verify
already accepts this (per-pair ranges are independent in index.json).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 6 — `backfill_pipeline` + CLI

**Files:**

- Modify: `cli/data/pipeline.py` (add `_backfill_plan`, `_backfill_apply`, `backfill_pipeline`)
- Modify: `cli/data/command.py` (add `backfill_cmd`)
- Create: `tests/test_data_backfill.py`
- Modify: `tests/test_data_command.py` (CLI smoke for backfill)

### Steps

- [ ] **Step 6.1: Write failing tests in `tests/test_data_backfill.py`**

```python
import datetime as dt
import pytest
from pathlib import Path

from cli.data.pipeline import backfill_pipeline, PipelineError
from cli.data.verify import verify_dataset
from cli.data.index import load_index
from tests.data_fixtures import FakeSource


def _bootstrap_two_pairs(tmp_path, dates_through):
    """Seed BTCUSDT + ETHUSDT in a dataset through `dates_through`."""
    from cli.data.pipeline import download_pipeline
    pairs = tmp_path / "pairs.txt"
    pairs.write_text("BTCUSDT\nETHUSDT\n")
    out = tmp_path / "ds"
    src = FakeSource()
    src.add_pair("BTCUSDT", "BTC", "USDT")
    src.add_pair("ETHUSDT", "ETH", "USDT")
    for d in (dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range((dates_through - dt.date(2024, 1, 1)).days + 1)):
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    download_pipeline(out, pairs, "1d", dt.date(2024, 1, 1), dates_through, src)
    return out, src


def test_backfill_happy_extends_to_yesterday(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    # Add 3 more days on source
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7), dt.date(2024, 1, 8)):
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    backfill_pipeline(out, "1d", dt.date(2024, 1, 8), src)
    idx = load_index(out)
    assert all(p.intervals["1d"].dates_to == "2024-01-08" for p in idx.pairs)


def test_backfill_noop_when_all_pairs_caught_up_no_snapshot(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    backfill_pipeline(out, "1d", dt.date(2024, 1, 5), src)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "no-op backfill must not write a snapshot"


def test_backfill_silently_skips_break_status_pair(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    # Flip BTCUSDT to BREAK on the source
    src._pairs["BTCUSDT"]["status"] = "BREAK"
    # Add new days only for ETHUSDT
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7)):
        src.add_kline("ETHUSDT", "1d", d)
    backfill_pipeline(out, "1d", dt.date(2024, 1, 7), src)
    idx = load_index(out)
    btc = next(p for p in idx.pairs if p.symbol == "BTCUSDT").intervals["1d"]
    eth = next(p for p in idx.pairs if p.symbol == "ETHUSDT").intervals["1d"]
    assert btc.dates_to == "2024-01-05", "BREAK pair must not have been extended"
    assert eth.dates_to == "2024-01-07", "TRADING pair extends normally"


def test_backfill_trading_pair_unreachable_raises_pipeline_error(tmp_path):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    # No new klines added on the source; BTCUSDT is still TRADING.
    # backfill --to 2024-01-08 expects to fetch 2024-01-06..2024-01-08, but they're not on FakeSource.
    with pytest.raises(PipelineError, match=r"not available|404|fetch failed|reachable"):
        backfill_pipeline(out, "1d", dt.date(2024, 1, 8), src)


def test_backfill_dry_run_prints_plan_no_mutation(tmp_path, capsys):
    out, src = _bootstrap_two_pairs(tmp_path, dt.date(2024, 1, 5))
    for d in (dt.date(2024, 1, 6), dt.date(2024, 1, 7)):
        src.add_kline("BTCUSDT", "1d", d)
        src.add_kline("ETHUSDT", "1d", d)
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    backfill_pipeline(out, "1d", dt.date(2024, 1, 7), src, dry_run=True)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after, "dry-run must not snapshot"
    captured = capsys.readouterr()
    assert "BTCUSDT" in captured.out or "DRY-RUN" in captured.out
```

- [ ] **Step 6.2: Run failing tests**

- [ ] **Step 6.3: Implement `_backfill_plan` / `_backfill_apply` / `backfill_pipeline`**

```python
@dataclass
class BackfillPlan:
    per_pair: dict[str, _PerPair]
    new_calendar: list[dt.date]
    skipped_pairs: list[tuple[str, str]]  # (symbol, status) for logged skips
    is_noop: bool

    def dry_run_summary(self) -> str:
        if self.is_noop:
            return "DRY-RUN: backfill: nothing to do."
        lines = ["DRY-RUN: backfill plan:"]
        for sym, p in self.per_pair.items():
            n = (p.effective_to - p.effective_from).days + 1
            lines.append(f"  {sym}: {p.effective_from} → {p.effective_to} ({n} zips)")
        for sym, status in self.skipped_pairs:
            lines.append(f"  {sym}: skipped (status={status})")
        return "\n".join(lines)


def _backfill_plan(
    out_dir: Path,
    interval: str,
    arg_to: dt.date,
    source: Source,
) -> BackfillPlan:
    idx = load_index(out_dir)
    if idx is None or not idx.pairs:
        raise PipelineError("no pairs in index; use 'data download' first to seed the dataset")

    exchange_info = source.fetch_exchange_info()
    classified = validate_pairs_against_exchange([p.symbol for p in idx.pairs], exchange_info)

    per_pair = {}
    skipped = []
    for p in idx.pairs:
        sym = p.symbol
        base, quote, status = classified[sym]
        if status != "TRADING":
            skipped.append((sym, status))
            logger.info(f"{sym}: status={status} on Binance; nothing to extend.")
            continue
        # TRADING — extend if needed
        index_to = dt.date.fromisoformat(p.intervals[interval].dates_to)
        eff_from = index_to + dt.timedelta(days=1)
        if eff_from > arg_to:
            continue  # already at or past arg_to
        # Right-edge reachability (iter-4 behavior, raises on unreachable)
        if not source.exists_kline(sym, interval, arg_to):
            raise PipelineError(
                f"{sym}: existing pair is not available on Binance at {arg_to} "
                f"(likely delisted or the ticker was renamed mid-window). Reconcile with "
                f"`zcrypto data delist` or `zcrypto data rename` before re-running backfill."
            )
        per_pair[sym] = _PerPair(symbol=sym, base=base, quote=quote,
                                effective_from=eff_from, effective_to=arg_to,
                                dates=[eff_from + dt.timedelta(days=i)
                                       for i in range((arg_to - eff_from).days + 1)])

    is_noop = not per_pair
    new_cal = _calendar_dates_from_index(idx) if is_noop else _compute_new_calendar(per_pair, idx)
    return BackfillPlan(per_pair=per_pair, new_calendar=new_cal, skipped_pairs=skipped, is_noop=is_noop)


def _backfill_apply(out_dir, staging, plan: BackfillPlan, source: Source, interval: str) -> None:
    if not plan.per_pair:
        return  # defensive; harness's no-op short-circuit should have caught this
    fetched = _fetch_all_concurrent(source, plan.per_pair, interval,
                                    CliConstants.FETCH_CONCURRENCY)
    # Reuse iter-4's _build_staging — needs to include unchanged pairs (skipped + caught-up)
    # by reading their existing data from the live dir.
    _build_staging(out_dir=out_dir, staging=staging,
                   per_pair=plan.per_pair, fetched=fetched,
                   new_calendar=plan.new_calendar)


def backfill_pipeline(
    out_dir: Path,
    interval: str,
    arg_to: dt.date,
    source: Source,
    *,
    dry_run: bool = False,
) -> None:
    plan_fn = lambda d: _backfill_plan(d, interval, arg_to, source)
    apply_fn = lambda d, s, p: _backfill_apply(d, s, p, source, interval)
    _execute_mutation(out_dir, "backfill", plan_fn, apply_fn, dry_run=dry_run)
```

- [ ] **Step 6.4: Add CLI**

```python
@data_app.command("backfill")
def backfill_cmd(
    out_dir: Path = typer.Argument(...),
    interval: str = typer.Option("1d", "--interval"),
    arg_to_str: str = typer.Option(None, "--to", callback=_to_callback),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    arg_to = dt.date.fromisoformat(arg_to_str) if arg_to_str else (dt.date.today() - dt.timedelta(days=1))
    try:
        backfill_pipeline(out_dir, interval, arg_to, BinanceSource(), dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
```

- [ ] **Step 6.5: Run all tests**

- [ ] **Step 6.6: Commit**

```bash
git add cli/data/pipeline.py cli/data/command.py tests/test_data_backfill.py tests/test_data_command.py
git commit -m "$(cat <<'CM'
feat(data): add `data backfill` command

Per-pair status-aware extension of every pair in index to --to (default
yesterday UTC). TRADING pairs use iter-4's right-edge reachability check
and fetch the new range; non-TRADING pairs (BREAK/HALT/etc.) are silently
skipped with an info log. When every pair is caught up or skipped, the
harness's no-op short-circuit fires — no snapshot, no commit.

CLI accepts --to and --dry-run; pre-flight verify must pass before any
mutation (PipelineError on partial/broken state).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 7 — `delist_pipeline` + CLI

**Files:**

- Modify: `cli/data/pipeline.py` (add `_delist_plan`, `_delist_apply`, `delist_pipeline`)
- Modify: `cli/data/command.py` (`delist_cmd`)
- Create: `tests/test_data_delist.py`
- Modify: `tests/test_data_command.py`

### Steps

- [ ] **Step 7.1: Write failing tests**

```python
def test_delist_happy_no_calendar_trim(tmp_path):
    """3 pairs, all sharing [2024-01-01..2024-01-05]. Removing one leaves the calendar intact."""
    out = _seed_three_pairs(tmp_path, dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    src = FakeSource()  # not needed for delist; pass through
    delist_pipeline(out, "BTCUSDT", source=src)
    idx = load_index(out)
    assert {p.symbol for p in idx.pairs} == {"ETHUSDT", "SOLUSDT"}
    cal = (out / "calendars" / "day.txt").read_text().strip().splitlines()
    assert cal[0] == "2024-01-01" and cal[-1] == "2024-01-05"


def test_delist_front_trim_when_removed_pair_uniquely_covers_earliest_dates(tmp_path):
    """BTC has 2024-01-01..2024-01-05, ETH has 2024-01-03..2024-01-05. Remove BTC → calendar shrinks to 2024-01-03..2024-01-05."""
    out = _seed_ragged_left(tmp_path)
    delist_pipeline(out, "BTCUSDT", source=FakeSource())
    cal = (out / "calendars" / "day.txt").read_text().strip().splitlines()
    assert cal[0] == "2024-01-03"
    # ETH's bin's start_index header now points to position 0 in the new calendar
    idx = load_index(out)
    eth = next(p for p in idx.pairs if p.symbol == "ETHUSDT").intervals["1d"]
    for f in eth.files:
        assert f.file.header_start_index == 0


def test_delist_refuses_not_in_index(tmp_path):
    out = _seed_three_pairs(tmp_path, dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    with pytest.raises(PipelineError, match=r"not in index"):
        delist_pipeline(out, "XYZUSDT", source=FakeSource())


def test_delist_refuses_last_pair(tmp_path):
    out = _seed_one_pair(tmp_path)
    with pytest.raises(PipelineError, match=r"would leave .* empty"):
        delist_pipeline(out, "BTCUSDT", source=FakeSource())


def test_delist_dry_run_prints_plan_no_mutation(tmp_path, capsys):
    out = _seed_three_pairs(tmp_path, dt.date(2024, 1, 1), dt.date(2024, 1, 5))
    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    delist_pipeline(out, "BTCUSDT", source=FakeSource(), dry_run=True)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after
    captured = capsys.readouterr()
    assert "BTCUSDT" in captured.out
    # Index unchanged
    idx = load_index(out)
    assert "BTCUSDT" in {p.symbol for p in idx.pairs}
```

(Helpers `_seed_three_pairs`, `_seed_ragged_left`, `_seed_one_pair` are small test-fixture utilities sharing the existing `download_pipeline` to bootstrap. Implementer writes them once.)

- [ ] **Step 7.2: Run failing tests**

- [ ] **Step 7.3: Implement `_delist_plan`**

```python
@dataclass
class DelistPlan:
    symbol: str
    new_calendar: list[dt.date]
    front_trim: int
    back_trim: int
    rewrite_headers: bool
    remaining_symbols: list[str]
    is_noop: bool

    def dry_run_summary(self) -> str:
        lines = [f"DRY-RUN: delist plan: {self.symbol}"]
        lines.append(f"  features/{self.symbol.lower()}/ → deleted")
        lines.append(f"  instruments/all.txt → 1 line removed")
        lines.append(f"  index.json → 1 pair entry removed")
        lines.append(f"  calendar: front_trim={self.front_trim}, back_trim={self.back_trim}")
        if self.rewrite_headers:
            lines.append(f"  Remaining bins: headers rewritten (subtract {self.front_trim} from each start_index)")
        else:
            lines.append(f"  Remaining bins: unchanged")
        lines.append(f"  Remaining pairs: {len(self.remaining_symbols)} ({', '.join(self.remaining_symbols)})")
        return "\n".join(lines)


def _delist_plan(out_dir: Path, symbol: str) -> DelistPlan:
    idx = load_index(out_dir)
    assert idx is not None
    sym = symbol.upper()
    if sym not in {p.symbol for p in idx.pairs}:
        raise PipelineError(f"{sym} not in index; nothing to remove")
    remaining = [p for p in idx.pairs if p.symbol != sym]
    if not remaining:
        raise PipelineError(
            f"delisting {sym} would leave the dataset empty; remove {out_dir} manually if that's intended"
        )
    # Compute new calendar bounds from remaining instruments
    interval = "1d"  # iter-5 only supports 1d
    new_from = min(dt.date.fromisoformat(p.intervals[interval].dates_from) for p in remaining)
    new_to = max(dt.date.fromisoformat(p.intervals[interval].dates_to) for p in remaining)
    # Refuse on gap-creating: every date in [new_from, new_to] must be covered by at least one remaining pair
    cur = new_from
    while cur <= new_to:
        covers = any(
            dt.date.fromisoformat(p.intervals[interval].dates_from) <= cur <= dt.date.fromisoformat(p.intervals[interval].dates_to)
            for p in remaining
        )
        if not covers:
            raise PipelineError(
                f"delisting {sym} would create a non-contiguous calendar (no remaining pair covers {cur}); "
                "reconcile manually before delisting"
            )
        cur += dt.timedelta(days=1)
    old_cal_dates = _calendar_dates_from_index(idx)
    front_trim = (new_from - old_cal_dates[0]).days
    back_trim = (old_cal_dates[-1] - new_to).days
    new_cal = [new_from + dt.timedelta(days=i) for i in range((new_to - new_from).days + 1)]
    return DelistPlan(
        symbol=sym, new_calendar=new_cal,
        front_trim=front_trim, back_trim=back_trim,
        rewrite_headers=(front_trim > 0),
        remaining_symbols=[p.symbol for p in remaining],
        is_noop=False,
    )
```

- [ ] **Step 7.4: Implement `_delist_apply`**

```python
def _delist_apply(out_dir: Path, staging: Path, plan: DelistPlan) -> None:
    # Copy remaining pairs' bins; optionally rewrite headers
    (staging / "features").mkdir(parents=True)
    idx = load_index(out_dir)
    for p in idx.pairs:
        if p.symbol == plan.symbol:
            continue
        src_dir = out_dir / "features" / p.symbol.lower()
        dst_dir = staging / "features" / p.symbol.lower()
        _shutil.copytree(src_dir, dst_dir)
        if plan.rewrite_headers:
            for field_path in dst_dir.iterdir():
                _rewrite_bin_start_index(field_path, -plan.front_trim)
    # Write new calendar
    (staging / "calendars").mkdir(parents=True)
    write_calendar(staging / "calendars", plan.new_calendar)
    # Write new instruments
    (staging / "instruments").mkdir(parents=True)
    write_instruments(staging / "instruments", {
        p.symbol: (
            dt.date.fromisoformat(p.intervals["1d"].dates_from),
            dt.date.fromisoformat(p.intervals["1d"].dates_to),
        )
        for p in idx.pairs if p.symbol != plan.symbol
    })
    # Write new index — drop the symbol, recompute file metadata for remaining pairs
    _write_index_from_staging(staging, removed_pair=plan.symbol, original_index=idx, header_shift=-plan.front_trim if plan.rewrite_headers else 0)


def _rewrite_bin_start_index(bin_path: Path, delta: int) -> None:
    """Read first 4 bytes (float32 header), adjust by delta, write back."""
    import struct
    data = bytearray(bin_path.read_bytes())
    current = struct.unpack_from("<f", data, 0)[0]
    new = current + delta
    struct.pack_into("<f", data, 0, float(new))
    bin_path.write_bytes(bytes(data))
```

(Implementer note: `_write_index_from_staging` is a small helper that builds a fresh `IndexData` from what's on disk in staging — basically a rebuild step. Can reuse the existing index-building logic from `_build_staging`.)

- [ ] **Step 7.5: Add `delist_pipeline` + CLI**

```python
def delist_pipeline(
    out_dir: Path,
    symbol: str,
    *,
    source: Source | None = None,  # unused; kept for harness signature uniformity if useful
    dry_run: bool = False,
) -> None:
    plan_fn = lambda d: _delist_plan(d, symbol)
    apply_fn = lambda d, s, p: _delist_apply(d, s, p)
    _execute_mutation(out_dir, "delist", plan_fn, apply_fn, dry_run=dry_run)


@data_app.command("delist")
def delist_cmd(
    out_dir: Path = typer.Argument(...),
    symbol: str = typer.Argument(..., callback=lambda s: s.upper()),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        delist_pipeline(out_dir, symbol, dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
```

- [ ] **Step 7.6: Run all tests**

- [ ] **Step 7.7: Commit**

```bash
git add cli/data/pipeline.py cli/data/command.py tests/test_data_delist.py tests/test_data_command.py
git commit -m "$(cat <<'CM'
feat(data): add `data delist` command with conditional calendar shrink

Removes SYMBOL from the dataset under the snapshot+commit discipline.
Refuses on not-in-index, last-pair (would empty the dataset), and
gap-creating (calendar union becomes non-contiguous).

Calendar handling: conditional shrink. If the removed pair was the
unique cover for the earliest dates, trim the front; rewrite every
remaining bin's start_index header by subtracting front_trim. If the
removed pair was the unique cover for the latest dates, trim the back;
remaining bin headers unchanged. If both, both. If neither, calendar
unchanged.

--dry-run previews the plan with the exact trim/rewrite counts.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 8 — `rename_pipeline` Variant 1 (single rename + gap fill)

**Files:**

- Modify: `cli/data/pipeline.py` (`_rename_plan`, `_rename_apply` for Variant 1 only; Variant 2 stubbed/raised)
- Modify: `cli/data/command.py` (`rename_cmd`)
- Create: `tests/test_data_rename.py`
- Modify: `tests/test_data_command.py`

### Steps

- [ ] **Step 8.1: Write failing tests for Variant 1**

```python
def test_rename_v1_no_gap_consecutive_days(tmp_path):
    """OLD ends 2024-09-10, NEW starts 2024-09-11 → no synthetic fill, simple rename."""
    out = _seed_one_pair_ending(tmp_path, "MATICUSDT", dt.date(2024, 9, 10))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    for d in (dt.date(2024, 9, 11) + dt.timedelta(days=i) for i in range(3)):
        src.add_kline("POLUSDT", "1d", d)

    rename_pipeline(out, "MATICUSDT", "POLUSDT", src)
    idx = load_index(out)
    assert "MATICUSDT" not in {p.symbol for p in idx.pairs}
    assert "POLUSDT" in {p.symbol for p in idx.pairs}
    pol = next(p for p in idx.pairs if p.symbol == "POLUSDT").intervals["1d"]
    assert pol.dates_to == "2024-09-10"  # no extension; the rename only re-labels
    assert (out / "features" / "polusdt").is_dir()
    assert not (out / "features" / "maticusdt").exists()


def test_rename_v1_with_gap_fills_zero_volume(tmp_path):
    """OLD ends 2024-09-10, NEW first archive day = 2024-09-13 → 2 synthetic days."""
    out = _seed_one_pair_ending(tmp_path, "MATICUSDT", dt.date(2024, 9, 10))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    for d in (dt.date(2024, 9, 13) + dt.timedelta(days=i) for i in range(3)):
        src.add_kline("POLUSDT", "1d", d)

    # Capture OLD's 2024-09-10 close before rename
    from cli.data.qlib_writer import read_bin
    old_close_bin = out / "features" / "maticusdt" / "close.day.bin"
    _, old_closes = read_bin(old_close_bin)
    locked_value = old_closes[-1]

    rename_pipeline(out, "MATICUSDT", "POLUSDT", src)

    new_close_bin = out / "features" / "polusdt" / "close.day.bin"
    _, new_closes = read_bin(new_close_bin)
    # Two synthetic values appended; both equal locked_value
    assert new_closes[-2] == pytest.approx(locked_value)
    assert new_closes[-1] == pytest.approx(locked_value)
    # Volume bin: two zero values appended
    _, vols = read_bin(out / "features" / "polusdt" / "volume.day.bin")
    assert vols[-2] == pytest.approx(0.0)
    assert vols[-1] == pytest.approx(0.0)
    # Factor bin: two 1.0 values appended
    _, factors = read_bin(out / "features" / "polusdt" / "factor.day.bin")
    assert factors[-2] == pytest.approx(1.0)
    assert factors[-1] == pytest.approx(1.0)
    # Pair's `to` = 2024-09-12 (the day before NEW's first archive day)
    idx = load_index(out)
    pol = next(p for p in idx.pairs if p.symbol == "POLUSDT").intervals["1d"]
    assert pol.dates_to == "2024-09-12"


def test_rename_v1_refuses_old_not_in_index(tmp_path):
    out = _seed_one_pair_ending(tmp_path, "BTCUSDT", dt.date(2024, 1, 5))
    src = FakeSource()
    src.add_pair("XYZUSDT", "XYZ", "USDT")
    with pytest.raises(PipelineError, match=r"not in index"):
        rename_pipeline(out, "MATICUSDT", "XYZUSDT", src)


def test_rename_v1_refuses_new_not_in_exchange_info(tmp_path):
    out = _seed_one_pair_ending(tmp_path, "MATICUSDT", dt.date(2024, 9, 10))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    # POLUSDT not added to FakeSource
    with pytest.raises(PipelineError, match=r"not found on Binance"):
        rename_pipeline(out, "MATICUSDT", "POLUSDT", src)


def test_rename_v1_refuses_new_no_archive_yet(tmp_path):
    """NEW is in exchangeInfo but has no archive days yet (operator ran rename too early)."""
    out = _seed_one_pair_ending(tmp_path, "MATICUSDT", dt.date(2024, 9, 10))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")  # no add_kline calls
    with pytest.raises(PipelineError, match=r"no daily archive available yet"):
        rename_pipeline(out, "MATICUSDT", "POLUSDT", src)


def test_rename_v1_dry_run_prints_plan_no_mutation(tmp_path, capsys):
    out = _seed_one_pair_ending(tmp_path, "MATICUSDT", dt.date(2024, 9, 10))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    for d in (dt.date(2024, 9, 13) + dt.timedelta(days=i) for i in range(3)):
        src.add_kline("POLUSDT", "1d", d)

    snaps_before = sorted((out / ".snapshots").glob("*.tar.gz"))
    rename_pipeline(out, "MATICUSDT", "POLUSDT", src, dry_run=True)
    snaps_after = sorted((out / ".snapshots").glob("*.tar.gz"))
    assert snaps_before == snaps_after
    captured = capsys.readouterr()
    assert "MATICUSDT" in captured.out and "POLUSDT" in captured.out
    # No mutation
    assert (out / "features" / "maticusdt").is_dir()
```

- [ ] **Step 8.2: Run failing tests**

- [ ] **Step 8.3: Implement `_rename_plan` (V1 only, V2 raises)**

```python
@dataclass
class RenamePlan:
    variant: int                      # 1 or 2
    old_symbol: str
    new_symbol: str
    new_base_asset: str
    new_quote_asset: str
    new_first: dt.date
    new_to: dt.date                   # the renamed pair's index.to after fill
    gap_dates: list[dt.date]
    synthetic_locked_ohlc: float
    is_noop: bool

    def dry_run_summary(self) -> str:
        lines = [f"DRY-RUN: rename plan ({self.old_symbol} → {self.new_symbol}, variant {self.variant})"]
        if self.gap_dates:
            lines.append(f"  Gap: {len(self.gap_dates)} days ({self.gap_dates[0]}..{self.gap_dates[-1]})")
            lines.append(f"  Synthetic fill: zero-volume, OHLC locked at {self.synthetic_locked_ohlc:.6f}")
        else:
            lines.append(f"  Gap: none (consecutive days)")
        lines.append(f"  features/{self.old_symbol.lower()}/ → features/{self.new_symbol.lower()}/")
        lines.append(f"  index.json: base {self.new_base_asset}; quote {self.new_quote_asset}; to={self.new_to}")
        return "\n".join(lines)


def _rename_plan(out_dir: Path, old_symbol: str, new_symbol: str, source: Source) -> RenamePlan:
    idx = load_index(out_dir)
    assert idx is not None
    old_sym = old_symbol.upper()
    new_sym = new_symbol.upper()
    if old_sym == new_sym:
        raise PipelineError("old_symbol equals new_symbol; no change requested")
    pair_syms = {p.symbol for p in idx.pairs}
    if old_sym not in pair_syms:
        raise PipelineError(f"{old_sym} not in index; nothing to rename")
    variant = 2 if new_sym in pair_syms else 1

    # exchangeInfo lookup for NEW
    exchange_info = source.fetch_exchange_info()
    new_entry = next((s for s in exchange_info if s["symbol"] == new_sym), None)
    if new_entry is None:
        raise PipelineError(f"{new_sym} not found on Binance (exchangeInfo); not a valid symbol")
    new_base, new_quote = new_entry["baseAsset"], new_entry["quoteAsset"]

    # OLD's index.to + last close
    old_pair = next(p for p in idx.pairs if p.symbol == old_sym).intervals["1d"]
    old_to = dt.date.fromisoformat(old_pair.dates_to)
    # Read OLD's last close
    from cli.data.qlib_writer import read_bin
    _, closes = read_bin(out_dir / "features" / old_sym.lower() / "close.day.bin")
    synth_locked = float(closes[-1])

    # Determine new_first
    if variant == 1:
        rng = find_available_range(source, new_sym, "1d", old_to + dt.timedelta(days=1),
                                   dt.date.today() - dt.timedelta(days=1))
        if rng is None:
            raise PipelineError(
                f"{new_sym} has no daily archive available on data.binance.vision yet "
                "(likely too early after listing). Try again tomorrow."
            )
        new_first = rng[0]
    else:
        new_pair = next(p for p in idx.pairs if p.symbol == new_sym).intervals["1d"]
        new_first = dt.date.fromisoformat(new_pair.dates_from)

    # Overlap sanity
    if new_first <= old_to:
        raise PipelineError(
            f"rename has overlapping data: {old_sym} ends {old_to} but {new_sym} starts {new_first}; "
            "manual resolution required"
        )

    gap_dates = [old_to + dt.timedelta(days=i) for i in range(1, (new_first - old_to).days)]
    new_to = new_first - dt.timedelta(days=1)

    if len(gap_dates) > CliConstants.RENAME_SYNTH_WARN_DAYS:
        logger.warning(
            f"rename: synthesizing {len(gap_dates)} (>{CliConstants.RENAME_SYNTH_WARN_DAYS}) "
            f"zero-volume days from {gap_dates[0]} to {gap_dates[-1]} — verify intentional."
        )
    elif gap_dates:
        logger.warning(
            f"rename: synthesizing {len(gap_dates)} zero-volume days "
            f"from {gap_dates[0]} to {gap_dates[-1]} to bridge {old_sym} (ends {old_to}) → {new_sym} "
            f"(starts {new_first}). Locked OHLC = {synth_locked:.6f}."
        )

    return RenamePlan(
        variant=variant, old_symbol=old_sym, new_symbol=new_sym,
        new_base_asset=new_base, new_quote_asset=new_quote,
        new_first=new_first, new_to=new_to,
        gap_dates=gap_dates, synthetic_locked_ohlc=synth_locked,
        is_noop=False,
    )
```

Add `CliConstants.RENAME_SYNTH_WARN_DAYS = 7` to `cli/constants.py`.

- [ ] **Step 8.4: Implement `_rename_apply` for Variant 1**

Variant 2 logic stubbed: `raise NotImplementedError("rename Variant 2 lands in Task 9")` initially, so Task 8 can ship and test Variant 1 in isolation.

```python
def _rename_apply(out_dir: Path, staging: Path, plan: RenamePlan) -> None:
    if plan.variant == 2:
        raise NotImplementedError("rename Variant 2 lands in Task 9")
    _rename_apply_variant1(out_dir, staging, plan)


def _rename_apply_variant1(out_dir: Path, staging: Path, plan: RenamePlan) -> None:
    # Copy unchanged components
    _shutil.copytree(out_dir / "calendars", staging / "calendars")
    # Update instruments: replace OLD's line with NEW
    # ... read live, rewrite ...
    # Copy all features dirs except OLD; rename OLD → NEW; if gap, extend bins
    (staging / "features").mkdir(parents=True)
    for sub in (out_dir / "features").iterdir():
        if sub.name == plan.old_symbol.lower():
            dst = staging / "features" / plan.new_symbol.lower()
            _shutil.copytree(sub, dst)
            if plan.gap_dates:
                _extend_bins_with_synthetic(dst, plan)
        else:
            _shutil.copytree(sub, staging / "features" / sub.name)
    # Recompute and write new index
    # ...


def _extend_bins_with_synthetic(features_dir: Path, plan: RenamePlan) -> None:
    """Append len(plan.gap_dates) synthetic values to each of the 11 field bins."""
    import struct
    n = len(plan.gap_dates)
    for field in _cfg.FIELDS:
        bin_path = features_dir / f"{field}.day.bin"
        synth_value = _synthetic_value(field, plan.synthetic_locked_ohlc)
        data = bytearray(bin_path.read_bytes())
        data.extend(struct.pack("<f", float(synth_value)) * n)
        bin_path.write_bytes(bytes(data))


def _synthetic_value(field: str, locked_ohlc: float) -> float:
    if field in ("open", "high", "low", "close", "vwap"):
        return locked_ohlc
    if field in ("volume", "amount", "trades", "taker_buy_base", "taker_buy_amount"):
        return 0.0
    if field == "factor":
        return 1.0
    raise ValueError(f"unknown field {field}")
```

- [ ] **Step 8.5: Wire up `rename_pipeline` and CLI**

```python
def rename_pipeline(
    out_dir: Path,
    old_symbol: str,
    new_symbol: str,
    source: Source,
    *,
    dry_run: bool = False,
) -> None:
    plan_fn = lambda d: _rename_plan(d, old_symbol, new_symbol, source)
    apply_fn = lambda d, s, p: _rename_apply(d, s, p)
    _execute_mutation(out_dir, "rename", plan_fn, apply_fn, dry_run=dry_run)


@data_app.command("rename")
def rename_cmd(
    out_dir: Path = typer.Argument(...),
    old_symbol: str = typer.Argument(..., callback=lambda s: s.upper()),
    new_symbol: str = typer.Argument(..., callback=lambda s: s.upper()),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        rename_pipeline(out_dir, old_symbol, new_symbol, BinanceSource(), dry_run=dry_run)
    except PipelineError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
```

- [ ] **Step 8.6: Run all tests**

- [ ] **Step 8.7: Commit**

```bash
git add cli/data/pipeline.py cli/data/command.py cli/constants.py tests/test_data_rename.py tests/test_data_command.py
git commit -m "$(cat <<'CM'
feat(data): add `data rename` Variant 1 (single rename + synthetic gap fill)

Re-labels OLD → NEW under the snapshot+commit discipline. Probes NEW's
first archive day on data.binance.vision; synthesizes the gap with
zero-volume bars (locked OHLC = OLD's last close, factor = 1.0). NEW's
index.to is set to (NEW.first_available - 1) so subsequent backfill
picks up at NEW's actual first day.

Variant 2 (merge two existing) lands in the next task; Variant 1 detects
the merge case and raises NotImplementedError until then.

Refusals: OLD not in index; OLD == NEW; NEW not in exchangeInfo; NEW no
archive yet (find_available_range returns None); overlap.

CliConstants gains RENAME_SYNTH_WARN_DAYS=7 — gaps larger than this log
a louder warning.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 9 — `rename_pipeline` Variant 2 (merge two existing entries)

**Files:**

- Modify: `cli/data/pipeline.py` (`_rename_apply_variant2`)
- Modify: `tests/test_data_rename.py` (Variant 2 tests)

### Steps

- [ ] **Step 9.1: Write failing tests**

```python
def test_rename_v2_merge_no_gap(tmp_path):
    """Both MATIC and POL already in index. POL.from = MATIC.to + 1 → no synthetic fill."""
    out = _seed_two_pairs_for_merge(tmp_path,
                                    old_range=(dt.date(2024, 8, 1), dt.date(2024, 9, 10)),
                                    new_range=(dt.date(2024, 9, 11), dt.date(2024, 9, 20)))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    rename_pipeline(out, "MATICUSDT", "POLUSDT", src)
    idx = load_index(out)
    assert "MATICUSDT" not in {p.symbol for p in idx.pairs}
    pol = next(p for p in idx.pairs if p.symbol == "POLUSDT").intervals["1d"]
    assert pol.dates_from == "2024-08-01"  # extends backward through OLD
    assert pol.dates_to == "2024-09-20"


def test_rename_v2_merge_with_gap_fills(tmp_path):
    """OLD ends 2024-09-10, NEW starts 2024-09-13 → 2 synthetic days between bins."""
    out = _seed_two_pairs_for_merge(tmp_path,
                                    old_range=(dt.date(2024, 8, 1), dt.date(2024, 9, 10)),
                                    new_range=(dt.date(2024, 9, 13), dt.date(2024, 9, 20)))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    rename_pipeline(out, "MATICUSDT", "POLUSDT", src)

    # POL's volume bin should be: OLD's volumes + [0, 0] + NEW's volumes
    from cli.data.qlib_writer import read_bin
    _, vols = read_bin(out / "features" / "polusdt" / "volume.day.bin")
    # OLD had 41 days (Aug 1 .. Sep 10), gap 2 days, NEW had 8 days (Sep 13..20). Total 51.
    assert len(vols) == 41 + 2 + 8
    assert vols[41] == pytest.approx(0.0)
    assert vols[42] == pytest.approx(0.0)


def test_rename_v2_dry_run_prints_merge_plan(tmp_path, capsys):
    out = _seed_two_pairs_for_merge(tmp_path,
                                    old_range=(dt.date(2024, 8, 1), dt.date(2024, 9, 10)),
                                    new_range=(dt.date(2024, 9, 13), dt.date(2024, 9, 20)))
    src = FakeSource()
    src.add_pair("MATICUSDT", "MATIC", "USDT", status="BREAK")
    src.add_pair("POLUSDT", "POL", "USDT")
    rename_pipeline(out, "MATICUSDT", "POLUSDT", src, dry_run=True)
    captured = capsys.readouterr()
    assert "variant 2" in captured.out.lower() or "merge" in captured.out.lower()
```

- [ ] **Step 9.2: Run failing tests** (currently raise `NotImplementedError`)

- [ ] **Step 9.3: Implement `_rename_apply_variant2`**

```python
def _rename_apply_variant2(out_dir: Path, staging: Path, plan: RenamePlan) -> None:
    """Merge OLD's bin into NEW's slot. Synthetic gap fill in between. Drop OLD's entry."""
    idx = load_index(out_dir)

    # Determine new calendar
    new_calendar = _compute_merged_calendar(idx, plan)
    front_extension = (new_calendar[0] - _calendar_dates_from_index(idx)[0]).days
    # front_extension > 0 means the merged NEW (with OLD's older history) introduces dates
    # earlier than the old calendar's start. All OTHER pairs' headers need to shift up by
    # +front_extension.

    (staging / "calendars").mkdir(parents=True)
    write_calendar(staging / "calendars", new_calendar)

    (staging / "features").mkdir(parents=True)

    # 1. Build merged NEW: OLD bin + synthetic gap + NEW existing bin
    new_dir = staging / "features" / plan.new_symbol.lower()
    new_dir.mkdir(parents=True)
    old_dir_live = out_dir / "features" / plan.old_symbol.lower()
    new_dir_live = out_dir / "features" / plan.new_symbol.lower()
    n_gap = len(plan.gap_dates)
    import struct
    for field in _cfg.FIELDS:
        synth_value = _synthetic_value(field, plan.synthetic_locked_ohlc)
        old_bytes = (old_dir_live / f"{field}.day.bin").read_bytes()
        new_bytes = (new_dir_live / f"{field}.day.bin").read_bytes()
        # Strip start_index headers from both (first 4 bytes), then concatenate
        old_data = old_bytes[4:]
        new_data = new_bytes[4:]
        gap_data = struct.pack("<f", float(synth_value)) * n_gap
        merged_data = old_data + gap_data + new_data
        # New start_index = position of min(OLD.from, NEW.from) in new_calendar
        merged_first = min(dt.date.fromisoformat(next(p for p in idx.pairs if p.symbol == plan.old_symbol).intervals["1d"].dates_from),
                          dt.date.fromisoformat(next(p for p in idx.pairs if p.symbol == plan.new_symbol).intervals["1d"].dates_from))
        new_start_index = new_calendar.index(merged_first)
        header = struct.pack("<f", float(new_start_index))
        (new_dir / f"{field}.day.bin").write_bytes(header + merged_data)

    # 2. Copy OTHER pairs; rewrite headers if front_extension > 0
    for p in idx.pairs:
        if p.symbol in (plan.old_symbol, plan.new_symbol):
            continue
        src_dir = out_dir / "features" / p.symbol.lower()
        dst_dir = staging / "features" / p.symbol.lower()
        _shutil.copytree(src_dir, dst_dir)
        if front_extension > 0:
            for field_path in dst_dir.iterdir():
                _rewrite_bin_start_index(field_path, +front_extension)

    # 3. New instruments: drop OLD, update NEW's range
    (staging / "instruments").mkdir(parents=True)
    instr = {}
    for p in idx.pairs:
        if p.symbol == plan.old_symbol:
            continue
        if p.symbol == plan.new_symbol:
            merged_from = min(dt.date.fromisoformat(next(q for q in idx.pairs if q.symbol == plan.old_symbol).intervals["1d"].dates_from),
                             dt.date.fromisoformat(p.intervals["1d"].dates_from))
            merged_to = dt.date.fromisoformat(p.intervals["1d"].dates_to)
            instr[p.symbol] = (merged_from, merged_to)
        else:
            instr[p.symbol] = (
                dt.date.fromisoformat(p.intervals["1d"].dates_from),
                dt.date.fromisoformat(p.intervals["1d"].dates_to),
            )
    write_instruments(staging / "instruments", instr)

    # 4. New index — drop OLD, update NEW
    _write_index_from_staging_merged(staging, plan=plan, original_index=idx, header_shift=+front_extension)
```

- [ ] **Step 9.4: Run all tests**

- [ ] **Step 9.5: Commit**

```bash
git add cli/data/pipeline.py tests/test_data_rename.py
git commit -m "$(cat <<'CM'
feat(data): add rename Variant 2 (merge two existing pair entries)

When both OLD and NEW already live in the index, rename merges OLD's
bin into NEW's slot: concatenates OLD's bin + synthetic gap + NEW's bin,
removes OLD's entry, updates NEW's range to span both. NEW's bin start
index is recomputed to point at min(OLD.from, NEW.from) in the new
calendar; OTHER pairs' headers shift up by any front-extension that
results from picking up OLD's older history.

This is the "operator downloaded MATIC and POL separately, now wants
them merged into one continuous series" workflow.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

---

## Task 10 — README + iterations-history closeout

**Files:**

- Modify: `README.md` (Usage section documenting backfill / delist / rename / --dry-run / status-aware behavior)
- Modify: `docs/iterations-history.md` (append iter-5 entry)
- Create: `tests/test_data_e2e.py` (the three end-to-end scenarios)

### Steps

- [ ] **Step 10.1: Write the three E2E tests in `tests/test_data_e2e.py`**

```python
def test_e2e_fresh_full_history_via_download_plus_rename_merge(tmp_path):
    """Spec section 'Testing strategy' scenario 1."""
    # pairs.txt with MATICUSDT + POLUSDT
    # download (Change C: MATIC fetched as historical [first, last])
    # rename MATICUSDT POLUSDT (Variant 2)
    # final dataset: POLUSDT with continuous history end-to-end
    ...


def test_e2e_ongoing_dataset_survives_mid_window_rename(tmp_path):
    """Spec section 'Testing strategy' scenario 2."""
    # start dataset with MATICUSDT TRADING (sim), to=2024-09-10
    # flip MATICUSDT to BREAK on FakeSource
    # backfill (skips MATIC silently)
    # rename MATICUSDT POLUSDT Variant 1 (2-day synthetic gap)
    # backfill again (POL extends forward)
    ...


def test_e2e_pure_delisted_snapshot(tmp_path):
    """Spec section 'Testing strategy' scenario 3."""
    # pairs.txt with MATICUSDT only (status=BREAK)
    # download (Change C: truncated range)
    # verify passes
    # backfill is no-op (skipped)
    ...
```

- [ ] **Step 10.2: Run E2E tests; expect pass** (everything they exercise is already implemented)

- [ ] **Step 10.3: Update README `## Usage`**

Add three new tables/subsections for backfill / delist / rename mirroring the iter-4 `download` / `verify` voice. Include `--dry-run` mention on all four mutators. Add a small note about status-aware behavior: "Pairs with Binance status `TRADING` are extended to `--to`; non-`TRADING` pairs (e.g. delisted via rename) are downloaded as historical archive only or skipped during backfill."

(The `mdformat` pre-commit hook regenerates the TOC — don't hand-edit the `<!-- mdformat-toc -->` block.)

- [ ] **Step 10.4: Append iter-5 entry to `docs/iterations-history.md`**

Per `.claude/rules/iterations-history.md`: new section at the bottom (`## 2026-06-09 — iter-5: data backfill/delist/rename and status-aware download/backfill`) followed by a bullet list — one bullet per feature/change/fix.

Sample bullets:

```markdown
## 2026-06-09 — iter-5: data backfill/delist/rename and status-aware download/backfill

- Mutation harness `_execute_mutation(out_dir, cmd_name, plan_fn, apply_fn, *, dry_run)` consolidates the iter-4 recover→pre-verify→snapshot→commit discipline. All four mutators (download/backfill/delist/rename) now go through one place; the no-op short-circuit means snapshots are written only when real mutation occurs. Iter-4's `download_pipeline` refactored to fit this shape — all 113 iter-4 tests continue to pass.
- `zcrypto data backfill OUT_DIR [--to YYYY-MM-DD] [--dry-run]` extends every pair in the index forward to `--to` (default yesterday UTC). Per-pair status-aware: `TRADING` pairs use the iter-4 right-edge reachability check; non-`TRADING` (`BREAK`, etc.) pairs are silently skipped with an info log. No-op (all caught up or all skipped) → no snapshot.
- `zcrypto data delist OUT_DIR SYMBOL [--dry-run]` removes a pair with conditional calendar shrink (front-trim rewrites every remaining bin's `start_index` header; back-trim shortens calendar without touching headers). Refuses on not-in-index, last-pair (would empty dataset), and gap-creating (calendar union becomes non-contiguous).
- `zcrypto data rename OUT_DIR OLD_SYMBOL NEW_SYMBOL [--dry-run]` re-labels a pair. Variant 1: OLD in index only — probe NEW's first archive day on data.binance.vision; synthesize the gap with zero-volume bars (locked OHLC = OLD's last close, factor = 1.0). Variant 2: both OLD and NEW in index — merge OLD's bin into NEW's slot, with the same synthetic gap fill in between. Same command, detected from the index.
- `validate_pairs_against_exchange` now reads Binance `status` (TRADING / BREAK / HALT / etc.) and routes downstream behavior: `download` Change C fetches non-`TRADING` pairs as historical archive only via the new `find_available_range` helper; `backfill` Change D silently skips them.
- `--dry-run` added to all four mutators (download / backfill / delist / rename). Skips snapshot, marker, and staging; prints the plan to stdout via `typer.echo`. Errors out if `.commit-in-progress` marker is present (cannot dry-run until recovery).
- Snapshot tar.gz files now named `<UTCstamp>-<cmd>.tar.gz` for every mutator (iter-4 was already this shape; iter-5 makes it load-bearing across four commands).
- `CliConstants.RENAME_SYNTH_WARN_DAYS = 7` controls when a rename gap warning is elevated to "louder" form.
- Test count: NNN passed (113 iter-4 baseline + MMM iter-5 across `test_data_backfill.py`, `test_data_delist.py`, `test_data_rename.py`, `test_data_e2e.py`, and extensions to `test_data_pipeline.py` / `test_data_command.py`).
- Open topics: none filed in iter-5 (no surprising findings worth follow-up).
```

(Implementer: fill in the actual NNN/MMM after running `uv run pytest -q` at this stage.)

- [ ] **Step 10.5: Update README's `Version` badge?** No — that's the `/release` skill's job at the next release cut. iter-5 just merges into `develop`; the version bump happens later.

- [ ] **Step 10.6: Run all tests + pre-commit**

```
uv run pytest -q
uv run pre-commit run --all-files
```

Pre-commit may reformat README's TOC and `iterations-history.md`; re-stage and continue.

- [ ] **Step 10.7: Closeout commit**

```bash
git add README.md docs/iterations-history.md tests/test_data_e2e.py
git commit -m "$(cat <<'CM'
docs(data): document backfill/delist/rename and append iter-5 history

README §Usage now covers all three new subcommands plus --dry-run on the
four mutators (download, backfill, delist, rename) and the status-aware
behavior of download/backfill.

docs/iterations-history.md gets the iter-5 entry summarizing the
mutation-harness refactor, the three new commands, the five design
changes (A status routing, B find_available_range, C download tolerance,
D backfill skip, E rename Variants 1+2), and the closeout test count.

Three end-to-end tests cover the scenarios from the spec's testing
strategy: fresh full-history via download+rename merge; ongoing dataset
survives mid-window rename; pure delisted snapshot is a stable
no-op backfill subject.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
CM
)"
```

After review subagents sign off (spec + code-quality + final whole-branch), amend their `Reviewed-by:` trailers onto whichever commits they covered. Per `.claude/rules/commit-messages.md`, per-commit attribution preserves which reviewer covered which slice — useful in long iterations.

---

## Closeout discipline

After Task 10:

1. **All tests pass.** `uv run pytest -q` shows ~155-170 passing.
2. **Pre-commit green.** `uv run pre-commit run --all-files` clean across all 15 hooks.
3. **Per-commit `Reviewed-by:` trailers** amended while local (any commit not yet pushed) or via `git push --force-with-lease` (commits already pushed) per the new commit-messages.md convention.
4. **Push** the branch: `git push -u origin feat/data-backfill-delist-rename`.
5. **Open PR** into `develop` using the template structure from `.github/pull_request_template.md`. PR title: `feat(data): iter-5 — backfill, delist, rename, status-aware download/backfill`. PR body mirrors iter-4's structure; aggregate `Co-Authored-By:` and `Reviewed-by:` trailers via the iter-4 commands in `.claude/rules/pull-requests.md`.

---

## Notes

- **No new dependencies.** Iter-5 reuses iter-4's stack entirely.
- **No interval expansion.** Still 1d-only. The `--interval` arg accepts only `"1d"`; validated at parse time.
- **No `data prune` / `data wipe` command.** Operators clear `OUT_DIR` with `rm -rf` (acknowledged in the spec's Out of Scope).
- **Variant 3 of rename** (OLD ∉ index, NEW ∉ index — synthesize MATIC's history into POL's slot in one step) is **not** implemented. Operators reach the same outcome via download (MATIC + POL) → rename Variant 2.
