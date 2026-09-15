
"""Tests for Rubik's Cube simulator forensic audit."""

import json
import os
import subprocess
import pytest
from math import gcd
from functools import reduce

RESULTS_PATH = "/app/results.json"
GAP_SCRIPT_PATH = "/app/gap_verify.g"

# Ground truth computed from a verified cube simulator.
# Verification invariants: all basic moves have order 4, R U has order 63,
# sexy move (R U R' U') has order 6, superflip has order 2.

EXPECTED_FACELET_STRINGS = [
    "BRBRUUFFBUBULRDFRULDLDFBRFLDLDFDFBLFLBUDLLRUFRUDBBRRUD",
    "RLURURDFDFBLBRBBBUBURDFDUDRBFDDDUFLBFFLULRLLRFFULBRLUD",
    "LDLLUFURRFUBLRUBLRBBUFFBLBLUUURDFRRDFDRBLRFUFDFDLBDBDD",
    "DRLBULFLURDULRBDRBDUFUFFFFBLDRRDDDLUBULFLRRBUBFLDBURBF",
    "LBLRULDDLBUFURRUBBFLUDFRUFRRLBDDLLDRFFRFLRBBFUUDBBUDFD",
    "RBDUUDBLFDRBLRDDRLRULFFFFDRLFFBDULUBFFURLRULURDULBBDBB",
    "RLDBUDFFBDRFRRFBBULDRUFBRFLDRULDUDLRFDULLRLDFLFUUBBBUB",
    "FDBRURBUFUFDURBRBRDBRBFFBDBURUFDRFDFLURULDLLLLFULBLDLD",
    "FDLRULFFDRBDBRUFLLLLBDFUBLRRUURDDBRURFUDLBDBUFFDFBRBUL",
    "BURRUUBFFLRBRRDFBUUUULFBDDLFRDDDLLDFDFLLLUBLRUBRFBFRBD",
    "LLDFURBLURBBRRBBDBUUFDFULDDFBLFDRFUUURLLLLDDDRFFUBBRFR",
    "DLRUUULFUFBUFRFDDUFULDFDFBLRLBDDBRUBRLDBLLBRDFFBRBRLRU",
    "FUURUFUBDRRBDRBULRFDBRFLBURLLBFDFUFFDBLRLUFUDLBLLBDDDR",
    "LFDBUFBDBRULRRUUBDDLURFUUUBRBLBDDDFFULRFLDRRFBDFLBRLLF",
    "BBFFUBBDFRDRURDDUDURDLFLBRBRBRFDFFUFLDLRLFURUULDLBULBL",
]

EXPECTED_ORDERS = [24, 12, 90, 30, 42, 84, 72, 126, 48, 84, 60, 72, 77, 168, 360]

EXPECTED_CYCLE_TYPES = [
    [2, 2, 2, 3, 3, 4, 6, 6, 8, 12],
    [1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4, 4, 6, 6],
    [1, 1, 1, 2, 2, 3, 10, 10, 18],
    [1, 1, 1, 1, 1, 1, 1, 6, 10, 10, 15],
    [1, 1, 2, 3, 3, 3, 3, 3, 3, 3, 3, 6, 7, 7],
    [2, 2, 2, 2, 2, 3, 4, 4, 6, 21],
    [1, 1, 1, 1, 1, 2, 2, 2, 3, 4, 4, 8, 18],
    [3, 6, 18, 21],
    [2, 2, 2, 3, 3, 8, 12, 16],
    [1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 3, 6, 12, 14],
    [1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 3, 6, 20],
    [1, 1, 2, 6, 6, 6, 8, 18],
    [1, 1, 1, 1, 1, 7, 7, 7, 11, 11],
    [2, 2, 6, 8, 8, 8, 14],
    [2, 4, 8, 9, 10, 15],
]

EXPECTED_FIXED = [0, 2, 3, 7, 2, 0, 5, 0, 0, 8, 5, 2, 5, 0, 0]

EXPECTED_PARITIES = [
    "even", "even", "odd", "odd", "even", "even", "odd", "even",
    "even", "even", "odd", "even", "even", "odd", "even",
]

