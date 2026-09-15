
import json
import os
import pytest

# Expected outputs under the nonstandard SOS rules for 10 regular programs
EXPECTED_OUTPUTS = {
    "arith": {"a": 30, "b": 6, "c": 24, "d": 36, "e": 0},
    "cond": {"r": 1, "x": 5, "y": 5},
    "loop": {"i": 5, "s": 10},
    "nested": {"a": 8, "b": 3, "c": 2, "r": 5},
    "break_find": {"found": 5, "i": 5},
    "continue_sum": {"i": 1, "s": 4},
    "halt_loop": {"x": 3, "y": 12},
    "nested_control": {"a": 0, "b": 10, "c": 3, "d": 2},
    "nested_logic": {"a": 10, "b": 5, "c": 3, "r": 22},
    "power_acc": {"acc": 81, "base": 3, "exp": 4, "i": 4},
}

# What standard (conventional) semantics would produce — used for anti-cheat
STANDARD_OUTPUTS = {
    "arith": {"a": 30, "b": 6, "c": 36, "d": 24, "e": 864},
    "cond": {"r": 10, "x": 5, "y": 5},
    "loop": {"i": 0, "s": 0},
    "nested": {"a": 8, "b": 3, "c": 2, "r": 2},
    "break_find": {"found": 0, "i": 10},
    "continue_sum": {"i": 10, "s": 0},
    "halt_loop": {"x": 0, "y": 1},
    "nested_control": {"a": 5, "b": 0, "c": 1, "d": 0},
    "nested_logic": {"a": 10, "b": 5, "c": 3, "r": -9},
    "power_acc": {"acc": 1, "base": 3, "exp": 4, "i": 0},
}

# Expected outputs for the fixed buggy programs
EXPECTED_FIXED_OUTPUTS = {
    "dot_product": {"a1": 3, "a2": 7, "b1": 4, "b2": 2, "dot": 26, "p1": 12, "p2": 14},
    "find_max": {"a": 7, "b": 19, "c": 4, "max": 19},
    "sum_loop": {"i": 6, "n": 5, "sum": 15},
}

# What the UNFIXED buggy programs produce under nonstandard semantics — anti-cheat
BUGGY_OUTPUTS = {
    "dot_product": {"a1": 3, "a2": 7, "b1": 4, "b2": 2, "dot": -3, "p1": 0, "p2": 3},
    "find_max": {"a": 7, "b": 19, "c": 4, "max": 4},
    "sum_loop": {"i": 1, "n": 5, "sum": 0},
}

# Expected outputs for the synthesized programs (Part 3)
SYNTH_CHALLENGES = {
    "gcd": {
        "required_output": {"gcd": 6},
        "must_contain": ["while", "%"],
        "input_assignments": ["48", "18"],
        "min_lines": 8,
    },
    "fibonacci": {
        "required_output": {"fib": 21},
        "must_contain": ["while"],
        "input_assignments": ["8"],
        "min_lines": 10,
    },
    "sort3": {
        "required_output": {"a": 5, "b": 17, "c": 23, "sorted": 1},
        "must_contain": ["if"],
        "input_assignments": ["17", "5", "23"],
        "min_lines": 10,
    },
}


# ─── Part 1: Regular program tests ───


@pytest.mark.parametrize("program_name", list(EXPECTED_OUTPUTS.keys()))
def test_output_exists(program_name):
    """Each program must produce a JSON output file."""
    path = f"/app/output/{program_name}.json"
    assert os.path.exists(path), f"Output file {path} not found"


@pytest.mark.parametrize("program_name", list(EXPECTED_OUTPUTS.keys()))
def test_output_correct(program_name):
    """Each output must contain the correct variable values under the nonstandard semantics."""
    path = f"/app/output/{program_name}.json"
    assert os.path.exists(path), f"Output file {path} not found"
    with open(path) as f:
        actual = json.load(f)
    expected = EXPECTED_OUTPUTS[program_name]
    for var, val in expected.items():
        assert var in actual, (
            f"Variable '{var}' not found in output for {program_name}"
        )
        assert actual[var] == val, (
            f"{program_name}: variable '{var}' expected {val}, got {actual[var]}"
        )


def test_not_standard_semantics():
    """Verify the interpreter doesn't just use standard (conventional) semantics.

    At least one program's output must differ from standard semantics results,
    proving the interpreter actually follows the provided SOS rules.
    """
    differs = False
    for prog_name, standard_output in STANDARD_OUTPUTS.items():
        path = f"/app/output/{prog_name}.json"
        if not os.path.exists(path):
            continue
        with open(path) as f:
            actual = json.load(f)
        for var, std_val in standard_output.items():
            if var in actual and actual[var] != std_val:
                differs = True
                break
        if differs:
            break
    assert differs, (
        "All outputs match standard semantics — interpreter may not follow "
        "the provided SOS rules"
    )


