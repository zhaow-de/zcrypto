def test_experiment_caveats_shape_and_survivorship_present():
    from cli.experiment.caveats import EXPERIMENT_CAVEATS, SURVIVORSHIP_MARKER

    assert isinstance(EXPERIMENT_CAVEATS, list) and EXPERIMENT_CAVEATS
    for c in EXPERIMENT_CAVEATS:
        assert {"topic", "summary"} <= set(c)
        assert c["topic"] and c["summary"]
    assert "00005" in {c["topic"] for c in EXPERIMENT_CAVEATS}  # survivorship caveat present
    assert isinstance(SURVIVORSHIP_MARKER, str) and SURVIVORSHIP_MARKER.strip()
