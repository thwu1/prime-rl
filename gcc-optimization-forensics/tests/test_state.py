
import json
import subprocess
import os
import tempfile
import pytest


ALL_CASES = ['case1', 'case2', 'case3', 'case4', 'case5']


def compile_and_run(src, flags):
    """Compile a C file with given flags and return stdout, or None on failure."""
    with tempfile.NamedTemporaryFile(suffix='', delete=False) as f:
        binary = f.name
    try:
        cmd = ['gcc'] + flags.split() + [src, '-o', binary, '-lm']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception:
        return None
    finally:
        if os.path.exists(binary):
            os.unlink(binary)


def load_report():
    report_path = '/app/report.json'
    assert os.path.exists(report_path), "report.json not found at /app/report.json"
    with open(report_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Report structure
# ---------------------------------------------------------------------------
class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), "report.json not found"

    def test_all_cases_present(self):
        report = load_report()
        for case_id in ALL_CASES:
            assert case_id in report, f"Missing {case_id} in report"

    def test_required_keys(self):
        report = load_report()
        required_keys = [
            'output_O0', 'output_O2', 'behavior_differs',
            'ub_type', 'flag', 'correct_output',
        ]
        for case_id in ALL_CASES:
            for key in required_keys:
                assert key in report[case_id], (
                    f"Missing key '{key}' in {case_id}"
                )


# ---------------------------------------------------------------------------
# 2. Output accuracy — compare reported values against actual compilation
# ---------------------------------------------------------------------------
class TestOutputAccuracy:

    @pytest.mark.parametrize("case_id", ALL_CASES)
    def test_o0_output(self, case_id):
        report = load_report()
        src = f'/app/cases/{case_id}.c'
        actual = compile_and_run(src, '-O0')
        assert actual is not None, f"Failed to compile {case_id} at -O0"
        assert report[case_id]['output_O0'] == actual, (
            f"{case_id} O0: reported '{report[case_id]['output_O0']}' "
            f"!= actual '{actual}'"
        )

    @pytest.mark.parametrize("case_id", ALL_CASES)
    def test_o2_output(self, case_id):
        report = load_report()
        src = f'/app/cases/{case_id}.c'
        actual = compile_and_run(src, '-O2')
        assert actual is not None, f"Failed to compile {case_id} at -O2"
        assert report[case_id]['output_O2'] == actual, (
            f"{case_id} O2: reported '{report[case_id]['output_O2']}' "
            f"!= actual '{actual}'"
        )

    @pytest.mark.parametrize("case_id", ALL_CASES)
    def test_behavior_differs_flag(self, case_id):
        report = load_report()
        src = f'/app/cases/{case_id}.c'
        o0_out = compile_and_run(src, '-O0')
        o2_out = compile_and_run(src, '-O2')
        expected_differs = (o0_out != o2_out)
        assert report[case_id]['behavior_differs'] == expected_differs, (
            f"{case_id}: behavior_differs should be {expected_differs} "
            f"(O0='{o0_out}', O2='{o2_out}')"
        )


# ---------------------------------------------------------------------------
# 3. Flag bisection — the reported flag must restore -O0 behaviour
# ---------------------------------------------------------------------------
class TestFlagBisection:

    @pytest.mark.parametrize("case_id", ALL_CASES)
    def test_flag_restores_o0(self, case_id):
        report = load_report()
        entry = report[case_id]

        if not entry['behavior_differs']:
            pytest.skip(f"{case_id} has no behavior difference")

        flag = entry['flag']
        assert flag and len(flag) > 0, (
            f"{case_id}: flag must be non-empty when behavior differs"
        )

        src = f'/app/cases/{case_id}.c'
        o0_out = compile_and_run(src, '-O0')

        # Build the compilation flags to test the reported flag
        clean_flag = flag.lstrip('-')
        if clean_flag in ('fwrapv', 'wrapv'):
            compile_flags = '-O2 -fwrapv'
        elif clean_flag.startswith('fno-'):
            compile_flags = f'-O2 -{clean_flag}'
        elif clean_flag.startswith('f'):
            compile_flags = f'-O2 -fno-{clean_flag[1:]}'
        else:
            compile_flags = f'-O2 -fno-{clean_flag}'

        restored = compile_and_run(src, compile_flags)
        assert restored is not None, (
            f"{case_id}: failed to compile with {compile_flags}"
        )
        assert restored == o0_out, (
            f"{case_id}: with {compile_flags}, got '{restored}' "
            f"but expected O0 output '{o0_out}'"
        )


# ---------------------------------------------------------------------------
# 4. Fixed versions — consistent and correct at all optimisation levels
# ---------------------------------------------------------------------------
class TestFixedVersions:

    @pytest.mark.parametrize("case_id", ALL_CASES)
    def test_fixed_version(self, case_id):
        report = load_report()
        entry = report[case_id]

        if not entry['behavior_differs']:
            pytest.skip(f"{case_id} has no behavior difference, no fix needed")

        fixed_src = f'/app/fixed/{case_id}.c'
        assert os.path.exists(fixed_src), f"Fixed version missing: {fixed_src}"

        fixed_o0 = compile_and_run(fixed_src, '-O0')
        fixed_o2 = compile_and_run(fixed_src, '-O2')

        assert fixed_o0 is not None, f"Fixed {case_id} fails to compile at -O0"
        assert fixed_o2 is not None, f"Fixed {case_id} fails to compile at -O2"
        assert fixed_o0 == fixed_o2, (
            f"Fixed {case_id} inconsistent: O0='{fixed_o0}' vs O2='{fixed_o2}'"
        )
        assert fixed_o0 == entry['correct_output'], (
            f"Fixed {case_id} output '{fixed_o0}' "
            f"!= expected '{entry['correct_output']}'"
        )


# ---------------------------------------------------------------------------
# 5. UB classification — dynamic (no hardcoded case-to-type mapping)
# ---------------------------------------------------------------------------
class TestUBClassification:

    @pytest.mark.parametrize("case_id", ALL_CASES)
    def test_ub_type_matches_behavior(self, case_id):
        """If behavior differs, ub_type must be descriptive; otherwise 'none'."""
        report = load_report()
        entry = report[case_id]
        ub = entry['ub_type'].lower().strip()

        if entry['behavior_differs']:
            assert ub and ub != 'none', (
                f"{case_id}: behavior differs but ub_type is "
                f"'{entry['ub_type']}' — should describe the UB"
            )
        else:
            assert ub == 'none' or ub == '' or 'well-defined' in ub, (
                f"{case_id}: behavior is consistent but ub_type is "
                f"'{entry['ub_type']}' — should be 'none'"
            )


# ---------------------------------------------------------------------------
# 6. Coverage — at least 2 differ and at least 2 are consistent
# ---------------------------------------------------------------------------
class TestMinimumCoverage:

    def test_minimum_differing_cases(self):
        report = load_report()
        differing = sum(
            1 for c in ALL_CASES if report[c]['behavior_differs']
        )
        assert differing >= 2, (
            f"Expected at least 2 cases with differing behavior, got {differing}"
        )

    def test_minimum_consistent_cases(self):
        report = load_report()
        consistent = sum(
            1 for c in ALL_CASES if not report[c]['behavior_differs']
        )
        assert consistent >= 2, (
            f"Expected at least 2 consistent cases, got {consistent}"
        )