def test_summary_exists():
    """summary.json must exist."""
    path = "/app/output/summary.json"
    assert os.path.exists(path), "summary.json not found"


def test_summary_correct():
    """summary.json must contain all program results merged correctly."""
    path = "/app/output/summary.json"
    assert os.path.exists(path), "summary.json not found"
    with open(path) as f:
        summary = json.load(f)

    assert isinstance(summary, dict), "summary.json must be a JSON object"

    for prog_name, expected in EXPECTED_OUTPUTS.items():
        assert prog_name in summary, (
            f"Program '{prog_name}' missing from summary.json"
        )
        actual = summary[prog_name]
        for var, val in expected.items():
            assert var in actual, (
                f"summary.json[{prog_name}]: variable '{var}' missing"
            )
            assert actual[var] == val, (
                f"summary.json[{prog_name}][{var}]: expected {val}, got {actual[var]}"
            )


def test_summary_keys_sorted():
    """summary.json keys must be sorted alphabetically."""
    path = "/app/output/summary.json"
    if not os.path.exists(path):
        pytest.skip("summary.json not found")
    with open(path) as f:
        raw = f.read()
    summary = json.loads(raw)
    keys = list(summary.keys())
    assert keys == sorted(keys), (
        f"summary.json keys are not sorted: {keys}"
    )


def test_lark_grammar_present():
    """The Lark grammar file must still be present and usable."""
    assert os.path.exists("/app/imp.lark"), "Lark grammar file missing"
    try:
        from lark import Lark
        with open("/app/imp.lark") as f:
            grammar = f.read()
        parser = Lark(grammar, start='start', parser='earley')
        tree = parser.parse("int x;")
        assert tree is not None
    except Exception as e:
        pytest.fail(f"Lark grammar is not functional: {e}")


# ─── Part 2: Semantic debugging tests ───


@pytest.mark.parametrize("program_name", list(EXPECTED_FIXED_OUTPUTS.keys()))
def test_fixed_output_exists(program_name):
    """Each fixed program must produce a JSON output file."""
    path = f"/app/output/{program_name}_fixed.json"
    assert os.path.exists(path), f"Fixed output file {path} not found"


@pytest.mark.parametrize("program_name", list(EXPECTED_FIXED_OUTPUTS.keys()))
def test_fixed_output_correct(program_name):
    """Each fixed program's output must match the intended computation."""
    path = f"/app/output/{program_name}_fixed.json"
    assert os.path.exists(path), f"Fixed output file {path} not found"
    with open(path) as f:
        actual = json.load(f)
    expected = EXPECTED_FIXED_OUTPUTS[program_name]
    for var, val in expected.items():
        assert var in actual, (
            f"Variable '{var}' not found in fixed output for {program_name}"
        )
        assert actual[var] == val, (
            f"{program_name}_fixed: variable '{var}' expected {val}, got {actual[var]}"
        )


@pytest.mark.parametrize("program_name", list(EXPECTED_FIXED_OUTPUTS.keys()))
def test_fixed_program_exists(program_name):
    """Each fixed .imp program file must exist."""
    path = f"/app/output/{program_name}_fixed.imp"
    assert os.path.exists(path), f"Fixed program file {path} not found"


@pytest.mark.parametrize("program_name", list(EXPECTED_FIXED_OUTPUTS.keys()))
def test_fixed_program_parseable(program_name):
    """Each fixed program must be parseable by the Lark grammar."""
    imp_path = f"/app/output/{program_name}_fixed.imp"
    if not os.path.exists(imp_path):
        pytest.skip(f"{imp_path} not found")
    try:
        from lark import Lark
        with open("/app/imp.lark") as f:
            grammar = f.read()
        parser = Lark(grammar, start='start', parser='earley')
        with open(imp_path) as f:
            source = f.read()
        tree = parser.parse(source)
        assert tree is not None
    except Exception as e:
        pytest.fail(f"Fixed program {program_name} is not parseable: {e}")


