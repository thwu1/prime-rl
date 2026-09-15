"""Verification tests for CrossHair plugin, contract fixes, specification engineering,
and defect classification report.

"""

import json
import os
import sys
import ast

sys.path.insert(0, "/app")

import pytest
from orderedset import OrderedSet
from sortedmap import SortedMapping


# ---------------------------------------------------------------------------
# Helper: extract function names and their docstrings from a module file
# ---------------------------------------------------------------------------
def _functions_with_postconditions(filepath):
    """Return dict mapping function name -> bool (has 'post:' in docstring)."""
    with open(filepath) as f:
        tree = ast.parse(f.read())
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            ds = ast.get_docstring(node)
            result[node.name] = ds is not None and "post:" in ds
    return result


class TestPluginStructure:
    """Verify the CrossHair plugin file exists and registers both types."""

    def test_plugin_file_exists(self):
        assert os.path.exists("/app/ch_plugin.py"), "Plugin file /app/ch_plugin.py not found"

    def test_plugin_imports_crosshair(self):
        with open("/app/ch_plugin.py") as f:
            source = f.read()
        assert "crosshair" in source, "Plugin must import crosshair"

    def test_plugin_registers_ordered_set(self):
        with open("/app/ch_plugin.py") as f:
            source = f.read()
        assert "OrderedSet" in source, "Plugin must reference OrderedSet"
        assert "register_type" in source, "Plugin must use register_type"

    def test_plugin_registers_sorted_mapping(self):
        with open("/app/ch_plugin.py") as f:
            source = f.read()
        assert "SortedMapping" in source, "Plugin must reference SortedMapping"

    def test_plugin_is_valid_python_with_two_registrations(self):
        with open("/app/ch_plugin.py") as f:
            source = f.read()
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        call_names = []
        for c in calls:
            if isinstance(c.func, ast.Attribute):
                call_names.append(c.func.attr)
            elif isinstance(c.func, ast.Name):
                call_names.append(c.func.id)
        assert call_names.count("register_type") >= 2, \
            "Plugin must call register_type at least twice (OrderedSet and SortedMapping)"

    def test_plugin_uses_symbolic_factory(self):
        with open("/app/ch_plugin.py") as f:
            source = f.read()
        assert "SymbolicFactory" in source, \
            "Plugin must use SymbolicFactory-based constructor callbacks"


class TestAllFunctionsHavePostconditions:
    """Every function in setops.py and mapops.py must have PEP 316 postconditions."""

    def test_setops_all_functions_have_postconditions(self):
        funcs = _functions_with_postconditions("/app/setops.py")
        assert len(funcs) > 0, "No functions found in setops.py"
        missing = [name for name, has_post in funcs.items() if not has_post]
        assert missing == [], \
            f"setops.py functions missing postconditions: {missing}"

    def test_mapops_all_functions_have_postconditions(self):
        funcs = _functions_with_postconditions("/app/mapops.py")
        assert len(funcs) > 0, "No functions found in mapops.py"
        missing = [name for name, has_post in funcs.items() if not has_post]
        assert missing == [], \
            f"mapops.py functions missing postconditions: {missing}"


class TestSetopsIntersectFix:
    """The intersect contract had size == min(...) which is too strong."""

    def test_disjoint_sets_empty_intersection(self):
        import setops
        s1 = OrderedSet([1, 3, 5])
        s2 = OrderedSet([2, 4, 6])
        result = setops.intersect(s1, s2)
        assert result.size() == 0

    def test_buggy_equality_contract_removed(self):
        with open("/app/setops.py") as f:
            source = f.read()
        assert (
            "__return__.size() == min(s1.size(), s2.size())" not in source
        ), "The overly-strong contract == min(...) must be fixed"

    def test_partial_overlap(self):
        import setops
        s1 = OrderedSet([1, 2, 3, 4])
        s2 = OrderedSet([3, 4, 5, 6])
        result = setops.intersect(s1, s2)
        assert result == OrderedSet([3, 4])

    def test_full_overlap(self):
        import setops
        s1 = OrderedSet([1, 2, 3])
        s2 = OrderedSet([1, 2, 3])
        result = setops.intersect(s1, s2)
        assert result == OrderedSet([1, 2, 3])

    def test_empty_inputs(self):
        import setops
        result = setops.intersect(OrderedSet(), OrderedSet())
        assert result.size() == 0
        result = setops.intersect(OrderedSet([1]), OrderedSet())
        assert result.size() == 0