EXPECTED_MAX_ORDER_INDEX = 14
EXPECTED_MAX_ORDER = 360
EXPECTED_TOTAL_FIXED = 39
EXPECTED_SHARED_PAIRS = []
EXPECTED_COMPOSITE_ORDER = 8
EXPECTED_BUGGY_MOVE = "R"


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_results_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_has_scrambles_array(self, results):
        assert "scrambles" in results
        assert isinstance(results["scrambles"], list)
        assert len(results["scrambles"]) == 15

    def test_has_global_fields(self, results):
        for field in ["max_order_index", "max_order", "total_fixed",
                       "shared_cycle_type_pairs", "composite_order"]:
            assert field in results, f"Missing global field: {field}"

    def test_has_diagnostics(self, results):
        assert "diagnostics" in results, "Missing diagnostics section"
        assert "buggy_move" in results["diagnostics"], "Missing buggy_move in diagnostics"

    def test_has_gap_verified_orders(self, results):
        assert "gap_verified_orders" in results, "Missing gap_verified_orders"
        assert isinstance(results["gap_verified_orders"], list)
        assert len(results["gap_verified_orders"]) == 15

    def test_scramble_entry_fields(self, results):
        for i, entry in enumerate(results["scrambles"]):
            for field in ["facelet_string", "permutation_order", "cycle_type",
                          "num_fixed_facelets", "parity"]:
                assert field in entry, f"Scramble {i} missing field: {field}"


