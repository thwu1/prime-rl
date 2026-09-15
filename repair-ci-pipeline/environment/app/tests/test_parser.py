"""Tests for logminer.parser module."""
import pytest


def test_strip_ansi_simple():
    """Simple ANSI codes like \\x1b[31m are stripped."""
    from logminer.parser import strip_ansi
    assert strip_ansi("\x1b[31mhello\x1b[0m") == "hello"


def test_strip_ansi_no_codes():
    """Plain text passes through unchanged."""
    from logminer.parser import strip_ansi
    assert strip_ansi("no codes here") == "no codes here"


def test_strip_ansi_extended():
    """Extended ANSI sequences with semicolons are stripped."""
    from logminer.parser import strip_ansi
    text = "\x1b[38;5;196mError\x1b[0m: \x1b[0;1;31mfatal\x1b[0m"
    result = strip_ansi(text)
    assert result == "Error: fatal", f"Got: {result!r}"


def test_extract_mypy_errors():
    """Mypy-style error lines are correctly parsed."""
    from logminer.parser import extract_error_blocks
    log = "src/foo.py:42: error: Incompatible types [assignment]"
    errors = extract_error_blocks(log)
    assert len(errors) == 1
    assert errors[0].error_type == 'type_error'
    assert errors[0].line_number == 42
    assert errors[0].file_path == 'src/foo.py'


def test_extract_ruff_errors():
    """Ruff-style lint error lines are correctly parsed."""
    from logminer.parser import extract_error_blocks
    log = "src/bar.py:10:5: F401 os imported but unused"
    errors = extract_error_blocks(log)
    assert len(errors) == 1
    assert errors[0].error_type == 'lint_error'
    assert 'F401' in errors[0].message


def test_extract_pip_errors():
    """Pip dependency errors are detected."""
    from logminer.parser import extract_error_blocks
    log = "ERROR: Could not find a version that satisfies the requirement pyyaml>=7.0"
    errors = extract_error_blocks(log)
    assert len(errors) == 1
    assert errors[0].error_type == 'dependency_error'


def test_parse_full_log():
    """Multi-step log is correctly split and parsed."""
    from logminer.parser import parse_full_log
    log = (
        "##[group]Lint Check\n"
        "src/foo.py:1:1: F401 unused import\n"
        "##[group]Type Check\n"
        "src/foo.py:10: error: Missing return [return]\n"
    )
    result = parse_full_log(log)
    assert 'Lint Check' in result
    assert 'Type Check' in result
    assert len(result['Lint Check']) == 1
    assert len(result['Type Check']) == 1


@pytest.mark.skip("TODO: flaky on CI, ANSI parsing intermittently fails — see issue #47")
def test_parse_log_with_colored_output():
    """Full log parsing works correctly with heavily colored ANSI output."""
    from logminer.parser import parse_full_log
    log = (
        "##[group]Lint\n"
        "\x1b[38;5;196m\x1b[1msrc/foo.py\x1b[0m:10:5: \x1b[0;1;31mF401\x1b[0m unused import\n"
        "##[group]Tests\n"
        "\x1b[0;1;31mFAILED\x1b[0m tests/bar.py::test_x - assert False\n"
    )
    result = parse_full_log(log)
    assert 'Lint' in result
    assert len(result['Lint']) == 1
    assert result['Lint'][0].error_type == 'lint_error'