class TestSetopsSymmetricDifferenceFix:
    """The symmetric_difference had a pointer advancement bug."""

    def test_excludes_common_elements(self):
        import setops
        s1 = OrderedSet([1, 2, 3])
        s2 = OrderedSet([2, 4])
        result = setops.symmetric_difference(s1, s2)
        assert not result.contains(2), "Common element 2 must not be in symmetric difference"
        assert result == OrderedSet([1, 3, 4])

    def test_identical_sets_empty(self):
        import setops
        s1 = OrderedSet([1, 2, 3])
        s2 = OrderedSet([1, 2, 3])
        result = setops.symmetric_difference(s1, s2)
        assert result.size() == 0, "Symmetric difference of identical sets must be empty"

    def test_no_common_elements(self):
        import setops
        s1 = OrderedSet([1, 3])
        s2 = OrderedSet([2, 4])
        result = setops.symmetric_difference(s1, s2)
        assert result == OrderedSet([1, 2, 3, 4])

    def test_multiple_common_elements(self):
        import setops
        s1 = OrderedSet([1, 2, 3, 4, 5])
        s2 = OrderedSet([2, 4, 6, 8])
        result = setops.symmetric_difference(s1, s2)
        assert result == OrderedSet([1, 3, 5, 6, 8])

    def test_postcondition_holds(self):
        import setops
        s1 = OrderedSet([10, 20, 30, 40])
        s2 = OrderedSet([20, 30, 50, 60])
        result = setops.symmetric_difference(s1, s2)
        for x in result.to_list():
            assert not (s1.contains(x) and s2.contains(x)), (
                f"Element {x} is in both s1 and s2 but appears in symmetric difference"
            )


class TestSetopsRangeCountFix:
    """The range_count had an off-by-one."""

    def test_basic_range(self):
        import setops
        s = OrderedSet([1, 3, 5, 7, 9])
        assert setops.range_count(s, 3, 7) == 3

    def test_full_range(self):
        import setops
        s = OrderedSet([1, 3, 5, 7, 9])
        assert setops.range_count(s, 1, 9) == 5

    def test_empty_range_no_elements(self):
        import setops
        s = OrderedSet([1, 3, 5, 7, 9])
        assert setops.range_count(s, 10, 20) == 0

    def test_empty_set(self):
        import setops
        s = OrderedSet()
        assert setops.range_count(s, 0, 10) == 0

    def test_single_element_in_range(self):
        import setops
        s = OrderedSet([5])
        assert setops.range_count(s, 5, 5) == 1

    def test_brute_force_match(self):
        import setops
        s = OrderedSet([2, 5, 8, 11, 14, 17, 20])
        for lo, hi in [(1, 10), (5, 14), (0, 25), (8, 8), (9, 10), (21, 30)]:
            expected = len([x for x in s.to_list() if lo <= x <= hi])
            actual = setops.range_count(s, lo, hi)
            assert actual == expected, f"range_count({s}, {lo}, {hi}): got {actual}, expected {expected}"


