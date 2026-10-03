from __future__ import annotations

from types import SimpleNamespace

import pytest
from sandoq_provider.config import parse_duration_seconds
from sandoq_provider.utils import duration_seconds, exception_http_status


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 7.0), ("", 7.0), ("250ms", 0.25), ("3s", 3.0), ("2m", 120.0), ("1.5h", 5400.0)],
)
def test_duration_seconds(value: str | None, expected: float) -> None:
    assert duration_seconds(value, 7.0) == expected


def test_legacy_config_duration_parser_keeps_invalid_value_fallback() -> None:
    assert parse_duration_seconds("not-a-duration", 7.0) == 7.0


def test_exception_http_status_walks_wrapped_errors() -> None:
    inner = RuntimeError("request failed")
    inner.response = SimpleNamespace(status_code=503)  # type: ignore[attr-defined]
    error = RuntimeError("wrapped")
    error.__cause__ = inner

    assert exception_http_status(error) == 503
