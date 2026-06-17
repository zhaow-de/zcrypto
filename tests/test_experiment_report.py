"""Tests for cli.experiment.report — 3-panel Plotly report."""

from __future__ import annotations

import types

import pandas as pd
import pytest

from cli.experiment.report import build_report, write_report
from cli.experiment.stress import STRESS_WINDOWS

# ---------------------------------------------------------------------------
# Minimal stand-in RunResult
# ---------------------------------------------------------------------------

# Equity window: a few days in early 2024 (test window)
_EQUITY_DATES = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])

# Context-price window: spans 2021-2023, so the LUNA window (2022-05) is included.
_CONTEXT_DATES = pd.date_range("2021-01-01", "2023-06-30", freq="D")


def _make_result():
    account_curve = pd.Series(
        [10000.0, 10200.0, 9900.0, 10500.0],
        index=_EQUITY_DATES,
    )
    benchmark_curve = pd.Series(
        [10000.0, 10300.0, 10100.0, 10600.0],
        index=_EQUITY_DATES,
    )

    # Two days, one symbol — produces at least one trade row.
    day0 = pd.Timestamp("2024-01-02")
    day1 = pd.Timestamp("2024-01-03")
    positions = {
        day0: types.SimpleNamespace(
            position={
                "BTCUSDT": {"amount": 0.1, "price": 42000.0},
                "cash": 5800.0,
                "now_account_value": 10000.0,
            }
        ),
        day1: types.SimpleNamespace(
            position={
                "BTCUSDT": {"amount": 0.15, "price": 44000.0},
                "cash": 3800.0,
                "now_account_value": 10400.0,
            }
        ),
    }

    # Context prices spanning 2021-2023 so LUNA (2022-05) is included.
    n = len(_CONTEXT_DATES)
    btc_prices = pd.Series([30000.0 + i for i in range(n)], index=_CONTEXT_DATES, dtype=float)
    eur_prices = pd.Series([28000.0 + i for i in range(n)], index=_CONTEXT_DATES, dtype=float)
    eth_prices = pd.Series([0.07 + i * 0.0001 for i in range(n)], index=_CONTEXT_DATES, dtype=float)

    context_prices = {
        "BTCUSDT": btc_prices,
        "BTCEUR": eur_prices,
        "ETHBTC": eth_prices,
    }

    recipe = types.SimpleNamespace(account=10000.0, name="skeleton")

    return types.SimpleNamespace(
        account_curve=account_curve,
        benchmark_curve=benchmark_curve,
        positions=positions,
        context_prices=context_prices,
        recipe=recipe,
        ending_value=10500.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_report_returns_figure():
    import plotly.graph_objects as go

    result = _make_result()
    fig = build_report(result)
    assert isinstance(fig, go.Figure)


def test_figure_has_three_subplot_rows():
    result = _make_result()
    fig = build_report(result)
    # _grid_ref is a list-of-lists; outer length == number of rows.
    assert len(fig._grid_ref) == 3


def test_panel1_has_strategy_and_benchmark_traces():
    result = _make_result()
    fig = build_report(result)

    # Panel-1 traces are on yaxis / yaxis1.
    panel1_traces = [t for t in fig.data if t.yaxis in ("y", "y1")]
    names = {t.name for t in panel1_traces}
    assert "strategy" in names
    assert "BTCUSDT buy & hold" in names


def test_stress_vrects_present():
    result = _make_result()
    fig = build_report(result)

    # add_vrect creates shapes on the layout.
    assert len(fig.layout.shapes) > 0


def test_stress_annotations_contain_luna_ftx():
    result = _make_result()
    fig = build_report(result)

    annotation_texts = [a.text for a in fig.layout.annotations if a.text]
    # subplot_titles also appear as annotations; filter to short labels.
    stress_labels = {t for t in annotation_texts if t in ("LUNA", "FTX")}
    assert "LUNA" in stress_labels
    assert "FTX" in stress_labels


def test_figure_title_contains_recipe_name():
    result = _make_result()
    fig = build_report(result)
    assert "skeleton" in fig.layout.title.text


def test_build_report_empty_positions_no_crash():
    result = _make_result()
    result.positions = {}  # empty — should not raise
    fig = build_report(result)
    assert len(fig._grid_ref) == 3


def test_build_report_custom_stress_windows():
    result = _make_result()
    custom = [("TEST", "2022-01-01", "2022-01-07")]
    fig = build_report(result, stress_windows=custom)

    annotation_texts = [a.text for a in fig.layout.annotations if a.text]
    assert "TEST" in annotation_texts
    # Default windows not present
    assert "LUNA" not in annotation_texts
    assert "FTX" not in annotation_texts


def test_write_report_html(tmp_path):
    result = _make_result()
    fig = build_report(result)
    html_path = write_report(fig, tmp_path)

    assert html_path == tmp_path / "report.html"
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    # Self-contained: plotly.js is inlined.
    assert "plotly" in content.lower()
    # The strategy trace name should appear somewhere in the serialised figure.
    assert "strategy" in content
    # Non-trivial: more than a few KB.
    assert html_path.stat().st_size > 10_000


def test_write_report_creates_out_dir(tmp_path):
    result = _make_result()
    fig = build_report(result)
    nested = tmp_path / "nested" / "deep"
    html_path = write_report(fig, nested)
    assert html_path.exists()


def test_write_report_svg(tmp_path):
    """SVG export via kaleido.  kaleido is installed; assert it works."""
    result = _make_result()
    fig = build_report(result)
    write_report(fig, tmp_path, svg=True)

    svg_path = tmp_path / "report.svg"
    assert svg_path.exists()
    assert svg_path.stat().st_size > 0
