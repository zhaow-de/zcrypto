"""`zcrypto rank` — rank persisted experiment runs as trials; report DSR + PBO."""

from __future__ import annotations

import json
from pathlib import Path

import typer


def _load_trials(out_dir: Path) -> list[dict]:
    """Return [{recipe, run, returns}] for every bundle under out_dir with a returns.csv."""
    import pandas as pd

    trials: list[dict] = []
    if not out_dir.is_dir():
        return trials
    for recipe_dir in sorted(p for p in out_dir.iterdir() if p.is_dir() and p.name != "mlruns"):
        for run_dir in sorted(p for p in recipe_dir.iterdir() if p.is_dir()):
            rcsv = run_dir / "returns.csv"
            if not rcsv.exists():
                continue
            series = pd.read_csv(rcsv, parse_dates=["date"]).set_index("date")["ret"]
            trials.append({"recipe": recipe_dir.name, "run": run_dir.name, "returns": series})
    return trials


def rank(
    out: Path = typer.Option(Path("runs"), "--out", help="Run-bundle root to scan for trials.", file_okay=False),
    n_splits: int = typer.Option(16, "--n-splits", help="CSCV splits for PBO (must be even)."),
) -> None:
    """Rank all persisted runs as trials; report the deflated Sharpe ratio + PBO."""
    import numpy as np

    from cli.experiment.stats import deflated_sharpe, pbo_cscv, psr, sharpe
    from cli.logging import get_logger

    logger = get_logger("rank.command")
    out = Path(out)
    trials = _load_trials(out)
    logger.info("rank-scan", extra={"n_trials": len(trials), "out": str(out)})
    if not trials:
        typer.echo(f"ERROR: no trials with returns.csv under {out}", err=True)
        raise typer.Exit(code=1)

    common = trials[0]["returns"].index
    for tr in trials[1:]:
        common = common.intersection(tr["returns"].index)
    if len(common) == 0:
        typer.echo("ERROR: trials share no common dates; cannot rank.", err=True)
        raise typer.Exit(code=1)
    common = common.sort_values()
    logger.info("rank-aligned", extra={"t": len(common), "from": str(common.min().date()), "to": str(common.max().date())})

    max_len = max(len(tr["returns"]) for tr in trials)
    if len(common) < 0.95 * max_len:
        typer.echo(
            f"WARNING: trials' return windows differ materially — shared window {len(common)}d "
            f"vs longest trial {max_len}d; DSR/PBO use only the shared dates.",
            err=True,
        )
        logger.info("rank-window-mismatch", extra={"common": len(common), "max_len": max_len})

    matrix = np.column_stack([tr["returns"].reindex(common).to_numpy() for tr in trials])
    per_trial = [
        {"recipe": tr["recipe"], "run": tr["run"], "sharpe_daily": sharpe(matrix[:, j]), "psr": psr(matrix[:, j])}
        for j, tr in enumerate(trials)
    ]
    n = len(trials)
    best = max(range(n), key=lambda j: per_trial[j]["sharpe_daily"])
    sr_trials = [pt["sharpe_daily"] for pt in per_trial]
    dsr = deflated_sharpe(matrix[:, best], sr_trials) if n >= 2 else float("nan")
    try:
        pbo = pbo_cscv(matrix, n_splits)["pbo"] if n >= 2 else float("nan")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    logger.info("rank-done", extra={"dsr": dsr, "pbo": pbo})

    typer.echo(f"{n} trials over {common.min().date()}..{common.max().date()} ({len(common)} days)")
    if n >= 2:
        typer.echo(f"  DSR(best) = {dsr:.4f}   PBO = {pbo:.4f}")
    else:
        typer.echo("  DSR / PBO: N/A (need >= 2 trials)")
    typer.echo(f"  {'rank':<5}{'recipe':<16}{'run':<22}{'Sharpe(d)':>9}{'PSR':>8}")
    typer.echo("  (Sharpe(d) = per-period daily Sharpe; PSR/DSR/PBO are computed per-period)")
    for rank_i, j in enumerate(sorted(range(n), key=lambda j: per_trial[j]["sharpe_daily"], reverse=True), 1):
        pt = per_trial[j]
        mark = " *" if j == best else ""
        typer.echo(f"  {rank_i:<5}{pt['recipe']:<16}{pt['run']:<22}{pt['sharpe_daily']:>9.4f}{pt['psr']:>8.3f}{mark}")

    (out / "rank.json").write_text(
        json.dumps(
            {
                "n_trials": n,
                "window": [str(common.min().date()), str(common.max().date()), len(common)],
                "n_splits": n_splits,
                "trials": per_trial,
                "dsr_best": dsr,
                "pbo": pbo,
            },
            indent=2,
        )
    )
    typer.echo(f"  wrote {out / 'rank.json'}")
