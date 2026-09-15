#!/usr/bin/env python3
"""Tests for the TAC optimizer pipeline."""
import subprocess
import os
import re
import tempfile
import json
import pytest

PROGRAMS = ['propagation.tac', 'loop_analysis.tac', 'diamond_flow.tac', 'tricky.tac']
PROGRAM_STEMS = ['propagation', 'loop_analysis', 'diamond_flow', 'tricky']
INTERPRETER = '/app/tac_interpreter.py'
OPTIMIZER = '/app/optimizer.py'
PROGRAM_DIR = '/app/programs'
CFG_DIR = '/app/cfg'
OPT_DIR = '/app/optimized'
REPORT_PATH = '/app/report.json'
MAKEFILE_PATH = '/app/Makefile'

EXPECTED_OUTPUTS = {
    'propagation.tac': ['930', '40', '900'],
    'loop_analysis.tac': ['1225', '500', '500'],
    'diamond_flow.tac': ['40', '-20', '0', '161'],
    'tricky.tac': ['20', '720', '42', '203'],
}

FULLY_CONSTANT_PROGRAMS = ['propagation.tac', 'diamond_flow.tac']


def run_interpreter(program_path):
    """Run the TAC interpreter on a program and return output lines."""
    result = subprocess.run(
        ['python3', INTERPRETER, program_path],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Interpreter failed on {program_path}: {result.stderr}"
    )
    return [line for line in result.stdout.strip().split('\n') if line]


def run_optimizer(program_path):
    """Run the optimizer on a program and return optimized TAC text."""
    result = subprocess.run(
        ['python3', OPTIMIZER, program_path],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Optimizer failed on {program_path}: {result.stderr}"
    )
    return result.stdout.strip()


def count_instructions(program_text):
    """Count non-blank, non-comment instructions in TAC text."""
    return sum(1 for line in program_text.strip().split('\n')
               if line.strip() and not line.strip().startswith('#'))


# ── Optimizer correctness tests ──────────────────────────────────


@pytest.mark.parametrize("program", PROGRAMS)
def test_interpreter_baseline(program):
    """Verify the interpreter itself produces the expected output."""
    orig_path = os.path.join(PROGRAM_DIR, program)
    output = run_interpreter(orig_path)
    assert output == EXPECTED_OUTPUTS[program], (
        f"Interpreter baseline mismatch for {program}: "
        f"got {output}, expected {EXPECTED_OUTPUTS[program]}"
    )


@pytest.mark.parametrize("program", PROGRAMS)
def test_optimizer_correctness(program):
    """Optimized program must produce identical output to original."""
    orig_path = os.path.join(PROGRAM_DIR, program)
    orig_output = run_interpreter(orig_path)
    optimized_code = run_optimizer(orig_path)

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.tac', delete=False
    ) as f:
        f.write(optimized_code)
        opt_path = f.name

    try:
        opt_output = run_interpreter(opt_path)
    finally:
        os.unlink(opt_path)

    assert orig_output == opt_output, (
        f"Output mismatch for {program}:\n"
        f"  Original:  {orig_output}\n"
        f"  Optimized: {opt_output}\n"
        f"  Optimized code:\n{optimized_code}"
    )


# ── Reduction tests ────────────────────────────────────────────────


@pytest.mark.parametrize("program", PROGRAMS)
def test_optimizer_reduces_code(program):
    """Optimized program must have strictly fewer instructions."""
    orig_path = os.path.join(PROGRAM_DIR, program)
    with open(orig_path) as f:
        orig_count = count_instructions(f.read())
    optimized_code = run_optimizer(orig_path)
    opt_count = count_instructions(optimized_code)
    assert opt_count < orig_count, (
        f"{program}: no reduction ({orig_count} -> {opt_count})"
    )


