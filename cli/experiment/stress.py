"""Named market-stress windows for experiment reporting."""

from __future__ import annotations

# (label, start_date, end_date) ISO date strings — inclusive crisis windows.
STRESS_WINDOWS: list[tuple[str, str, str]] = [
    ("LUNA", "2022-05-07", "2022-05-16"),
    ("FTX", "2022-11-06", "2022-11-14"),
]
