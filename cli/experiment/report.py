"""3- or 4-panel Plotly report for a zcrypto experiment run.

Panel 1 — equity curves (test window): strategy vs BTCUSDT buy-and-hold.
Panel 2 — trade timeline: buy/sell markers on a date × symbol scatter.
Panel 3 — full-history market context: BTCUSDT + reference instruments rebased to 100,
          with shaded vertical regions for LUNA and FTX stress windows.
Panel 4 — (optional) CPCV OOS Sharpe distribution (descriptive), appended when cv
          data is provided to build_report. The holdout marker shows the test-period
          Sharpe + PSR — a different-period reference, not an overfit test.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from cli.experiment.caveats import SURVIVORSHIP_MARKER
from cli.experiment.stress import STRESS_WINDOWS
from cli.experiment.trades import trades_from_positions

# Colour constants — keep it simple.
_BUY_COLOR = "green"
_SELL_COLOR = "red"
_STRESS_FILLCOLOR = "rgba(255, 165, 0, 0.15)"  # translucent orange


def build_report(result, *, stress_windows=None, cv=None) -> go.Figure:
    """Build and return a 3- or 4-panel Plotly Figure from a RunResult.

    Parameters
    ----------
    result:
        A RunResult (or duck-typed stand-in) with fields: account_curve,
        benchmark_curve, positions, context_prices, recipe, ending_value.
    stress_windows:
        List of (label, start, end) ISO strings.  Defaults to STRESS_WINDOWS.
    cv:
        Optional dict with keys ``path_sharpes`` (list[float]), ``holdout_sharpe``
        (float), and ``holdout_psr`` (float).  When provided, a 4th panel is appended
        showing the CPCV OOS Sharpe distribution (descriptive); its holdout marker
        shows the test-period Sharpe + PSR.
    """
    if stress_windows is None:
        stress_windows = STRESS_WINDOWS

    recipe = result.recipe
    ending = float(result.account_curve.iloc[-1])
    title = f"{recipe.name}: {recipe.account:,.0f} → {ending:,.0f} USDT<br><sub>⚠ {SURVIVORSHIP_MARKER}</sub>"

    n_rows = 4 if cv else 3
    titles = ["Equity (test window)", "Trade timeline", "Market context (rebased)"]
    if cv:
        titles.append("CPCV OOS Sharpe distribution (descriptive)")
    fig = make_subplots(rows=n_rows, cols=1, subplot_titles=tuple(titles), vertical_spacing=0.06)

    # ------------------------------------------------------------------
    # Panel 1 — equity curves
    # ------------------------------------------------------------------
    fig.add_trace(
        go.Scatter(
            x=result.account_curve.index,
            y=result.account_curve.values,
            mode="lines",
            name="strategy",
            line={"width": 1.5},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=result.benchmark_curve.index,
            y=result.benchmark_curve.values,
            mode="lines",
            name="BTCUSDT buy & hold",
            line={"width": 1.5, "dash": "dot"},
        ),
        row=1,
        col=1,
    )

    # ------------------------------------------------------------------
    # Panel 2 — trade timeline
    # ------------------------------------------------------------------
    trades = trades_from_positions(result.positions)
    if trades.empty:
        fig.add_trace(
            go.Scatter(x=[], y=[], mode="markers", name="trades", showlegend=False),
            row=2,
            col=1,
        )
    else:
        colors = [_BUY_COLOR if s == "buy" else _SELL_COLOR for s in trades["side"]]
        hover = [
            f"{row['side'].upper()} {row['symbol']}<br>qty={row['qty']:.6g}  price={row['price']:.6g}<br>value={row['value']:.2f}"
            for _, row in trades.iterrows()
        ]
        fig.add_trace(
            go.Scatter(
                x=trades["date"],
                y=trades["symbol"],
                mode="markers",
                name="trades",
                marker={"color": colors, "size": 8, "symbol": "circle"},
                text=hover,
                hoverinfo="text",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # ------------------------------------------------------------------
    # Panel 3 — context prices rebased to 100
    # ------------------------------------------------------------------
    for sym, series in result.context_prices.items():
        series = series.dropna()
        if series.empty:
            continue
        rebased = series / series.iloc[0] * 100
        fig.add_trace(
            go.Scatter(
                x=rebased.index,
                y=rebased.values,
                mode="lines",
                name=sym,
                line={"width": 1},
            ),
            row=3,
            col=1,
        )

    # Stress-window shading on panel 3
    for label, start, end in stress_windows:
        fig.add_vrect(
            x0=start,
            x1=end,
            fillcolor=_STRESS_FILLCOLOR,
            opacity=1,
            line_width=0,
            annotation_text=label,
            annotation_position="top left",
            row=3,
            col=1,
        )

    # ------------------------------------------------------------------
    # Panel 4 — CPCV Sharpe distribution (only when cv results are provided)
    # ------------------------------------------------------------------
    if cv:
        sharpes = list(cv["path_sharpes"])
        fig.add_trace(
            go.Histogram(x=sharpes, name="path Sharpe", showlegend=False, marker={"color": "steelblue"}),
            row=4,
            col=1,
        )
        fig.add_vline(
            x=cv["holdout_sharpe"],
            line={"color": _SELL_COLOR, "width": 2, "dash": "dash"},
            annotation_text=f"holdout (test period) · PSR {cv.get('holdout_psr', float('nan')):.2f}",
            annotation_position="top",
            row=4,
            col=1,
        )

    fig.update_layout(title=title, height=300 * n_rows, template="plotly_white")
    return fig


def write_report(fig: go.Figure, out_dir: Path, *, svg: bool = False) -> Path:
    """Write the report to *out_dir*.

    Always writes ``report.html`` (self-contained, plotly.js inline).
    If *svg* is True, also writes ``report.svg`` via kaleido.

    Returns the html Path.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / "report.html"
    fig.write_html(str(html_path), include_plotlyjs="inline")

    if svg:
        svg_path = out_dir / "report.svg"
        fig.write_image(str(svg_path), format="svg")

    return html_path