@pytest.mark.parametrize("program", FULLY_CONSTANT_PROGRAMS)
def test_fully_constant_programs(program):
    """Fully-reducible programs must collapse to near-pure PRINT sequences."""
    orig_path = os.path.join(PROGRAM_DIR, program)
    optimized_code = run_optimizer(orig_path)

    non_print_non_label = sum(
        1 for line in optimized_code.strip().split('\n')
        if line.strip() and not line.strip().startswith('#')
        and not line.strip().startswith('PRINT')
        and not line.strip().startswith('LABEL')
    )
    assert non_print_non_label <= 5, (
        f"{program}: expected near-full reduction, "
        f"but got {non_print_non_label} non-PRINT/non-LABEL instructions.\n"
        f"Optimized code:\n{optimized_code}"
    )


def test_overall_reduction():
    """Total instruction reduction across all programs must be >= 40%."""
    total_orig = 0
    total_opt = 0
    for program in PROGRAMS:
        orig_path = os.path.join(PROGRAM_DIR, program)
        with open(orig_path) as f:
            total_orig += count_instructions(f.read())
        optimized_code = run_optimizer(orig_path)
        total_opt += count_instructions(optimized_code)

    reduction = 1 - (total_opt / total_orig)
    assert reduction >= 0.40, (
        f"Overall reduction {reduction:.1%} < 40% "
        f"({total_orig} -> {total_opt} instructions)"
    )


# ── Structural tests ──────────────────────────────────────────────


def test_loop_preserved():
    """The factorial loop in tricky.tac must NOT be eliminated."""
    orig_path = os.path.join(PROGRAM_DIR, 'tricky.tac')
    optimized_code = run_optimizer(orig_path)

    has_goto = any(
        line.strip().startswith('GOTO')
        for line in optimized_code.split('\n')
        if line.strip() and not line.strip().startswith('#')
    )
    has_label = any(
        line.strip().startswith('LABEL')
        for line in optimized_code.split('\n')
        if line.strip() and not line.strip().startswith('#')
    )
    assert has_goto and has_label, (
        "tricky.tac: factorial loop was incorrectly eliminated. "
        "Optimized code must preserve the loop.\n"
        f"Optimized code:\n{optimized_code}"
    )