class TestMapopsMergeMappingsFix:
    """merge_mappings must sum values for duplicate keys, not replace."""

    def test_sums_duplicate_keys(self):
        import mapops
        m1 = SortedMapping([(1, 10), (2, 20)])
        m2 = SortedMapping([(2, 30), (3, 40)])
        result = mapops.merge_mappings(m1, m2)
        assert result.get(1) == 10
        assert result.get(2) == 50, "Duplicate key 2: values 20+30 should be 50"
        assert result.get(3) == 40

    def test_no_overlap(self):
        import mapops
        m1 = SortedMapping([(1, 10)])
        m2 = SortedMapping([(2, 20)])
        result = mapops.merge_mappings(m1, m2)
        assert result.get(1) == 10
        assert result.get(2) == 20
        assert result.size() == 2

    def test_full_overlap(self):
        import mapops
        m1 = SortedMapping([(1, 5), (2, 10)])
        m2 = SortedMapping([(1, 3), (2, 7)])
        result = mapops.merge_mappings(m1, m2)
        assert result.get(1) == 8
        assert result.get(2) == 17

    def test_empty_mappings(self):
        import mapops
        result = mapops.merge_mappings(SortedMapping(), SortedMapping())
        assert result.size() == 0

    def test_one_empty(self):
        import mapops
        m = SortedMapping([(1, 10)])
        result = mapops.merge_mappings(m, SortedMapping())
        assert result.get(1) == 10
        assert result.size() == 1


class TestMapopsRangeLookupFix:
    """range_lookup had a weak spec (strict < instead of <=) hiding a bisect bug."""

    def test_includes_upper_boundary(self):
        import mapops
        m = SortedMapping([(5, 50), (10, 100)])
        result = mapops.range_lookup(m, 5, 10)
        assert result.contains_key(10), "Upper boundary key 10 must be included"
        assert result.get(10) == 100

    def test_includes_lower_boundary(self):
        import mapops
        m = SortedMapping([(5, 50), (10, 100)])
        result = mapops.range_lookup(m, 5, 10)
        assert result.contains_key(5), "Lower boundary key 5 must be included"

    def test_single_key_equals_both_bounds(self):
        import mapops
        m = SortedMapping([(5, 50)])
        result = mapops.range_lookup(m, 5, 5)
        assert result.contains_key(5)
        assert result.size() == 1

    def test_no_keys_in_range(self):
        import mapops
        m = SortedMapping([(1, 10), (20, 200)])
        result = mapops.range_lookup(m, 5, 15)
        assert result.size() == 0

    def test_all_keys_in_range(self):
        import mapops
        m = SortedMapping([(3, 30), (5, 50), (7, 70)])
        result = mapops.range_lookup(m, 1, 10)
        assert result.size() == 3

    def test_weak_completeness_spec_removed(self):
        with open("/app/mapops.py") as f:
            source = f.read()
        assert "lo < k < hi" not in source, \
            "The weak completeness postcondition (lo < k < hi) must use inclusive bounds (lo <= k <= hi)"


class TestMapopsSumValuesInRangeFix:
    """sum_values_in_range must sum values, not keys."""

    def test_sums_values_not_keys(self):
        import mapops
        m = SortedMapping([(1, 100), (2, 200), (3, 300)])
        assert mapops.sum_values_in_range(m, 1, 3) == 600

    def test_single_key(self):
        import mapops
        m = SortedMapping([(5, 42)])
        assert mapops.sum_values_in_range(m, 5, 5) == 42

    def test_partial_range(self):
        import mapops
        m = SortedMapping([(1, 10), (5, 50), (10, 100)])
        assert mapops.sum_values_in_range(m, 3, 7) == 50

    def test_no_keys_in_range(self):
        import mapops
        m = SortedMapping([(1, 10)])
        assert mapops.sum_values_in_range(m, 5, 10) == 0

    def test_empty_mapping(self):
        import mapops
        assert mapops.sum_values_in_range(SortedMapping(), 0, 100) == 0


