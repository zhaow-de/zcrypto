def test_cli_constants_fetch_concurrency_default_is_five():
    """The documented default. Changing it is a deliberate code change."""
    from cli.constants import CliConstants

    assert CliConstants.FETCH_CONCURRENCY == 5
