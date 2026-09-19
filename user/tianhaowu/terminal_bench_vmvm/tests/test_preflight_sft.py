from __future__ import annotations

from pathlib import Path

import preflight_sft
import pytest

from prime_rl.trainer.sft.export_preflight import SFTPreflightError


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--export-root",
        str(tmp_path / "export"),
        "--expected-manifest-sha256",
        "a" * 64,
        "--project-dir",
        str(tmp_path / "project"),
        "--expected-project-revision",
        "b" * 40,
        "--output",
        str(tmp_path / "preflight.json"),
    ]


def test_cli_requires_explicit_exact_provider_json_expectation(tmp_path: Path) -> None:
    with pytest.raises(SFTPreflightError, match="^arguments_invalid$"):
        preflight_sft.parse_args(_arguments(tmp_path))


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("--expected-require-exact-provider-json", True),
        ("--no-expected-require-exact-provider-json", False),
    ],
)
def test_cli_parses_exact_provider_json_expectation(
    tmp_path: Path,
    flag: str,
    expected: bool,
) -> None:
    arguments = _arguments(tmp_path)
    arguments.insert(-2, flag)

    assert preflight_sft.parse_args(arguments).expected_require_exact_provider_json is expected