class TestMapopsContractWriting:
    """Functions keys_with_value_in and key_of_max_value must have postconditions."""

    def test_keys_with_value_in_has_postconditions(self):
        with open("/app/mapops.py") as f:
            source = f.read()
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "keys_with_value_in":
                docstring = ast.get_docstring(node)
                assert docstring is not None and "post:" in docstring, \
                    "keys_with_value_in must have PEP 316 postconditions"
                found = True
                break
        assert found, "Function keys_with_value_in not found in mapops.py"

    def test_keys_with_value_in_basic(self):
        import mapops
        m = SortedMapping([(1, 10), (2, 20), (3, 10), (4, 30)])
        values = OrderedSet([10, 30])
        result = mapops.keys_with_value_in(m, values)
        assert result == OrderedSet([1, 3, 4])

    def test_keys_with_value_in_none_match(self):
        import mapops
        m = SortedMapping([(1, 10), (2, 20)])
        values = OrderedSet([30])
        result = mapops.keys_with_value_in(m, values)
        assert result.size() == 0

    def test_keys_with_value_in_all_match(self):
        import mapops
        m = SortedMapping([(1, 5), (2, 5)])
        values = OrderedSet([5])
        result = mapops.keys_with_value_in(m, values)
        assert result == OrderedSet([1, 2])

    def test_key_of_max_value_has_postconditions(self):
        with open("/app/mapops.py") as f:
            source = f.read()
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "key_of_max_value":
                docstring = ast.get_docstring(node)
                assert docstring is not None and "post:" in docstring, \
                    "key_of_max_value must have PEP 316 postconditions"
                found = True
                break
        assert found, "Function key_of_max_value not found in mapops.py"

    def test_key_of_max_value_basic(self):
        import mapops
        m = SortedMapping([(1, 30), (2, 10), (3, 20)])
        assert mapops.key_of_max_value(m) == 1

    def test_key_of_max_value_tie_smallest_key(self):
        import mapops
        m = SortedMapping([(1, 10), (2, 10), (3, 10)])
        assert mapops.key_of_max_value(m) == 1

    def test_key_of_max_value_last_key(self):
        import mapops
        m = SortedMapping([(1, 10), (2, 20), (3, 30)])
        assert mapops.key_of_max_value(m) == 3

    def test_key_of_max_value_single(self):
        import mapops
        m = SortedMapping([(5, 100)])
        assert mapops.key_of_max_value(m) == 5

    def test_key_of_max_value_negative_values(self):
        import mapops
        m = SortedMapping([(1, -10), (2, -5), (3, -20)])
        assert mapops.key_of_max_value(m) == 2


class TestSetopsV2Fix:
    """setops_v2.intersect had a bounds-check bug."""

    def test_no_crash_larger_element(self):
        import setops_v2
        s1 = OrderedSet([1, 100])
        s2 = OrderedSet([1, 50])
        result = setops_v2.intersect(s1, s2)
        assert result == OrderedSet([1])

    def test_no_crash_all_larger(self):
        import setops_v2
        s1 = OrderedSet([100, 200])
        s2 = OrderedSet([1, 50])
        result = setops_v2.intersect(s1, s2)
        assert result.size() == 0

    def test_matches_reference(self):
        import setops
        import setops_v2
        cases = [
            (OrderedSet([1, 2, 3]), OrderedSet([2, 3, 4])),
            (OrderedSet([1]), OrderedSet([1])),
            (OrderedSet([1]), OrderedSet([2])),
            (OrderedSet(), OrderedSet([1, 2, 3])),
            (OrderedSet([1, 2, 3]), OrderedSet()),
            (OrderedSet(), OrderedSet()),
            (OrderedSet([1, 3, 5, 7, 9]), OrderedSet([2, 4, 6, 8, 10])),
            (OrderedSet([1, 2, 3, 4, 5]), OrderedSet([1, 2, 3, 4, 5])),
        ]
        for s1, s2 in cases:
            r1 = setops.intersect(s1, s2)
            r2 = setops_v2.intersect(s1, s2)
            assert r1 == r2, f"Mismatch for {s1}, {s2}: setops={r1} vs setops_v2={r2}"