@pytest.mark.parametrize("program_name", list(BUGGY_OUTPUTS.keys()))
def test_fixed_differs_from_buggy(program_name):
    """Fixed output must differ from what the unfixed buggy program produces.

    This verifies the agent actually diagnosed and fixed the semantic bugs
    rather than just running the unfixed program or hardcoding values.
    """
    path = f"/app/output/{program_name}_fixed.json"
    if not os.path.exists(path):
        pytest.skip(f"{path} not found")
    with open(path) as f:
        fixed_output = json.load(f)
    buggy_output = BUGGY_OUTPUTS[program_name]
    differs = False
    for var, buggy_val in buggy_output.items():
        if var in fixed_output and fixed_output[var] != buggy_val:
            differs = True
            break
    assert differs, (
        f"Fixed output for {program_name} matches the buggy output — "
        f"the program may not have been properly fixed"
    )


def test_summary_excludes_fixed():
    """summary.json should only contain the 10 regular programs, not fixed programs."""
    path = "/app/output/summary.json"
    if not os.path.exists(path):
        pytest.skip("summary.json not found")
    with open(path) as f:
        summary = json.load(f)
    for key in summary:
        assert "_fixed" not in key, (
            f"summary.json should not contain fixed program entries, found '{key}'"
        )


# ─── Part 3: Program synthesis tests ───


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_imp_exists(challenge_name):
    """Each synthesized program must exist as an .imp file."""
    path = f"/app/output/{challenge_name}_synth.imp"
    assert os.path.exists(path), f"Synthesized program {path} not found"


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_imp_parseable(challenge_name):
    """Each synthesized program must be parseable by the Lark grammar."""
    imp_path = f"/app/output/{challenge_name}_synth.imp"
    if not os.path.exists(imp_path):
        pytest.skip(f"{imp_path} not found")
    try:
        from lark import Lark
        with open("/app/imp.lark") as f:
            grammar = f.read()
        parser = Lark(grammar, start='start', parser='earley')
        with open(imp_path) as f:
            source = f.read()
        tree = parser.parse(source)
        assert tree is not None
    except Exception as e:
        pytest.fail(f"Synthesized program {challenge_name} is not parseable: {e}")


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_output_exists(challenge_name):
    """Each synthesized program must produce a JSON output file."""
    path = f"/app/output/{challenge_name}_synth.json"
    assert os.path.exists(path), f"Synthesized output {path} not found"


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_output_correct(challenge_name):
    """Each synthesized program's output must match the required result."""
    path = f"/app/output/{challenge_name}_synth.json"
    assert os.path.exists(path), f"Synthesized output {path} not found"
    with open(path) as f:
        actual = json.load(f)
    challenge = SYNTH_CHALLENGES[challenge_name]
    for var, val in challenge["required_output"].items():
        assert var in actual, (
            f"Variable '{var}' not found in synthesized output for {challenge_name}"
        )
        assert actual[var] == val, (
            f"{challenge_name}_synth: variable '{var}' expected {val}, got {actual[var]}"
        )


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_structural_constraints(challenge_name):
    """Synthesized programs must contain required syntactic elements."""
    imp_path = f"/app/output/{challenge_name}_synth.imp"
    if not os.path.exists(imp_path):
        pytest.skip(f"{imp_path} not found")
    with open(imp_path) as f:
        source = f.read()
    challenge = SYNTH_CHALLENGES[challenge_name]
    for keyword in challenge["must_contain"]:
        assert keyword in source, (
            f"Synthesized program {challenge_name} must contain '{keyword}' "
            f"but it was not found in the source"
        )


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_minimum_complexity(challenge_name):
    """Synthesized programs must have minimum complexity (not trivially hardcoded)."""
    imp_path = f"/app/output/{challenge_name}_synth.imp"
    if not os.path.exists(imp_path):
        pytest.skip(f"{imp_path} not found")
    with open(imp_path) as f:
        source = f.read()
    lines = [line.strip() for line in source.strip().split('\n') if line.strip()]
    challenge = SYNTH_CHALLENGES[challenge_name]
    assert len(lines) >= challenge["min_lines"], (
        f"Synthesized program {challenge_name} has only {len(lines)} non-empty lines, "
        f"expected at least {challenge['min_lines']} (program appears trivially hardcoded)"
    )


@pytest.mark.parametrize("challenge_name", list(SYNTH_CHALLENGES.keys()))
def test_synth_contains_inputs(challenge_name):
    """Synthesized programs must initialize the specified input values."""
    imp_path = f"/app/output/{challenge_name}_synth.imp"
    if not os.path.exists(imp_path):
        pytest.skip(f"{imp_path} not found")
    with open(imp_path) as f:
        source = f.read()
    challenge = SYNTH_CHALLENGES[challenge_name]
    for val in challenge["input_assignments"]:
        assert val in source, (
            f"Synthesized program {challenge_name} must contain input value '{val}' "
            f"but it was not found — the program may not use the specified inputs"
        )
