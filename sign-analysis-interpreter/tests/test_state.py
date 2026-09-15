
import subprocess
import json
import os
import pytest


EXPECTED = {
    "basic": {"x": "pos", "y": "neg", "z": "top", "w": "neg", "v": "pos"},
    "branch": {"x": "pos", "y": "neg", "z": "pos"},
    "loop": {"i": "top", "s": "pos"},
    "interproc": {"a": "pos", "b": "neg", "c": "neg"},
    "context": {"a": "pos", "b": "pos", "c": "pos"},
}


def test_analyzer_exists():
    assert os.path.exists("/app/analyzer.py"), (
        "analyzer.py not found at /app/analyzer.py"
    )


def test_grammar_file_exists():
    """Grammar file must exist at /app/grammar.lark."""
    assert os.path.exists("/app/grammar.lark"), (
        "grammar.lark not found at /app/grammar.lark"
    )


def test_grammar_valid():
    """The grammar file must be a valid Lark grammar."""
    from lark import Lark
    with open("/app/grammar.lark") as f:
        grammar_text = f.read()
    Lark(grammar_text)


def test_grammar_parses_all_programs():
    """The grammar must successfully parse every test program."""
    from lark import Lark
    with open("/app/grammar.lark") as f:
        grammar_text = f.read()
    parser = Lark(grammar_text)
    for prog_name in EXPECTED:
        prog_path = f"/app/programs/{prog_name}.lang"
        with open(prog_path) as f:
            code = f.read()
        tree = parser.parse(code)
        assert tree is not None, f"Grammar failed to parse {prog_name}.lang"


def test_analyzer_uses_lark():
    """The analyzer must use the Lark parser generator library."""
    with open("/app/analyzer.py") as f:
        code = f.read()
    assert "lark" in code, (
        "analyzer.py does not appear to reference the Lark library"
    )


def test_makefile_check_grammar():
    """make check-grammar must succeed."""
    result = subprocess.run(
        ["make", "--no-print-directory", "-C", "/app", "check-grammar"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"make check-grammar failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_makefile_analyze():
    """make analyze must produce correct JSON for a test program."""
    result = subprocess.run(
        ["make", "--no-print-directory", "-C", "/app", "analyze", "PROG=programs/basic.lang"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"make analyze failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = json.loads(result.stdout.strip())
    assert output["x"] == "pos", f"Expected x=pos, got {output.get('x')}"


@pytest.mark.parametrize("program_name", list(EXPECTED.keys()))
def test_analyzer_output(program_name):
    prog_path = f"/app/programs/{program_name}.lang"
    assert os.path.exists(prog_path), f"Program file {prog_path} not found"

    result = subprocess.run(
        ["python3", "/app/analyzer.py", prog_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer failed on {program_name}.lang with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Analyzer output for {program_name}.lang is not valid JSON: {e}\n"
            f"stdout: {result.stdout}"
        )

    expected = EXPECTED[program_name]
    for var, expected_sign in expected.items():
        assert var in output, (
            f"Variable '{var}' missing from output for {program_name}.lang. "
            f"Got keys: {list(output.keys())}"
        )
        assert output[var] == expected_sign, (
            f"{program_name}.lang: variable '{var}' expected '{expected_sign}', "
            f"got '{output[var]}'"
        )


@pytest.mark.parametrize("program_name", ["interproc", "context"])
def test_context_sensitivity_required(program_name):
    """Verify that context-insensitive results (all top) are NOT accepted."""
    expected = EXPECTED[program_name]
    has_non_top = any(v != "top" for v in expected.values())
    assert has_non_top, (
        f"Test design error: {program_name} should require context sensitivity"
    )