@pytest.mark.parametrize("program", PROGRAMS)
def test_optimizer_valid_tac(program):
    """Optimized output must be valid TAC parseable by the interpreter."""
    orig_path = os.path.join(PROGRAM_DIR, program)
    optimized_code = run_optimizer(orig_path)

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.tac', delete=False
    ) as f:
        f.write(optimized_code)
        opt_path = f.name

    try:
        result = subprocess.run(
            ['python3', INTERPRETER, opt_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Optimized {program} is not valid TAC: {result.stderr}\n"
            f"Code:\n{optimized_code}"
        )
    finally:
        os.unlink(opt_path)


# ── Makefile tests ────────────────────────────────────────────────


def test_makefile_exists():
    """Makefile must exist at /app/Makefile."""
    assert os.path.isfile(MAKEFILE_PATH), "Makefile not found at /app/Makefile"


def test_makefile_has_targets():
    """Makefile must define all required targets."""
    assert os.path.isfile(MAKEFILE_PATH), "Makefile not found"
    with open(MAKEFILE_PATH) as f:
        content = f.read()
    for target in ['optimize', 'cfg', 'verify', 'report', 'all']:
        pattern = re.compile(rf'^{target}\s*:', re.MULTILINE)
        assert pattern.search(content), (
            f"Makefile missing target definition: {target}"
        )


def test_makefile_syntax_valid():
    """Makefile must be syntactically valid (dry-run succeeds)."""
    assert os.path.isfile(MAKEFILE_PATH), "Makefile not found"
    result = subprocess.run(
        ['make', '-n', '-f', MAKEFILE_PATH, 'all'],
        capture_output=True, text=True, timeout=10,
        cwd='/app'
    )
    assert result.returncode == 0, (
        f"Makefile syntax error (make -n failed): {result.stderr}"
    )


# ── CFG visualization tests ──────────────────────────────────────


@pytest.mark.parametrize("stem", PROGRAM_STEMS)
def test_cfg_dot_files_exist(stem):
    """DOT control flow graph files must exist for each program."""
    for suffix in ['_before.dot', '_after.dot']:
        path = os.path.join(CFG_DIR, stem + suffix)
        assert os.path.isfile(path), f"Missing CFG DOT file: {path}"


@pytest.mark.parametrize("stem", PROGRAM_STEMS)
def test_cfg_svg_files_exist(stem):
    """SVG renders of CFGs must exist for each program."""
    for suffix in ['_before.svg', '_after.svg']:
        path = os.path.join(CFG_DIR, stem + suffix)
        assert os.path.isfile(path), f"Missing CFG SVG file: {path}"


@pytest.mark.parametrize("stem", PROGRAM_STEMS)
def test_cfg_dot_renderable(stem):
    """DOT files must be renderable by graphviz dot command."""
    for suffix in ['_before.dot', '_after.dot']:
        path = os.path.join(CFG_DIR, stem + suffix)
        if not os.path.isfile(path):
            pytest.skip(f"DOT file not found: {path}")
        result = subprocess.run(
            ['dot', '-Tsvg', path],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"graphviz dot failed on {path}: {result.stderr}"
        )


@pytest.mark.parametrize("stem", PROGRAM_STEMS)
def test_cfg_dot_has_blocks(stem):
    """DOT files must contain digraph with labeled basic-block nodes."""
    path = os.path.join(CFG_DIR, stem + '_before.dot')
    if not os.path.isfile(path):
        pytest.skip(f"DOT file not found: {path}")
    with open(path) as f:
        content = f.read()
    assert 'digraph' in content.lower() or 'graph' in content.lower(), (
        f"{path} does not contain a graph definition"
    )
    assert 'label=' in content or 'label =' in content, (
        f"{path} has no labeled nodes (expected basic blocks with instructions)"
    )


# ── Report tests ──────────────────────────────────────────────────


def test_report_exists():
    """report.json must exist at /app/report.json."""
    assert os.path.isfile(REPORT_PATH), f"Report not found at {REPORT_PATH}"


def test_report_valid_json():
    """report.json must be a valid JSON array with one entry per program."""
    assert os.path.isfile(REPORT_PATH), "report.json not found"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "report.json must be a JSON array"
    assert len(data) == len(PROGRAMS), (
        f"report.json should have {len(PROGRAMS)} entries, got {len(data)}"
    )


def test_report_structure():
    """Each report entry must have required fields with correct types."""
    assert os.path.isfile(REPORT_PATH), "report.json not found"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    required_fields = {
        'program', 'original_instructions', 'optimized_instructions',
        'reduction_pct', 'semantic_match'
    }
    for entry in data:
        missing = required_fields - set(entry.keys())
        assert not missing, f"report.json entry missing fields: {missing}"
        assert isinstance(entry['original_instructions'], int), (
            "original_instructions must be int"
        )
        assert isinstance(entry['optimized_instructions'], int), (
            "optimized_instructions must be int"
        )
        assert isinstance(entry['reduction_pct'], (int, float)), (
            "reduction_pct must be numeric"
        )
        assert entry['semantic_match'] is True, (
            f"Semantic mismatch reported for {entry.get('program')}"
        )


def test_report_jq_processable():
    """report.json must be processable by jq."""
    if not os.path.isfile(REPORT_PATH):
        pytest.skip("report.json not found")
    result = subprocess.run(
        ['jq', '.[] | .program', REPORT_PATH],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, (
        f"jq failed on report.json: {result.stderr}"
    )
    programs = [line.strip().strip('"') for line in result.stdout.strip().split('\n')]
    assert len(programs) == len(PROGRAMS), (
        f"jq returned {len(programs)} program entries, expected {len(PROGRAMS)}"
    )
