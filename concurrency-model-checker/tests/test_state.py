"""
Tests for the concurrency model checker.
Verifies deadlock detection, race detection, assertion failure detection,
absence of false positives, positive exploration statistics, re-entrant
locking semantics, and partial-order reduction effectiveness.
"""


import os
import pytest


def parse_output(filepath):
    """Parse model checker output into dict of program_name -> {violations, states, transitions}."""
    results = {}
    current = None
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('PROGRAM: '):
                current = line[len('PROGRAM: '):]
                results[current] = {'violations': [], 'states': 0, 'transitions': 0}
            elif current and line.startswith('STATES: '):
                results[current]['states'] = int(line.split(': ', 1)[1])
            elif current and line.startswith('TRANSITIONS: '):
                results[current]['transitions'] = int(line.split(': ', 1)[1])
            elif current and line.startswith('VIOLATIONS: '):
                pass  # count line; we derive count from violation list
            elif current and line.startswith('VIOLATION: '):
                rest = line[len('VIOLATION: '):]
                vtype, _, vmsg = rest.partition(': ')
                results[current]['violations'].append({'type': vtype, 'message': vmsg})
            elif line == '---':
                current = None
    return results


@pytest.fixture(scope='module')
def results_no_por():
    path = '/app/build/output_no_por.txt'
    assert os.path.exists(path), f"Output file {path} not found"
    return parse_output(path)


@pytest.fixture(scope='module')
def results_por():
    path = '/app/build/output_por.txt'
    assert os.path.exists(path), f"Output file {path} not found"
    return parse_output(path)


def violation_types(results, prog_name):
    """Extract set of violation type strings for a given program."""
    if prog_name not in results:
        return set()
    return set(v['type'] for v in results[prog_name]['violations'])


ALL_PROGRAMS = {
    'DiningPhilosophers', 'SimpleRace', 'MutualExclusion',
    'RaceCounter', 'LockOrderDeadlock', 'HighOrderRace',
    'ReentrantMutex'
}


# ============================================================
# Tests without POR — map to instruction "Required results"
# ============================================================

class TestWithoutPOR:

    def test_all_programs_present(self, results_no_por):
        """All seven programs must appear in output."""
        assert ALL_PROGRAMS.issubset(results_no_por.keys()), \
            f"Missing programs: {ALL_PROGRAMS - results_no_por.keys()}"

    def test_dining_philosophers_deadlock(self, results_no_por):
        """DiningPhilosophers: must contain DEADLOCK."""
        types = violation_types(results_no_por, 'DiningPhilosophers')
        assert 'DEADLOCK' in types, \
            f"Expected DEADLOCK in DiningPhilosophers, got {types}"

    def test_simple_race(self, results_no_por):
        """SimpleRace: must contain DATA_RACE."""
        types = violation_types(results_no_por, 'SimpleRace')
        assert 'DATA_RACE' in types, \
            f"Expected DATA_RACE in SimpleRace, got {types}"

    def test_mutual_exclusion_clean(self, results_no_por):
        """MutualExclusion: exactly zero violations."""
        violations = results_no_por['MutualExclusion']['violations']
        assert len(violations) == 0, \
            f"MutualExclusion should have 0 violations, got {violations}"

    def test_race_counter(self, results_no_por):
        """RaceCounter: must contain DATA_RACE."""
        types = violation_types(results_no_por, 'RaceCounter')
        assert 'DATA_RACE' in types, \
            f"Expected DATA_RACE in RaceCounter, got {types}"

    def test_lock_order_deadlock(self, results_no_por):
        """LockOrderDeadlock: must contain DEADLOCK."""
        types = violation_types(results_no_por, 'LockOrderDeadlock')
        assert 'DEADLOCK' in types, \
            f"Expected DEADLOCK in LockOrderDeadlock, got {types}"

    def test_high_order_race_assertion(self, results_no_por):
        """HighOrderRace: must contain ASSERTION_FAILURE."""
        types = violation_types(results_no_por, 'HighOrderRace')
        assert 'ASSERTION_FAILURE' in types, \
            f"Expected ASSERTION_FAILURE in HighOrderRace, got {types}"

    def test_high_order_race_no_data_race(self, results_no_por):
        """HighOrderRace: must NOT contain DATA_RACE."""
        types = violation_types(results_no_por, 'HighOrderRace')
        assert 'DATA_RACE' not in types, \
            f"HighOrderRace should not report DATA_RACE, got {types}"

    def test_reentrant_mutex_clean(self, results_no_por):
        """ReentrantMutex: exactly zero violations."""
        violations = results_no_por['ReentrantMutex']['violations']
        assert len(violations) == 0, \
            f"ReentrantMutex should have 0 violations, got {violations}"

    def test_states_positive(self, results_no_por):
        """Every program must report positive STATES count."""
        for prog_name, data in results_no_por.items():
            assert data['states'] > 0, f"{prog_name} explored 0 states"

    def test_transitions_positive(self, results_no_por):
        """Every program must report positive TRANSITIONS count."""
        for prog_name, data in results_no_por.items():
            assert data['transitions'] > 0, f"{prog_name} explored 0 transitions"