class TestFaceletStrings:
    def test_facelet_string_length(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert len(entry["facelet_string"]) == 54, \
                f"Scramble {i}: facelet string length {len(entry['facelet_string'])}, expected 54"

    def test_facelet_string_colors(self, results):
        for i, entry in enumerate(results["scrambles"]):
            s = entry["facelet_string"]
            for c in "URFDLB":
                count = s.count(c)
                assert count == 9, \
                    f"Scramble {i}: color {c} appears {count} times, expected 9"

    def test_facelet_strings_correct(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert entry["facelet_string"] == EXPECTED_FACELET_STRINGS[i], \
                f"Scramble {i}: facelet string mismatch"


class TestPermutationOrders:
    def test_orders_correct(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert entry["permutation_order"] == EXPECTED_ORDERS[i], \
                f"Scramble {i}: order {entry['permutation_order']}, expected {EXPECTED_ORDERS[i]}"

    def test_orders_positive(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert entry["permutation_order"] > 0, \
                f"Scramble {i}: order must be positive"


class TestCycleTypes:
    def test_cycle_types_correct(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert entry["cycle_type"] == EXPECTED_CYCLE_TYPES[i], \
                f"Scramble {i}: cycle type mismatch"

    def test_cycle_type_sum_is_48(self, results):
        """All cycle lengths must sum to 48 (the number of non-center facelets)."""
        for i, entry in enumerate(results["scrambles"]):
            total = sum(entry["cycle_type"])
            assert total == 48, \
                f"Scramble {i}: cycle type sum {total}, expected 48"

    def test_cycle_type_sorted(self, results):
        for i, entry in enumerate(results["scrambles"]):
            ct = entry["cycle_type"]
            assert ct == sorted(ct), \
                f"Scramble {i}: cycle type not sorted"

    def test_order_equals_lcm_of_cycles(self, results):
        """Permutation order must equal LCM of all cycle lengths."""
        for i, entry in enumerate(results["scrambles"]):
            ct = entry["cycle_type"]
            lcm_val = reduce(lambda a, b: a * b // gcd(a, b), ct) if ct else 1
            assert entry["permutation_order"] == lcm_val, \
                f"Scramble {i}: order {entry['permutation_order']} != LCM {lcm_val}"


class TestFixedFacelets:
    def test_fixed_facelets_correct(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert entry["num_fixed_facelets"] == EXPECTED_FIXED[i], \
                f"Scramble {i}: fixed {entry['num_fixed_facelets']}, expected {EXPECTED_FIXED[i]}"

    def test_fixed_equals_unit_cycles(self, results):
        """Number of fixed facelets must equal number of length-1 cycles."""
        for i, entry in enumerate(results["scrambles"]):
            unit_cycles = entry["cycle_type"].count(1)
            assert entry["num_fixed_facelets"] == unit_cycles, \
                f"Scramble {i}: fixed {entry['num_fixed_facelets']} != unit cycles {unit_cycles}"


class TestParity:
    def test_parities_correct(self, results):
        for i, entry in enumerate(results["scrambles"]):
            assert entry["parity"] == EXPECTED_PARITIES[i], \
                f"Scramble {i}: parity '{entry['parity']}', expected '{EXPECTED_PARITIES[i]}'"

    def test_parity_consistent_with_cycles(self, results):
        """Parity = sum of (cycle_length - 1) mod 2."""
        for i, entry in enumerate(results["scrambles"]):
            ct = entry["cycle_type"]
            computed = sum(c - 1 for c in ct) % 2
            expected_parity = "even" if computed == 0 else "odd"
            assert entry["parity"] == expected_parity, \
                f"Scramble {i}: parity inconsistent with cycle type"


class TestDiagnostics:
    def test_buggy_move_identified(self, results):
        assert results["diagnostics"]["buggy_move"] == EXPECTED_BUGGY_MOVE, \
            f"buggy_move: '{results['diagnostics']['buggy_move']}', expected '{EXPECTED_BUGGY_MOVE}'"


class TestGAPVerification:
    def test_gap_script_exists(self):
        assert os.path.exists(GAP_SCRIPT_PATH), \
            f"GAP verification script not found at {GAP_SCRIPT_PATH}"

    def test_gap_script_runs(self):
        """The GAP script must execute without errors."""
        result = subprocess.run(
            ['gap', '-q', '-b', GAP_SCRIPT_PATH],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"GAP script failed with exit code {result.returncode}.\nstderr: {result.stderr[:500]}"

    def test_gap_script_produces_correct_orders(self):
        """The GAP script must output the correct permutation orders."""
        result = subprocess.run(
            ['gap', '-q', '-b', GAP_SCRIPT_PATH],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout
        # Check that each expected order appears in the output
        for i, expected_order in enumerate(EXPECTED_ORDERS):
            # Look for patterns like "order_N = K" or "Order: K" or just the number
            assert str(expected_order) in output, \
                f"GAP output missing order {expected_order} for scramble {i}"

    def test_gap_verified_orders_match(self, results):
        """gap_verified_orders must match expected permutation orders."""
        for i, order in enumerate(results["gap_verified_orders"]):
            assert order == EXPECTED_ORDERS[i], \
                f"gap_verified_orders[{i}]: {order}, expected {EXPECTED_ORDERS[i]}"


class TestGlobalResults:
    def test_max_order_index(self, results):
        assert results["max_order_index"] == EXPECTED_MAX_ORDER_INDEX, \
            f"max_order_index: {results['max_order_index']}, expected {EXPECTED_MAX_ORDER_INDEX}"

    def test_max_order_value(self, results):
        assert results["max_order"] == EXPECTED_MAX_ORDER, \
            f"max_order: {results['max_order']}, expected {EXPECTED_MAX_ORDER}"

    def test_max_order_consistent(self, results):
        """max_order must equal the order at max_order_index."""
        idx = results["max_order_index"]
        assert results["scrambles"][idx]["permutation_order"] == results["max_order"]

    def test_total_fixed(self, results):
        assert results["total_fixed"] == EXPECTED_TOTAL_FIXED, \
            f"total_fixed: {results['total_fixed']}, expected {EXPECTED_TOTAL_FIXED}"

    def test_total_fixed_consistent(self, results):
        """total_fixed must be the sum of all num_fixed_facelets."""
        computed = sum(e["num_fixed_facelets"] for e in results["scrambles"])
        assert results["total_fixed"] == computed

    def test_shared_cycle_type_pairs(self, results):
        assert results["shared_cycle_type_pairs"] == EXPECTED_SHARED_PAIRS, \
            f"shared_cycle_type_pairs mismatch"

    def test_composite_order(self, results):
        assert results["composite_order"] == EXPECTED_COMPOSITE_ORDER, \
            f"composite_order: {results['composite_order']}, expected {EXPECTED_COMPOSITE_ORDER}"
