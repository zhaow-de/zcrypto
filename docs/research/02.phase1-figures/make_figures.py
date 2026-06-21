"""Regenerate the Phase 1 summary figures (docs/research/02.phase1-summary.md).

All underlying numbers also live as markdown tables in the report's Data Appendix,
so the figures are reproducible from the document alone. Run:

    uv run python docs/research/02.phase1-figures/make_figures.py
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

NEG = "#c0392b"  # muted red — losses
POS = "#2e7d32"  # green — gains
SLATE = "#34495e"  # neutral
STEEL = "#2c6fbb"  # blue accent
ORANGE = "#e67e22"  # highlight
GRAY = "#95a5a6"

OUT = Path(__file__).resolve().parent
WINDOWS = ["OOS 2022\n(crisis)", "OOS 2023\n(bull)", "OOS 2024\n(bull)", "OOS 2025\n(bear, dev-seen)"]


def _signed_colors(vals):
    return [POS if v > 0 else NEG for v in vals]


def fig1_multiseed():
    """iter-14: 16-seed holdout — nothing profitable, differences within seed noise."""
    recipes = ["crossasset_steady", "skeleton", "alpha360_steady", "steady"]
    means = [-0.43, -0.51, -0.57, -0.62]
    stds = [0.14, 0.15, 0.17, 0.21]
    y = np.arange(len(recipes))[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.errorbar(means, y, xerr=stds, fmt="o", color=NEG, ecolor=SLATE, elinewidth=1.4, capsize=4, markersize=7)
    ax.axvline(0, color=SLATE, lw=1.0, ls="-")
    for yi, m, s in zip(y, means, stds):
        ax.text(m, yi + 0.18, f"{m:.2f}±{s:.2f}", ha="center", va="bottom", fontsize=8.5, color=SLATE)
    ax.set_yticks(y)
    ax.set_yticklabels(recipes)
    ax.set_xlabel("Cost-adjusted holdout Sharpe (2025–26), mean ± 1σ over 16 seeds")
    ax.set_title("Fig. 1 — No daily-OHLCV recipe is profitable, and the\ndifferences sit within seed noise (iter-14)")
    ax.set_xlim(-0.95, 0.15)
    ax.margins(y=0.18)
    fig.savefig(OUT / "fig1_multiseed.png")
    plt.close(fig)


def fig2_longshort():
    """iter-21 vs iter-22: the market-neutral +33% was selection bias."""
    ls = [-0.65, 0.45, -0.68, 0.47]
    x = np.arange(len(WINDOWS))
    colors = _signed_colors(ls)
    colors[3] = ORANGE  # dev-seen window
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    bars = ax.bar(x, ls, color=colors, width=0.6, edgecolor="white")
    ax.axhline(0, color=SLATE, lw=1.0)
    ax.axhline(0.599, color=STEEL, lw=1.4, ls="--", label="In-sample claim (dev-seen): +0.60")
    ax.axhline(-0.10, color=NEG, lw=1.4, ls=":", label="OOS walk-forward mean: −0.10")
    for xi, v in zip(x, ls):
        ax.text(xi, v + (0.04 if v >= 0 else -0.06), f"{v:+.2f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(WINDOWS)
    ax.set_ylabel("Market-neutral L/S Sharpe (steady)")
    ax.set_title(
        "Fig. 2 — The +33% market-neutral edge was selection bias:\npositive only on the repeatedly-seen 2025 window (iter-21 → iter-22)"
    )
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.95)
    ax.set_ylim(-0.95, 0.85)
    fig.savefig(OUT / "fig2_longshort_selection_bias.png")
    plt.close(fig)


def fig3_regime_per_window():
    """iter-29/30/32: OOS-by-window — regime-gating removes the bear-window losses."""
    series = {
        "steady (Alpha158, ungated)": ([-0.753, 1.244, 0.700, -0.576], NEG),
        "regime_equalweight (gated, no ML)": ([0.000, 1.058, 1.100, -0.632], STEEL),
        "regime_volweight_majors (gated, inv-vol)": ([0.000, 1.198, 0.977, -0.158], POS),
    }
    x = np.arange(len(WINDOWS))
    n = len(series)
    w = 0.26
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    for i, (label, (vals, c)) in enumerate(series.items()):
        ax.bar(x + (i - (n - 1) / 2) * w, vals, width=w, color=c, label=label, edgecolor="white", linewidth=0.5)
    ax.axhline(0, color=SLATE, lw=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(WINDOWS)
    ax.set_ylabel("Per-window long-only Sharpe (8 seeds)")
    ax.set_title(
        "Fig. 3 — Out-of-sample by window: the regime gate sits out the 2022 crisis\n(0.00) and softens the 2025 bear tail; the quality basket lifts the bull windows"
    )
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.9)
    ax.set_ylim(-0.95, 1.85)
    fig.savefig(OUT / "fig3_regime_per_window.png")
    plt.close(fig)


def fig4_progression():
    """The deployable progression — every improvement removed complexity."""
    labels = [
        "Alpha158\nlong-only\n(baseline)",
        "+ BTC regime\ngate",
        "− ML selection\n(equal-weight)",
        "quality basket\n(10 majors)",
        "+ inverse-vol\nweights",
    ]
    vals = [0.154, 0.311, 0.382, 0.493, 0.504]
    x = np.arange(len(vals))
    shades = ["#9bbce0", "#6f9fd0", "#4a82c0", "#2c6fbb", "#1b5390"]
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    bars = ax.bar(x, vals, color=shades, width=0.62, edgecolor="white")
    for xi, v in zip(x, vals):
        ax.text(xi, v + 0.012, f"{v:.3f}", ha="center", va="bottom", fontsize=9.5, fontweight="bold", color=SLATE)
    deltas = [vals[0]] + [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    for xi, d in zip(x[1:], deltas[1:]):
        ax.annotate(f"+{d:.3f}", xy=(xi, vals[xi]), xytext=(xi - 0.5, max(vals) * 0.5), fontsize=8, color=POS, ha="center")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Across-window mean OOS Sharpe (2022–2025)")
    ax.set_title(
        "Fig. 4 — Every step that improved the strategy removed complexity\n(ending at a no-ML, regime-timed, risk-weighted majors basket)"
    )
    ax.set_ylim(0, 0.58)
    fig.savefig(OUT / "fig4_deployable_progression.png")
    plt.close(fig)


def fig5_selection_distribution():
    """iter-33: 18 recipes on one holdout — coarse structure real, the top near noise."""
    ungated = [0.180, 0.170, 0.168, 0.154, 0.151, 0.149, 0.036]
    slow_gate = [0.594, 0.504, 0.493, 0.382, 0.311, 0.304, 0.289, 0.259, 0.241]
    fast_gate = [0.110, -0.113]
    groups = [("ungated (7)", ungated, GRAY), ("slow-gate family (9)", slow_gate, STEEL), ("fast-gate whipsaw (2)", fast_gate, NEG)]
    rng = np.random.default_rng(0)
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    for yi, (label, vals, c) in enumerate(groups):
        jitter = rng.uniform(-0.13, 0.13, size=len(vals))
        ax.scatter(vals, np.full(len(vals), yi) + jitter, s=55, color=c, edgecolor="white", linewidth=0.6, zorder=3, label=label)
    ax.axvline(0.210, color=SLATE, lw=1.3, ls="--", label="median 0.21")
    ax.axvline(0.594, color=STEEL, lw=1.3, ls="-", label="best 0.594")
    ax.axvline(0.60, color=NEG, lw=1.3, ls=":", label="E[max of 18] ≈ 0.6 (noise ceiling)")
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels([g[0] for g in groups])
    ax.set_xlabel("Across-window mean OOS Sharpe")
    ax.set_title(
        "Fig. 5 — 18 recipes on one holdout: the slow-gate cluster is really shifted\nright of ungated, but the single best sits at the noise ceiling (iter-33)"
    )
    ax.legend(loc="upper right", fontsize=7.8, framealpha=0.95, ncol=2)
    ax.set_xlim(-0.25, 0.78)
    ax.margins(y=0.25)
    fig.savefig(OUT / "fig5_selection_bias_distribution.png")
    plt.close(fig)


if __name__ == "__main__":
    fig1_multiseed()
    fig2_longshort()
    fig3_regime_per_window()
    fig4_progression()
    fig5_selection_distribution()
    print("wrote:", *(p.name for p in sorted(OUT.glob("*.png"))))
