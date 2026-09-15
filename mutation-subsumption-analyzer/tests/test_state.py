
"""Verification tests for the Mutation Subsumption Analyzer output."""

import json
import os
import subprocess
import sys


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _load(name):
    with open(f'/app/results/{name}') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Output files exist
# ---------------------------------------------------------------------------

def test_output_files_exist():
    for name in ['metrics.json', 'mutants.json', 'kill_matrix.json', 'subsumption.json']:
        path = f'/app/results/{name}'
        assert os.path.isfile(path), f"Missing output file: {path}"


# ---------------------------------------------------------------------------
# 2. metrics.json structure and consistency
# ---------------------------------------------------------------------------

def test_metrics_consistency():
    m = _load('metrics.json')

    for key in ['total_mutants', 'killed', 'survived', 'mutation_score',
                'operators', 'subsuming_mutants_total', 'subsuming_mutation_score']:
        assert key in m, f"Missing key in metrics: {key}"

    equiv = m.get('equivalent', 0)
    timeout = m.get('timeout', 0)
    assert m['killed'] + m['survived'] + equiv + timeout == m['total_mutants'], \
        f"Counts don't sum: {m['killed']}+{m['survived']}+{equiv}+{timeout} != {m['total_mutants']}"

    assert 0 <= m['mutation_score'] <= 1, f"Invalid mutation_score: {m['mutation_score']}"
    assert 0 <= m['subsuming_mutation_score'] <= 1, \
        f"Invalid subsuming_mutation_score: {m['subsuming_mutation_score']}"
    assert m['subsuming_mutants_total'] <= m['total_mutants']
    assert m['subsuming_mutants_total'] > 0, "Must identify at least one subsuming mutant"


# ---------------------------------------------------------------------------
# 3. Operator breakdown
# ---------------------------------------------------------------------------

def test_all_operators_present():
    m = _load('metrics.json')
    for op in ['AOR', 'ROR', 'LCR']:
        assert op in m['operators'], f"Missing operator breakdown: {op}"
        info = m['operators'][op]
        assert 'generated' in info and 'killed' in info
        assert info['generated'] > 0, f"No {op} mutants generated"
        assert info['killed'] <= info['generated']


# ---------------------------------------------------------------------------
# 4. mutants.json structure
# ---------------------------------------------------------------------------

def test_mutants_structure():
    mutants = _load('mutants.json')
    assert isinstance(mutants, list)
    assert len(mutants) > 0

    for entry in mutants:
        assert 'id' in entry
        assert 'operator' in entry
        assert entry['operator'] in ('AOR', 'ROR', 'LCR'), \
            f"Unknown operator: {entry['operator']}"
        assert 'line' in entry
        assert 'status' in entry
        assert entry['status'] in ('killed', 'survived', 'equivalent', 'timeout'), \
            f"Unknown status: {entry['status']}"


# ---------------------------------------------------------------------------
# 5. Minimum mutant count
# ---------------------------------------------------------------------------

def test_minimum_mutant_count():
    m = _load('metrics.json')
    assert m['total_mutants'] >= 40, \
        f"Too few mutants generated ({m['total_mutants']}); expected >= 40"


# ---------------------------------------------------------------------------
# 6. kill_matrix.json structure
# ---------------------------------------------------------------------------

def test_kill_matrix_structure():
    km = _load('kill_matrix.json')

    assert 'mutant_ids' in km
    assert 'test_names' in km
    assert 'matrix' in km

    n_mutants = len(km['mutant_ids'])
    n_tests = len(km['test_names'])

    assert n_mutants > 0
    assert n_tests > 0
    assert len(km['matrix']) == n_mutants, \
        f"Matrix rows ({len(km['matrix'])}) != mutant count ({n_mutants})"

    for i, row in enumerate(km['matrix']):
        assert len(row) == n_tests, \
            f"Row {i} length ({len(row)}) != test count ({n_tests})"
        assert all(v in (0, 1) for v in row), \
            f"Row {i} contains non-binary values"


# ---------------------------------------------------------------------------
# 7. Kill matrix consistent with metrics
# ---------------------------------------------------------------------------

def test_kill_matrix_matches_metrics():
    m = _load('metrics.json')
    km = _load('kill_matrix.json')

    killed_from_matrix = sum(1 for row in km['matrix'] if any(v == 1 for v in row))
    assert killed_from_matrix == m['killed'], \
        f"Kill matrix killed count ({killed_from_matrix}) != metrics killed ({m['killed']})"


# ---------------------------------------------------------------------------
# 8. Subsumption edges verified against kill matrix
# ---------------------------------------------------------------------------

