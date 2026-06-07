from cli.logging.get_logger import get_logger


def test_get_logger_returns_zcrypto_namespaced_logger():
    logger = get_logger("example.workflow")
    assert logger.name == "zcrypto.example.workflow"


def test_get_logger_with_simple_name():
    assert get_logger("cli").name == "zcrypto.cli"
