def test_experiment_caveats_shape_and_survivorship_present():
    from cli.experiment.caveats import EXPERIMENT_CAVEATS, SURVIVORSHIP_MARKER

    assert isinstance(EXPERIMENT_CAVEATS, list) and EXPERIMENT_CAVEATS
    for c in EXPERIMENT_CAVEATS:
        assert {"topic", "summary"} <= set(c)
        assert c["topic"] and c["summary"]
    assert "T0005" in {c["topic"] for c in EXPERIMENT_CAVEATS}  # survivorship caveat present
    assert isinstance(SURVIVORSHIP_MARKER, str) and SURVIVORSHIP_MARKER.strip()


def test_point_in_time_caveat_points_to_t0005():
    from cli.experiment.caveats import POINT_IN_TIME

    assert POINT_IN_TIME["topic"] == "T0005"
    assert "survivorship-free" in POINT_IN_TIME["summary"]
    assert "T0005-point-in-time-universe.md" in POINT_IN_TIME["summary"]


def test_pit_marker_says_survivorship_free():
    from cli.experiment.caveats import PIT_MARKER, SURVIVORSHIP_MARKER

    assert "survivorship-free" in PIT_MARKER
    assert PIT_MARKER != SURVIVORSHIP_MARKER
