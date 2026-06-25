"""Regenerate the Phase 2 Stage-2 results figures (docs/research/04.phase2-stage2-results.md).

All underlying numbers also live as markdown tables in the report's Data Appendix
(B.1–B.5), so the figures are reproducible from the document alone. Run:

    uv run python docs/research/04.phase2-figures/make_figures.py

Style/palette intentionally match docs/research/02.phase1-figures/make_figures.py.
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

mpl.rcParams.update(
    {
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "font.size": 10,
        "font.family": "sans-serif",
        "axes.titlesize": 11.5,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)

NEG = "#c0392b"  # muted red — losses / fails the bar
POS = "#2e7d32"  # green — gains
SLATE = "#34495e"  # neutral
STEEL = "#2c6fbb"  # blue accent
ORANGE = "#e67e22"  # highlight (the apparent positive)
GRAY = "#95a5a6"

OUT = Path(__file__).resolve().parent


def fig1_landscape():
    """The bets vs the passive-beta null — only momentum is positive (and it still fails the bar)."""
    # channel, mean delta-vs-beta_null (B.1); one representative per channel
    rows = [
        ("Per-asset TSMOM", -0.43),
        ("On-chain NVM (keyless)", -0.41),
        ("Derivatives: basis", -0.21),
        ("Derivatives: long/short", -0.07),
        ("Derivatives: OI", 0.01),
        ("Cross-sectional momentum", 0.200),
    ]
    rows = sorted(rows, key=lambda r: r[1])
    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    colors = [POS if v > 0 else NEG for v in vals]
    colors[labels.index("Cross-sectional momentum")] = ORANGE
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(8.4, 4.0))
    ax.barh(y, vals, color=colors, edgecolor="white", height=0.62)
    ax.axvline(0, color=SLATE, lw=1.2, label="`beta_null` (passive-beta null)")
    for yi, v in zip(y, vals):
        ax.text(v + (0.012 if v >= 0 else -0.012), yi, f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Mean Δ cost-adjusted Sharpe vs `beta_null` (OOS walk-forward)")
    ax.set_title(
        "Fig. 1 — Every channel vs the passive-beta null: only momentum is\npositive — and it still fails the significance bar (Fig. 2)"
    )
    ax.set_xlim(-0.62, 0.40)
    ax.legend(loc="lower right", fontsize=8.5, framealpha=0.95)
    ax.text(
        -0.60,
        len(rows) - 0.5,
        "BTC→alt lead-lag refuted separately (IC, not Δ): 0/40 cells significant",
        fontsize=7.5,
        color=GRAY,
        style="italic",
    )
    fig.savefig(OUT / "fig1_bets_landscape.png")
    plt.close(fig)


def fig2_momentum_crux():
    """In-sample looked strong (left); the edge-over-null fails the significance bar (right)."""
    windows = ["2022", "2023", "2024", "2025"]
    deltas = [0.0, 0.108, 0.529, 0.164]  # B.2 annualized per-window Δ
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.2, 4.4))

    # Left — annualized per-window Δ
    x = np.arange(len(windows))
    axL.bar(x, deltas, color=[GRAY if v == 0 else POS for v in deltas], edgecolor="white", width=0.6)
    axL.axhline(0.200, color=STEEL, lw=1.5, ls="--", label="mean +0.200")
    axL.axhline(0, color=SLATE, lw=1.0)
    for xi, v in zip(x, deltas):
        axL.text(xi, v + 0.012, f"{v:+.3f}", ha="center", va="bottom", fontsize=9)
    axL.set_xticks(x)
    axL.set_xticklabels(windows)
    axL.set_ylabel("Annualized Δ Sharpe vs `beta_null`")
    axL.set_title("In-sample: directionally consistent\n(+0.200 mean, positive in all 3 active windows)")
    axL.set_ylim(-0.05, 0.62)
    axL.legend(loc="upper left", fontsize=8.5, framealpha=0.95)

    # Right — per-period daily-delta t-stat vs the hurdles
    tw = ["2023", "2024", "2025", "pooled"]
    tvals = [0.29, 1.36, 0.71, 1.30]  # B.2 daily-delta t
    xr = np.arange(len(tw))
    tcolors = [STEEL, STEEL, STEEL, ORANGE]
    axR.bar(xr, tvals, color=tcolors, edgecolor="white", width=0.6)
    axR.axhline(2.0, color=GRAY, lw=1.4, ls="--", label="naive bar  t = 2.0")
    axR.axhline(3.0, color=NEG, lw=1.6, ls=":", label="multiple-testing bar  t = 3.0")
    for xi, v in zip(xr, tvals):
        axR.text(xi, v + 0.05, f"{v:.2f}", ha="center", va="bottom", fontsize=9)
    axR.set_xticks(xr)
    axR.set_xticklabels(tw)
    axR.set_ylabel("Paired daily-delta t-stat (edge over null)")
    axR.set_title("Significance: pooled t ≈ 1.3 —\nbelow t = 2, far below the t = 3 bar")
    axR.set_ylim(0, 3.4)
    axR.legend(loc="upper left", fontsize=8.5, framealpha=0.95)

    fig.suptitle(
        "Fig. 2 — momentum_tilt: robust in-sample (left) but short of the significance bar (right) — robust ≠ significant",
        fontsize=12,
        fontweight="bold",
        y=1.02,
    )
    fig.savefig(OUT / "fig2_momentum_crux.png")
    plt.close(fig)


def fig3_broken_register():
    """The deflated-Sharpe backstop was broken: 4 of ~46 trials counted → ~no penalty."""
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.2, 4.2), gridspec_kw={"width_ratios": [1, 1.35]})

    # Left — trials run vs trials counted
    bars = ["trials actually run", "trials in register"]
    counts = [46, 4]
    axL.bar([0, 1], counts, color=[STEEL, NEG], edgecolor="white", width=0.6)
    for xi, v in zip([0, 1], counts):
        axL.text(xi, v + 0.6, str(v), ha="center", va="bottom", fontsize=11, fontweight="bold", color=SLATE)
    axL.set_xticks([0, 1])
    axL.set_xticklabels(bars)
    axL.set_ylabel("# distinct trials")
    axL.set_title("Register lost its history\n(`runs/trials.jsonl`)")
    axL.set_ylim(0, 52)

    # Right — the artifactually-high deflated Sharpes the broken register produced
    sib = {
        "k15": 0.96,
        "k20": 0.96,
        "l90": 0.94,
        "l60": 0.93,
        "vt60": 0.85,
        "vt55": 0.85,
        "vt45": 0.85,
        "confirm10": 0.77,
        "confirm3": 0.76,
    }
    names = list(sib.keys())
    yv = list(sib.values())
    xs = np.arange(len(names))
    axR.scatter(xs, yv, s=70, color=STEEL, edgecolor="white", linewidth=0.7, zorder=3, label="sibling recipes (no real penalty)")
    axR.scatter(
        [len(names)], [0.0], s=110, color=NEG, marker="x", linewidth=2.2, zorder=3, label="momentum_tilt = NaN (uncomputable)"
    )
    axR.axhspan(0.0, 0.0, color="white")
    axR.annotate(
        "correctly counted (true N≈46)\nwould fall far lower",
        xy=(4, 0.85),
        xytext=(2.2, 0.45),
        fontsize=8,
        color=SLATE,
        arrowprops=dict(arrowstyle="->", color=SLATE, lw=1.0),
    )
    axR.set_xticks(list(xs) + [len(names)])
    axR.set_xticklabels(names + ["mom."], fontsize=8)
    axR.set_ylabel("Recorded deflated Sharpe")
    axR.set_title("…so deflated Sharpe was NaN (momentum)\nor artifactually high (siblings, ~0.85–0.96)")
    axR.set_ylim(-0.06, 1.05)
    axR.legend(loc="lower left", fontsize=8, framealpha=0.95)

    fig.suptitle(
        "Fig. 3 — The deflated-Sharpe backstop was broken: 4 of ~46 trials counted, so the multiple-testing penalty was ~none (T0025)",
        fontsize=11.5,
        fontweight="bold",
        y=1.02,
    )
    fig.savefig(OUT / "fig3_broken_register.png")
    plt.close(fig)


def fig4_momentum_robustness():
    """Why momentum looked convincing — robust across strength, lookback, cost — but robust ≠ significant."""
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.2, 4.2))

    # Left — k strength dose-response (B.3)
    k = [0.5, 1.0, 1.5, 2.0]
    kd = [0.107, 0.200, 0.221, 0.223]
    axL.plot(k, kd, "-o", color=STEEL, markersize=7, lw=1.8)
    for xi, v in zip(k, kd):
        axL.text(xi, v + 0.006, f"{v:+.3f}", ha="center", va="bottom", fontsize=8.5)
    axL.scatter([1.0], [0.200], s=130, facecolor="none", edgecolor=ORANGE, linewidth=2.0, zorder=4, label="default k = 1.0")
    axL.set_xlabel("tilt strength k")
    axL.set_ylabel("Mean Δ Sharpe vs `beta_null`")
    axL.set_title("Strength: clean monotonic-then-plateau\ndose-response (the signature that misled)")
    axL.set_ylim(0, 0.26)
    axL.set_xticks(k)
    axL.legend(loc="lower right", fontsize=8.5, framealpha=0.95)

    # Right — lookback robustness (B.3), + cost annotation
    lb = ["14d", "30d", "60d", "90d"]
    lv = [0.210, 0.200, 0.146, 0.142]
    x = np.arange(len(lb))
    axR.bar(x, lv, color=POS, edgecolor="white", width=0.6)
    for xi, v in zip(x, lv):
        axR.text(xi, v + 0.005, f"{v:+.3f}", ha="center", va="bottom", fontsize=8.5)
    axR.set_xticks(x)
    axR.set_xticklabels(lb)
    axR.set_ylabel("Mean Δ Sharpe vs `beta_null`")
    axR.set_title("Lookback: positive across 14–90d\n(cost-robust too: +0.194 at 2× turnover cost)")
    axR.set_ylim(0, 0.26)

    fig.suptitle(
        "Fig. 4 — Why momentum looked convincing: robust across strength, lookback, and cost — but robustness is not significance (Fig. 2)",
        fontsize=11.5,
        fontweight="bold",
        y=1.02,
    )
    fig.savefig(OUT / "fig4_momentum_robustness.png")
    plt.close(fig)


if __name__ == "__main__":
    fig1_landscape()
    fig2_momentum_crux()
    fig3_broken_register()
    fig4_momentum_robustness()
    print("wrote:", *(p.name for p in sorted(OUT.glob("*.png"))))