# ============================================================
# Tests with POR — map to instruction "With --por" section
# ============================================================

class TestWithPOR:

    def test_por_all_programs_present(self, results_por):
        """All seven programs must appear in POR output."""
        assert ALL_PROGRAMS.issubset(results_por.keys()), \
            f"Missing programs in POR output: {ALL_PROGRAMS - results_por.keys()}"

    def test_por_dining_deadlock_preserved(self, results_por):
        types = violation_types(results_por, 'DiningPhilosophers')
        assert 'DEADLOCK' in types, \
            "POR must preserve DEADLOCK in DiningPhilosophers"

    def test_por_simple_race_preserved(self, results_por):
        types = violation_types(results_por, 'SimpleRace')
        assert 'DATA_RACE' in types, \
            "POR must preserve DATA_RACE in SimpleRace"

    def test_por_mutual_exclusion_clean(self, results_por):
        violations = results_por['MutualExclusion']['violations']
        assert len(violations) == 0, \
            "POR must not introduce false positives in MutualExclusion"

    def test_por_race_counter_preserved(self, results_por):
        types = violation_types(results_por, 'RaceCounter')
        assert 'DATA_RACE' in types, \
            "POR must preserve DATA_RACE in RaceCounter"

    def test_por_lock_order_deadlock_preserved(self, results_por):
        types = violation_types(results_por, 'LockOrderDeadlock')
        assert 'DEADLOCK' in types, \
            "POR must preserve DEADLOCK in LockOrderDeadlock"

    def test_por_high_order_race_preserved(self, results_por):
        types = violation_types(results_por, 'HighOrderRace')
        assert 'ASSERTION_FAILURE' in types, \
            "POR must preserve ASSERTION_FAILURE in HighOrderRace"

    def test_por_reentrant_mutex_clean(self, results_por):
        violations = results_por['ReentrantMutex']['violations']
        assert len(violations) == 0, \
            "POR must not introduce false positives in ReentrantMutex"

    def test_por_violation_types_match(self, results_no_por, results_por):
        """POR must not change the set of violation types for any program."""
        for prog_name in results_no_por:
            no_por_types = violation_types(results_no_por, prog_name)
            por_types = violation_types(results_por, prog_name)
            assert no_por_types == por_types, \
                f"POR changed violation types for {prog_name}: " \
                f"without={no_por_types}, with={por_types}"

    def test_por_state_reduction_dining(self, results_no_por, results_por):
        """DiningPhilosophers must have strictly fewer explored states with POR."""
        no_por = results_no_por['DiningPhilosophers']['states']
        por = results_por['DiningPhilosophers']['states']
        assert por < no_por, \
            f"POR should reduce states for DiningPhilosophers: " \
            f"without={no_por}, with={por}"
