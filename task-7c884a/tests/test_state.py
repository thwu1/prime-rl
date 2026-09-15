
import subprocess
import os
import re
import json

TESTS_DIR = '/app/tests'


def _assert_feature_present(pattern, name):
    """Check that at least one .test file matches the regex pattern."""
    for f in os.listdir(TESTS_DIR):
        if f.endswith('.test'):
            content = open(os.path.join(TESTS_DIR, f)).read()
            if re.search(pattern, content):
                return
    assert False, f"No .test file uses {name}"


def _load_analysis():
    with open('/app/analysis.json') as f:
        return json.load(f)


# ---- Structural checks ----

def test_lit_config_exists():
    """lit.cfg.py must exist and reference ir-opt."""
    path = f'{TESTS_DIR}/lit.cfg.py'
    assert os.path.exists(path), "lit.cfg.py not found in /app/tests/"
    with open(path) as f:
        content = f.read()
    assert 'ir-opt' in content, "lit.cfg.py must reference the ir-opt tool"


def test_minimum_test_files():
    """At least 6 .test files must exist."""
    test_files = [f for f in os.listdir(TESTS_DIR) if f.endswith('.test')]
    assert len(test_files) >= 6, (
        f"Need >= 6 .test files, found {len(test_files)}: {test_files}"
    )


def test_each_test_has_run_line():
    """Every .test file must have a // RUN: directive."""
    for f in os.listdir(TESTS_DIR):
        if f.endswith('.test'):
            content = open(os.path.join(TESTS_DIR, f)).read()
            assert '// RUN:' in content, f"{f} is missing a // RUN: line"


def test_each_test_has_checks():
    """Every .test file must have at least 3 CHECK directives."""
    for f in os.listdir(TESTS_DIR):
        if f.endswith('.test'):
            content = open(os.path.join(TESTS_DIR, f)).read()
            checks = len(re.findall(r'//\s*CHECK', content))
            assert checks >= 3, (
                f"{f} has only {checks} CHECK directives (need >= 3)"
            )


# ---- lit execution ----

def test_lit_all_pass():
    """All tests must pass: lit /app/tests/ -v exits 0."""
    result = subprocess.run(
        ['lit', TESTS_DIR, '-v'],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"lit failed (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout[-3000:]}\n"
        f"STDERR:\n{result.stderr[-1000:]}"
    )


# ---- FileCheck feature coverage ----

def test_feature_check_label():
    """At least one test uses CHECK-LABEL."""
    _assert_feature_present(r'//\s*CHECK-LABEL:', 'CHECK-LABEL')


def test_feature_check_dag():
    """At least one test uses CHECK-DAG."""
    _assert_feature_present(r'//\s*CHECK-DAG:', 'CHECK-DAG')


def test_feature_check_not():
    """At least one test uses CHECK-NOT."""
    _assert_feature_present(r'//\s*CHECK-NOT:', 'CHECK-NOT')


def test_feature_check_same():
    """At least one test uses CHECK-SAME."""
    _assert_feature_present(r'//\s*CHECK-SAME:', 'CHECK-SAME')


def test_feature_variable_capture():
    """At least one test uses variable capture [[VAR:pattern]]."""
    _assert_feature_present(r'\[\[\w+:', 'variable capture ([[VAR:pattern]])')


def test_feature_implicit_check_not():
    """At least one test uses --implicit-check-not in a RUN line."""
    _assert_feature_present(r'--implicit-check-not', '--implicit-check-not')


def test_feature_split_input_file():
    """At least one test uses --split-input-file in a RUN line."""
    _assert_feature_present(r'--split-input-file', '--split-input-file')


# ---- Analysis JSON correctness ----

def test_analysis_exists():
    """analysis.json must exist and be valid JSON."""
    assert os.path.exists('/app/analysis.json'), "analysis.json not found"
    data = json.load(open('/app/analysis.json'))
    assert isinstance(data, dict), "analysis.json must be a JSON object"


def test_analysis_q1_fold_chain():
    """Q1: --constfold on fold_chain.ir yields final constant 26 (3*7+5)."""
    data = _load_analysis()
    assert data.get('q1_fold_chain_result') == 26, (
        f"Expected 26, got {data.get('q1_fold_chain_result')}"
    )


def test_analysis_q2_canon_dead_code():
    """Q2: --canonicalize alone does NOT remove unreferenced constants."""
    data = _load_analysis()
    assert data.get('q2_canonicalize_removes_dead_code') is False, (
        f"Expected false, got {data.get('q2_canonicalize_removes_dead_code')}"
    )


def test_analysis_q3_cse_commutative():
    """Q3: CSE does NOT recognize addi(a,b) and addi(b,a) as equivalent."""
    data = _load_analysis()
    assert data.get('q3_cse_commutative_aware') is False, (
        f"Expected false, got {data.get('q3_cse_commutative_aware')}"
    )


def test_analysis_q4_mul_zero():
    """Q4: --canonicalize replaces muli(x,0) with arith.constant."""
    data = _load_analysis()
    assert data.get('q4_mul_zero_replacement_opcode') == 'arith.constant', (
        f"Expected 'arith.constant', got {data.get('q4_mul_zero_replacement_opcode')}"
    )


def test_analysis_q5_remsi_divzero():
    """Q5: --constfold does NOT fold remsi when divisor is zero."""
    data = _load_analysis()
    assert data.get('q5_constfold_handles_remsi_divzero') is False, (
        f"Expected false, got {data.get('q5_constfold_handles_remsi_divzero')}"
    )


def test_analysis_q6_combined():
    """Q6: --cse --constfold --canonicalize --dce on combined.ir leaves 2 ops."""
    data = _load_analysis()
    assert data.get('q6_combined_ops_remaining') == 2, (
        f"Expected 2, got {data.get('q6_combined_ops_remaining')}"
    )