def test_subsumption_edges_verified():
    km = _load('kill_matrix.json')
    sub = _load('subsumption.json')

    id_to_idx = {mid: i for i, mid in enumerate(km['mutant_ids'])}

    for a, b in sub['subsumption_edges']:
        assert a in id_to_idx, f"Mutant {a} in edge but not in kill matrix"
        assert b in id_to_idx, f"Mutant {b} in edge but not in kill matrix"

        ks_a = frozenset(j for j, v in enumerate(km['matrix'][id_to_idx[a]]) if v == 1)
        ks_b = frozenset(j for j, v in enumerate(km['matrix'][id_to_idx[b]]) if v == 1)

        assert len(ks_a) > 0, f"Subsuming mutant {a} has empty kill set"
        assert ks_a.issubset(ks_b), \
            f"Edge ({a},{b}): kill_set({a}) not subset of kill_set({b})"
        assert ks_a != ks_b, \
            f"Edge ({a},{b}): kill sets equal — not strict subsumption"


# ---------------------------------------------------------------------------
# 9. Subsuming set independently verified
# ---------------------------------------------------------------------------

def test_subsuming_set_correct():
    km = _load('kill_matrix.json')
    sub = _load('subsumption.json')

    id_to_idx = {mid: i for i, mid in enumerate(km['mutant_ids'])}

    # Compute kill sets for killable mutants
    killable = {}
    for mid, idx in id_to_idx.items():
        ks = frozenset(j for j, v in enumerate(km['matrix'][idx]) if v == 1)
        if ks:
            killable[mid] = ks

    # Identify mutants that are strictly subsumed
    subsumed = set()
    killable_ids = list(killable.keys())
    for i, a in enumerate(killable_ids):
        for b in killable_ids[i + 1:]:
            ks_a, ks_b = killable[a], killable[b]
            if ks_a < ks_b:
                subsumed.add(b)
            elif ks_b < ks_a:
                subsumed.add(a)

    expected = set(killable.keys()) - subsumed
    actual = set(sub['subsuming_mutant_ids'])

    assert actual == expected, (
        f"Subsuming set mismatch: expected {len(expected)} dominators, "
        f"got {len(actual)}.  Missing: {expected - actual},  Extra: {actual - expected}"
    )


# ---------------------------------------------------------------------------
# 10. Independent verification of a specific mutation
# ---------------------------------------------------------------------------

def test_verify_specific_mutant():
    """Apply % -> * in gcd independently and confirm the tool agrees."""
    source_path = '/app/project/src/mathlib.py'
    test_path = '/app/project/tests/test_mathlib.py'
    assert os.path.isfile(source_path), "Source file missing"

    with open(source_path) as f:
        source = f.read()

    # Apply a known mutation: replace first 'a % b' with 'a * b'
    mutated = source.replace('a % b', 'a * b', 1)
    assert mutated != source, "Mutation not applied (string 'a % b' not found)"

    backup = source_path + '._verify_bak'
    os.rename(source_path, backup)
    try:
        with open(source_path, 'w') as f:
            f.write(mutated)

        try:
            result = subprocess.run(
                [sys.executable, '-B', '-m', 'pytest', test_path,
                 '--tb=no', '-q', '-x'],
                capture_output=True, text=True, timeout=20,
            )
            killed = result.returncode != 0
        except subprocess.TimeoutExpired:
            killed = True
    finally:
        if os.path.exists(source_path):
            os.unlink(source_path)
        os.rename(backup, source_path)

    assert killed, "The % -> * mutation in gcd must be killed by the test suite"

    # Verify the analyzer also reports an AOR mutant in gcd as killed
    mutants = _load('mutants.json')
    gcd_aor = [m for m in mutants
                if m['operator'] == 'AOR'
                and m.get('function', '') == 'gcd']
    assert len(gcd_aor) > 0, "Analyzer should generate AOR mutants for gcd"

    gcd_aor_killed = [m for m in gcd_aor if m['status'] == 'killed']
    assert len(gcd_aor_killed) > 0, \
        "At least one AOR mutant in gcd should be killed"


# ---------------------------------------------------------------------------
# 11. Mutation score is reasonable
# ---------------------------------------------------------------------------

def test_mutation_score_reasonable():
    m = _load('metrics.json')
    assert m['mutation_score'] >= 0.5, \
        f"Mutation score too low ({m['mutation_score']}); test suite should kill most mutants"


# ---------------------------------------------------------------------------
# 12. Subsuming set is smaller than total
# ---------------------------------------------------------------------------

def test_subsuming_fewer_than_total():
    m = _load('metrics.json')
    assert m['subsuming_mutants_total'] < m['total_mutants'], \
        "Subsuming set should be a proper subset of all mutants"