class TestMapopsV2RangeLookupFix:
    """mapops_v2.range_lookup must include upper boundary and match reference."""

    def test_includes_upper_boundary(self):
        import mapops_v2
        m = SortedMapping([(5, 50), (10, 100)])
        result = mapops_v2.range_lookup(m, 5, 10)
        assert result.contains_key(10), "V2 must include upper boundary key 10"

    def test_single_key_at_boundary(self):
        import mapops_v2
        m = SortedMapping([(7, 70)])
        result = mapops_v2.range_lookup(m, 7, 7)
        assert result.contains_key(7)
        assert result.size() == 1

    def test_matches_reference(self):
        import mapops
        import mapops_v2
        cases = [
            (SortedMapping([(1, 10), (5, 50), (10, 100)]), 1, 10),
            (SortedMapping([(1, 10), (5, 50), (10, 100)]), 5, 5),
            (SortedMapping([(1, 10), (5, 50), (10, 100)]), 3, 7),
            (SortedMapping([(1, 10)]), 1, 1),
            (SortedMapping(), 0, 10),
            (SortedMapping([(1, 10), (2, 20), (3, 30)]), 1, 3),
        ]
        for m, lo, hi in cases:
            r1 = mapops.range_lookup(m, lo, hi)
            r2 = mapops_v2.range_lookup(m, lo, hi)
            assert r1 == r2, f"Mismatch for {m}, {lo}, {hi}: ref={r1} vs v2={r2}"


class TestCorrectFunctionsUnchanged:
    """Verify that functions that were already correct remain correct."""

    def test_union(self):
        import setops
        result = setops.union(OrderedSet([1, 2, 3]), OrderedSet([2, 3, 4]))
        assert result == OrderedSet([1, 2, 3, 4])

    def test_union_disjoint(self):
        import setops
        result = setops.union(OrderedSet([1, 3, 5]), OrderedSet([2, 4, 6]))
        assert result == OrderedSet([1, 2, 3, 4, 5, 6])

    def test_difference(self):
        import setops
        result = setops.difference(OrderedSet([1, 2, 3, 4]), OrderedSet([2, 4]))
        assert result == OrderedSet([1, 3])

    def test_difference_disjoint(self):
        import setops
        result = setops.difference(OrderedSet([1, 2, 3]), OrderedSet([4, 5, 6]))
        assert result == OrderedSet([1, 2, 3])

    def test_kth_element(self):
        import setops
        s = OrderedSet([10, 20, 30, 40, 50])
        assert setops.kth_element(s, 0) == 10
        assert setops.kth_element(s, 2) == 30
        assert setops.kth_element(s, 4) == 50

    def test_invert_mapping(self):
        import mapops
        m = SortedMapping([(1, 10), (2, 20), (3, 30)])
        result = mapops.invert_mapping(m)
        assert result.get(10) == 1
        assert result.get(20) == 2
        assert result.get(30) == 3
        assert result.size() == 3

    def test_invert_mapping_single(self):
        import mapops
        m = SortedMapping([(5, 50)])
        result = mapops.invert_mapping(m)
        assert result.get(50) == 5
        assert result.size() == 1


