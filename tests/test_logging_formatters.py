import json
import logging
import re

import pytest

from cli.logging.formatters import JsonLineFormatter, PlainTextFormatter


def _make_record(
    name="zcrypto.example.workflow",
    level=logging.INFO,
    pathname="/abs/path/to/workflow.py",
    lineno=46,
    msg="show_data: feature head",
    args=(),
    exc_info=None,
    extra=None,
):
    record = logging.LogRecord(name, level, pathname, lineno, msg, args, exc_info)
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
            record.__dict__.setdefault("_zcrypto_extra_keys", set()).add(k)
    return record


def test_json_basic_shape():
    rec = _make_record()
    line = JsonLineFormatter().format(rec)
    obj = json.loads(line)
    assert obj["level"] == "INFO"
    assert obj["logger"] == "zcrypto.example.workflow"
    assert obj["file"] == "workflow.py"
    assert obj["line"] == 46
    assert obj["message"] == "show_data: feature head"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", obj["ts"])
    assert "pid" not in obj and "thread" not in obj
    assert "extra" not in obj
    assert "exception" not in obj


def test_json_includes_extra_when_present():
    rec = _make_record(extra={"head": {"col": [1, 2, 3]}})
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["extra"] == {"head": {"col": [1, 2, 3]}}


def test_json_includes_exception_when_present():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _make_record(exc_info=sys.exc_info())
    obj = json.loads(JsonLineFormatter().format(rec))
    assert "exception" in obj
    assert "ValueError: boom" in obj["exception"]


def test_json_message_uses_args():
    rec = _make_record(msg="hello %s", args=("world",))
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["message"] == "hello world"


def test_json_extra_serializes_non_json_native_via_default_str():
    from pathlib import Path

    rec = _make_record(extra={"path": Path("/tmp/x.log")})
    obj = json.loads(JsonLineFormatter().format(rec))
    assert obj["extra"]["path"] == "/tmp/x.log"


def test_plain_text_basic_shape():
    rec = _make_record()
    line = PlainTextFormatter().format(rec)
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO zcrypto\.example\.workflow"
        r" \[workflow\.py:46\] - show_data: feature head",
        line,
    )
    assert "MainThread" not in line and " - PID" not in line


def test_plain_text_qlib_record():
    rec = _make_record(name="qlib.timer", pathname="/abs/log.py", lineno=127, msg="Time cost: 30.891s | Loading data Done")
    line = PlainTextFormatter().format(rec)
    assert " INFO qlib.timer [log.py:127] - Time cost: 30.891s | Loading data Done" in line
