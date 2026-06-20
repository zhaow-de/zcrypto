"""Run-time caveats surfaced in experiment outputs.

These are concise POINTERS to docs/open-topics/* (the single source of truth for
gaps and roadmap). Do not restate a topic's analysis or fix plan here — only a
one-line summary and the topic id a reader follows for the full picture.
"""

SURVIVORSHIP = {
    "topic": "T0005",
    "summary": (
        "universe is survivorship-biased — today's surviving pairs only; "
        "historically-delisted pairs are absent, so the CPCV paths and the holdout "
        "are optimistically inflated (listing dates are respected). "
        "See docs/open-topics/T0005-point-in-time-universe.md."
    ),
}

POINT_IN_TIME = {
    "topic": "T0005",
    "summary": (
        "point-in-time universe — historically delisted/faded majors are included over their "
        "real listing ranges, so the run is survivorship-free. Delisting-loss is captured by "
        "qlib's position freeze at the last close (frozen capital is not redeployed — a "
        "conservative imperfection). See docs/open-topics/T0005-point-in-time-universe.md."
    ),
}

# All caveats applicable to an experiment run (extend as topics warrant).
EXPERIMENT_CAVEATS = [SURVIVORSHIP]

# Short marker for the report subtitle and the stdout line.
SURVIVORSHIP_MARKER = "survivorship-biased universe — see open-topic T0005"

# Marker for the report subtitle + stdout line when --pit-universe is on (the run is
# survivorship-free, so the SURVIVORSHIP_MARKER above must not appear).
PIT_MARKER = "point-in-time universe (survivorship-free) — see open-topic T0005"
