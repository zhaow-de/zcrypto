"""Run-time caveats surfaced in experiment outputs.

These are concise POINTERS to docs/open-topics/* (the single source of truth for
gaps and roadmap). Do not restate a topic's analysis or fix plan here — only a
one-line summary and the topic id a reader follows for the full picture.
"""

SURVIVORSHIP = {
    "topic": "00005",
    "summary": (
        "universe is survivorship-biased — today's surviving pairs only; "
        "historically-delisted pairs are absent, so the CPCV paths and the holdout "
        "are optimistically inflated (listing dates are respected). "
        "See docs/open-topics/00005-point-in-time-universe.md."
    ),
}

# All caveats applicable to an experiment run (extend as topics warrant).
EXPERIMENT_CAVEATS = [SURVIVORSHIP]

# Short marker for the report subtitle and the stdout line.
SURVIVORSHIP_MARKER = "survivorship-biased universe — see open-topic 00005"
