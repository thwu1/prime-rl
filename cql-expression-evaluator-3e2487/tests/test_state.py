"""Tests for the CQL expression test runner.

Verifies CLI behavior, JSON output schema, ANTLR4 parser generation,
invalid test exclusion, and overall pass rate against HL7 CQL fixtures.

"""

import subprocess
import json
import os
import sys
import glob
import pytest


def run_runner(*args, timeout=120):
    result = subprocess.run(
        ['python3', '/app/cql_runner.py'] + list(args),
        capture_output=True, text=True, timeout=timeout, cwd='/app'
    )
    return result


# ---------------------------------------------------------------------------
# Generated ANTLR4 parser verification
# ---------------------------------------------------------------------------

class TestGeneratedParser:
    def test_lexer_file_exists(self):
        patterns = ['/app/generated/*Lexer.py', '/app/generated/*_lexer.py',
                    '/app/generated/*lexer.py']
        files = []
        for p in patterns:
            files.extend(glob.glob(p))
        assert len(files) > 0, "No generated lexer .py file found in /app/generated/"

    def test_parser_file_exists(self):
        patterns = ['/app/generated/*Parser.py', '/app/generated/*_parser.py',
                    '/app/generated/*parser.py']
        files = []
        for p in patterns:
            files.extend(glob.glob(p))
        assert len(files) > 0, "No generated parser .py file found in /app/generated/"

    def test_parser_is_antlr4_generated(self):
        """Generated parser must contain antlr4 imports."""
        parser_files = (glob.glob('/app/generated/*Parser.py')
                        + glob.glob('/app/generated/*_parser.py')
                        + glob.glob('/app/generated/*parser.py'))
        assert len(parser_files) > 0
        content = open(parser_files[0]).read()
        assert 'antlr4' in content, (
            "Parser file does not appear to be ANTLR4-generated "
            "(no 'antlr4' found in source)")

    def test_parser_has_serialized_atn(self):
        """ANTLR4-generated parsers contain a serializedATN field."""
        parser_files = (glob.glob('/app/generated/*Parser.py')
                        + glob.glob('/app/generated/*_parser.py')
                        + glob.glob('/app/generated/*parser.py'))
        assert len(parser_files) > 0
        content = open(parser_files[0]).read()
        assert 'serializedATN' in content, (
            "Parser lacks serializedATN — not genuine ANTLR4 output")

    def test_antlr4_runtime_installed(self):
        """The antlr4-python3-runtime package must be installed."""
        result = subprocess.run(
            ['python3', '-c', 'import antlr4'],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, (
            f"antlr4 runtime not installed: {result.stderr}")


# ---------------------------------------------------------------------------
# CLI existence
# ---------------------------------------------------------------------------

class TestCLIExists:
    def test_runner_file_exists(self):
        assert os.path.isfile('/app/cql_runner.py'), "/app/cql_runner.py not found"


# ---------------------------------------------------------------------------
# Single-file mode: JSON schema
# ---------------------------------------------------------------------------

class TestSingleFileMode:
    FIXTURE = '/app/fixtures/CqlLogicalOperatorsTest.xml'

    def test_returns_valid_json(self):
        result = run_runner(self.FIXTURE)
        assert result.returncode == 0, f"Runner failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_schema_file_field(self):
        result = run_runner(self.FIXTURE)
        data = json.loads(result.stdout)
        assert 'file' in data
        assert data['file'] == 'CqlLogicalOperatorsTest.xml'

    def test_schema_tests_array(self):
        result = run_runner(self.FIXTURE)
        data = json.loads(result.stdout)
        assert 'tests' in data
        assert isinstance(data['tests'], list)
        assert len(data['tests']) > 0

    def test_schema_test_item_keys(self):
        result = run_runner(self.FIXTURE)
        data = json.loads(result.stdout)
        t = data['tests'][0]
        for key in ('name', 'group', 'expression', 'expected', 'actual', 'pass'):
            assert key in t, f"Missing key '{key}' in test item"
        assert isinstance(t['pass'], bool)

    def test_schema_summary(self):
        result = run_runner(self.FIXTURE)
        data = json.loads(result.stdout)
        assert 'summary' in data
        s = data['summary']
        for key in ('total', 'passed', 'failed'):
            assert key in s, f"Missing key '{key}' in summary"
        assert s['total'] == s['passed'] + s['failed'], (
            f"total ({s['total']}) != passed ({s['passed']}) + failed ({s['failed']})")


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

class TestBatchMode:
    def test_batch_returns_json_array(self):
        result = run_runner('--batch', timeout=180)
        assert result.returncode == 0, f"Batch mode failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_batch_processes_all_fixtures(self):
        result = run_runner('--batch', timeout=180)
        data = json.loads(result.stdout)
        fixture_count = len(glob.glob('/app/fixtures/*.xml'))
        assert len(data) == fixture_count, (
            f"Expected {fixture_count} entries, got {len(data)}")

    def test_batch_each_entry_has_required_keys(self):
        result = run_runner('--batch', timeout=180)
        data = json.loads(result.stdout)
        for entry in data:
            assert 'file' in entry
            assert 'tests' in entry
            assert 'summary' in entry


# ---------------------------------------------------------------------------
# Invalid test exclusion
# ---------------------------------------------------------------------------

class TestInvalidExclusion:
    def test_invalid_true_excluded_from_values(self):
        """ValueLiteralsAndSelectors.xml has tests with invalid='true'
        (e.g. Integer2Pow31). They must not appear in output."""
        result = run_runner('/app/fixtures/ValueLiteralsAndSelectors.xml')
        data = json.loads(result.stdout)
        names = {t['name'] for t in data['tests']}
        assert 'Integer2Pow31' not in names, (
            "Test with invalid='true' should be excluded")
        assert 'IntegerPos2Pow31' not in names

    def test_invalid_semantic_excluded_from_types(self):
        """CqlTypesTest.xml has tests with invalid='semantic'. They
        should also be excluded."""
        result = run_runner('/app/fixtures/CqlTypesTest.xml')
        data = json.loads(result.stdout)
        names = {t['name'] for t in data['tests']}
        assert 'TimeUpperBoundHours' not in names, (
            "Test with invalid='semantic' should be excluded")


# ---------------------------------------------------------------------------
# Overall pass rate
# ---------------------------------------------------------------------------

class TestPassRate:
    def test_overall_pass_rate_at_least_85(self):
        result = run_runner('--batch', timeout=180)
        assert result.returncode == 0, f"Batch mode failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        total = sum(d['summary']['total'] for d in data)
        passed = sum(d['summary']['passed'] for d in data)
        assert total > 0, "No tests found"
        rate = passed / total
        assert rate >= 0.85, (
            f"Overall pass rate {rate:.1%} ({passed}/{total}) is below 85%")


# ---------------------------------------------------------------------------
# Spot-check specific expression results
# ---------------------------------------------------------------------------

class TestSpecificResults:
    """Verify specific test cases pass by inspecting runner JSON output."""

    def _find_test(self, fixture, test_name):
        result = run_runner(f'/app/fixtures/{fixture}')
        data = json.loads(result.stdout)
        for t in data['tests']:
            if t['name'] == test_name:
                return t
        return None

    # Arithmetic
    def test_arith_add11(self):
        t = self._find_test('CqlArithmeticFunctionsTest.xml', 'Add11')
        assert t is not None, "Test Add11 not found"
        assert t['pass'], f"Add11 failed: actual={t['actual']}"

    def test_arith_abs_neg1(self):
        t = self._find_test('CqlArithmeticFunctionsTest.xml', 'AbsNeg1')
        assert t is not None, "Test AbsNeg1 not found"
        assert t['pass'], f"AbsNeg1 failed: actual={t['actual']}"

    def test_arith_predecessor_1d(self):
        t = self._find_test('CqlArithmeticFunctionsTest.xml', 'PredecessorOf1D')
        assert t is not None, "Test PredecessorOf1D not found"
        assert t['pass'], f"PredecessorOf1D failed: actual={t['actual']}"

    def test_arith_divide_by_zero(self):
        t = self._find_test('CqlArithmeticFunctionsTest.xml', 'Divide10')
        assert t is not None, "Test Divide10 not found"
        assert t['pass'], f"Divide10 failed: actual={t['actual']}"

    # Logical operators
    def test_logic_false_and_null(self):
        t = self._find_test('CqlLogicalOperatorsTest.xml', 'FalseAndNull')
        assert t is not None, "Test FalseAndNull not found"
        assert t['pass'], f"FalseAndNull failed: actual={t['actual']}"

    def test_logic_false_implies_null(self):
        t = self._find_test('CqlLogicalOperatorsTest.xml', 'FalseImpliesNull')
        assert t is not None, "Test FalseImpliesNull not found"
        assert t['pass'], f"FalseImpliesNull failed: actual={t['actual']}"

    def test_logic_true_or_null(self):
        t = self._find_test('CqlLogicalOperatorsTest.xml', 'TrueOrNull')
        assert t is not None, "Test TrueOrNull not found"
        assert t['pass'], f"TrueOrNull failed: actual={t['actual']}"

    # Comparison
    def test_cmp_eq_int(self):
        t = self._find_test('CqlComparisonOperatorsTest.xml', 'SimpleEqInt1Int1')
        assert t is not None, "Test SimpleEqInt1Int1 not found"
        assert t['pass'], f"SimpleEqInt1Int1 failed: actual={t['actual']}"

    def test_cmp_equiv_null_null(self):
        t = self._find_test('CqlComparisonOperatorsTest.xml', 'EquivNullNull')
        assert t is not None, "Test EquivNullNull not found"
        assert t['pass'], f"EquivNullNull failed: actual={t['actual']}"

    # Conditional
    def test_cond_if_true(self):
        t = self._find_test('CqlConditionalOperatorsTest.xml', 'IfTrue1')
        assert t is not None, "Test IfTrue1 not found"
        assert t['pass'], f"IfTrue1 failed: actual={t['actual']}"

    def test_cond_selected_case(self):
        t = self._find_test('CqlConditionalOperatorsTest.xml', 'SelectedCase1')
        assert t is not None, "Test SelectedCase1 not found"
        assert t['pass'], f"SelectedCase1 failed: actual={t['actual']}"

    # Nullological
    def test_null_coalesce(self):
        t = self._find_test('CqlNullologicalOperatorsTest.xml', 'CoalesceNullA')
        assert t is not None, "Test CoalesceNullA not found"
        assert t['pass'], f"CoalesceNullA failed: actual={t['actual']}"

    def test_null_is_null(self):
        t = self._find_test('CqlNullologicalOperatorsTest.xml', 'IsNullTrue')
        assert t is not None, "Test IsNullTrue not found"
        assert t['pass'], f"IsNullTrue failed: actual={t['actual']}"

    # Types
    def test_types_datetime_proper(self):
        t = self._find_test('CqlTypesTest.xml', 'DateTimeProper')
        assert t is not None, "Test DateTimeProper not found"
        assert t['pass'], f"DateTimeProper failed: actual={t['actual']}"

    def test_types_any_interval(self):
        t = self._find_test('CqlTypesTest.xml', 'AnyInterval')
        assert t is not None, "Test AnyInterval not found"
        assert t['pass'], f"AnyInterval failed: actual={t['actual']}"