class TestDefectReport:
    """Verify the defect classification report is accurate and complete."""

    def test_report_file_exists(self):
        assert os.path.exists("/app/defect_report.json"), \
            "Defect classification report /app/defect_report.json not found"

    def test_report_is_valid_json_with_defects_array(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        assert "defects" in data, "Report must have a 'defects' key"
        assert isinstance(data["defects"], list), "'defects' must be an array"

    def test_report_entries_have_required_fields(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        valid_categories = {
            "implementation_bug", "contract_error",
            "weak_specification", "missing_specification",
        }
        for i, entry in enumerate(data["defects"]):
            assert "module" in entry, f"Entry {i} missing 'module'"
            assert "function" in entry, f"Entry {i} missing 'function'"
            assert "category" in entry, f"Entry {i} missing 'category'"
            assert entry["category"] in valid_categories, \
                f"Entry {i} has invalid category '{entry['category']}'"

    def test_correct_functions_not_reported_as_defective(self):
        """Functions that are already correct must NOT appear in the report."""
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        correct_funcs = {
            ("setops", "union"),
            ("setops", "difference"),
            ("setops", "kth_element"),
            ("mapops", "invert_mapping"),
        }
        reported = {(d["module"], d["function"]) for d in data["defects"]}
        false_positives = reported & correct_funcs
        assert false_positives == set(), \
            f"Correct functions incorrectly flagged as defective: {false_positives}"

    def test_all_defective_functions_reported(self):
        """Every actually defective function must appear in the report."""
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        reported = {(d["module"], d["function"]) for d in data["defects"]}
        expected_defective = {
            ("setops", "intersect"),
            ("setops", "symmetric_difference"),
            ("setops", "range_count"),
            ("mapops", "merge_mappings"),
            ("mapops", "range_lookup"),
            ("mapops", "sum_values_in_range"),
            ("mapops", "keys_with_value_in"),
            ("mapops", "key_of_max_value"),
            ("setops_v2", "intersect"),
            ("mapops_v2", "range_lookup"),
        }
        missing = expected_defective - reported
        assert missing == set(), \
            f"Defective functions not reported: {missing}"

    def test_category_setops_intersect(self):
        """intersect has a logically incorrect contract (== min is too strong)."""
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "setops" and d["function"] == "intersect"}
        assert "contract_error" in cats, \
            "setops.intersect should be classified as contract_error"

    def test_category_setops_symmetric_difference(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "setops" and d["function"] == "symmetric_difference"}
        assert "implementation_bug" in cats, \
            "setops.symmetric_difference should be classified as implementation_bug"

    def test_category_setops_range_count(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "setops" and d["function"] == "range_count"}
        assert "implementation_bug" in cats, \
            "setops.range_count should be classified as implementation_bug"

    def test_category_mapops_merge_mappings(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "mapops" and d["function"] == "merge_mappings"}
        assert "implementation_bug" in cats, \
            "mapops.merge_mappings should be classified as implementation_bug"

    def test_category_mapops_range_lookup(self):
        """range_lookup has a weak spec masking an impl bug; accept either classification."""
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "mapops" and d["function"] == "range_lookup"}
        assert cats & {"weak_specification", "contract_error"}, \
            "mapops.range_lookup must be classified as weak_specification or contract_error"

    def test_category_mapops_sum_values_in_range(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "mapops" and d["function"] == "sum_values_in_range"}
        assert "implementation_bug" in cats, \
            "mapops.sum_values_in_range should be classified as implementation_bug"

    def test_category_mapops_keys_with_value_in(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "mapops" and d["function"] == "keys_with_value_in"}
        assert "missing_specification" in cats, \
            "mapops.keys_with_value_in should be classified as missing_specification"

    def test_category_mapops_key_of_max_value(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "mapops" and d["function"] == "key_of_max_value"}
        assert "missing_specification" in cats, \
            "mapops.key_of_max_value should be classified as missing_specification"

    def test_category_setops_v2_intersect(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "setops_v2" and d["function"] == "intersect"}
        assert "implementation_bug" in cats, \
            "setops_v2.intersect should be classified as implementation_bug"

    def test_category_mapops_v2_range_lookup(self):
        with open("/app/defect_report.json") as f:
            data = json.load(f)
        cats = {d["category"] for d in data["defects"]
                if d["module"] == "mapops_v2" and d["function"] == "range_lookup"}
        assert "implementation_bug" in cats, \
            "mapops_v2.range_lookup should be classified as implementation_bug"
