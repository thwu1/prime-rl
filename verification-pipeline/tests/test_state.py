
"""Tests for seL4 Verification Pipeline Auditor."""

import subprocess
import json
import os
import tempfile
import pytest


def run_pipeline(*args):
    """Run the pipeline tool and return parsed JSON output."""
    pipeline_path = '/app/pipeline.py'
    assert os.path.isfile(pipeline_path), (
        f"{pipeline_path} does not exist. "
        f"Contents of /app/: {os.listdir('/app/')}"
    )
    result = subprocess.run(
        ['python3', pipeline_path] + list(args),
        capture_output=True, text=True, cwd='/app'
    )
    assert result.returncode == 0, (
        f"pipeline.py {' '.join(args)} exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"pipeline.py {' '.join(args)} produced invalid JSON.\n"
            f"stdout: {result.stdout!r}\nerror: {e}"
        )


# ---------------------------------------------------------------------------
# ROOT Session Parsing
# ---------------------------------------------------------------------------

class TestParseSessions:
    def test_total_session_count(self):
        """All ROOT files should define exactly 33 sessions."""
        out = run_pipeline('parse-sessions')
        assert out['total'] == 33, f"Expected 33 sessions, got {out['total']}"

    def test_refine_deps(self):
        """Refine extends BaseRefine and lists ASpec, ExecSpec in sessions block."""
        out = run_pipeline('parse-sessions')
        refine = next(s for s in out['sessions'] if s['name'] == 'Refine')
        assert refine['parent'] == 'BaseRefine'
        assert refine['deps'] == ['ASpec', 'BaseRefine', 'ExecSpec']

    def test_ckernel_deps(self):
        """CKernel extends CParser with sessions ExecSpec, CLib, AsmRefine."""
        out = run_pipeline('parse-sessions')
        ck = next(s for s in out['sessions'] if s['name'] == 'CKernel')
        assert ck['deps'] == ['AsmRefine', 'CLib', 'CParser', 'ExecSpec']

    def test_infoflowcbase_deps(self):
        """InfoFlowCBase extends InfoFlow with CRefine in sessions block."""
        out = run_pipeline('parse-sessions')
        ifcb = next(s for s in out['sessions'] if s['name'] == 'InfoFlowCBase')
        assert ifcb['deps'] == ['CRefine', 'InfoFlow']

    def test_lib_has_external_deps(self):
        """Lib depends on external sessions Word_Lib and HOL-Eisbach."""
        out = run_pipeline('parse-sessions')
        lib = next(s for s in out['sessions'] if s['name'] == 'Lib')
        assert 'Word_Lib' in lib['deps']
        assert 'HOL-Eisbach' in lib['deps']

    def test_options_block_ignored(self):
        """AInvs has an options block that should not corrupt theory parsing."""
        out = run_pipeline('parse-sessions')
        ainvs = next(s for s in out['sessions'] if s['name'] == 'AInvs')
        assert ainvs['theories'] == ['AInvsToplevel_AI']
        assert ainvs['deps'] == ['ASpec']


# ---------------------------------------------------------------------------
# XML Test Parsing
# ---------------------------------------------------------------------------

class TestParseTests:
    def test_total_test_count(self):
        """All XML files should define exactly 43 tests."""
        out = run_pipeline('parse-tests')
        assert out['total'] == 43, f"Expected 43 tests, got {out['total']}"

    def test_isabelle_no_deps(self):
        """The isabelle bootstrap test has no dependencies."""
        out = run_pipeline('parse-tests')
        isa = next(t for t in out['tests'] if t['name'] == 'isabelle')
        assert isa['direct_deps'] == []
        assert isa['cpu_timeout'] == 3600

    def test_crefine_deps(self):
        """CRefine is the last in a sequence; has all preceding tests as deps."""
        out = run_pipeline('parse-tests')
        cr = next(t for t in out['tests'] if t['name'] == 'CRefine')
        assert 'CBaseRefine' in cr['direct_deps']
        assert 'CKernel' in cr['direct_deps']
        assert cr['cpu_timeout'] == 36000

    def test_infoflowcbase_mixed_deps(self):
        """InfoFlowCBase has CRefine (explicit attr) and InfoFlow (sequence)."""
        out = run_pipeline('parse-tests')
        ifcb = next(t for t in out['tests'] if t['name'] == 'InfoFlowCBase')
        assert 'CRefine' in ifcb['direct_deps'], \
            "CRefine from explicit depends attribute must be present"
        assert 'InfoFlow' in ifcb['direct_deps'], \
            "InfoFlow from sequence ordering must be present"

    def test_sequence_accumulation(self):
        """RefineOrphanage at end of sequence depends on all prior members."""
        out = run_pipeline('parse-tests')
        ro = next(t for t in out['tests'] if t['name'] == 'RefineOrphanage')
        assert 'AInvs' in ro['direct_deps']
        assert 'BaseRefine' in ro['direct_deps']
        assert 'Refine' in ro['direct_deps']

    def test_nested_set_explicit_dep(self):
        """AutoCorresSEL4 inside nested set has CBaseRefine from explicit attr."""
        out = run_pipeline('parse-tests')
        acs = next(t for t in out['tests'] if t['name'] == 'AutoCorresSEL4')
        assert 'CBaseRefine' in acs['direct_deps']
        assert 'AutoCorres' in acs['direct_deps']
        assert acs['cpu_timeout'] == 21600


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_matched_count(self):
        """31 names appear in both ROOT sessions and XML tests."""
        out = run_pipeline('reconcile')
        assert out['matched_count'] == 31

    def test_root_only(self):
        """CLib and CorresK exist only as ROOT sessions, not XML tests."""
        out = run_pipeline('reconcile')
        assert out['root_only'] == ['CLib', 'CorresK']
        assert out['root_only_count'] == 2

    def test_test_only_count(self):
        """12 XML tests have no corresponding ROOT session."""
        out = run_pipeline('reconcile')
        assert out['test_only_count'] == 12


# ---------------------------------------------------------------------------
# Cascade Exclusion
# ---------------------------------------------------------------------------

class TestCascadeExclusion:
    def test_arm_no_exclusions(self):
        """ARM has no exclusions at all."""
        out = run_pipeline('cascade-exclude', 'ARM')
        assert out['total_excluded_count'] == 0

    def test_arm_hyp_cascade(self):
        """ARM_HYP cascade-excludes InfoFlow chain and DPolicy."""
        out = run_pipeline('cascade-exclude', 'ARM_HYP')
        cascade = set(out['cascade_excluded'])
        assert cascade == {'InfoFlow', 'InfoFlowCBase', 'InfoFlowC', 'DPolicy'}
        assert out['total_excluded_count'] == 9

    def test_x64_total(self):
        """X64 has 14 total exclusions (7 direct + 7 cascade)."""
        out = run_pipeline('cascade-exclude', 'X64')
        assert out['total_excluded_count'] == 14

    def test_aarch64_total(self):
        """AARCH64 has 16 total exclusions."""
        out = run_pipeline('cascade-exclude', 'AARCH64')
        assert out['total_excluded_count'] == 16


# ---------------------------------------------------------------------------
# Critical Path
# ---------------------------------------------------------------------------

class TestCriticalPath:
    def test_arm_critical_path_length(self):
        """ARM critical path = 142200 seconds."""
        out = run_pipeline('critical-path', 'ARM')
        assert out['total_seconds'] == 142200

    def test_arm_critical_path_full_sequence(self):
        """ARM critical path traverses CRefine chain to InfoFlowC."""
        out = run_pipeline('critical-path', 'ARM')
        expected = [
            'isabelle', 'Lib', 'c-kernel', 'CKernel', 'CSpec',
            'CBaseRefine', 'CRefine', 'InfoFlowCBase', 'InfoFlowC'
        ]
        assert out['path'] == expected

    def test_x64_critical_path_length(self):
        """X64 critical path = 120600 (InfoFlow chain excluded)."""
        out = run_pipeline('critical-path', 'X64')
        assert out['total_seconds'] == 120600

    def test_x64_critical_path_ends_at_crefine(self):
        """X64 critical path ends at CRefine."""
        out = run_pipeline('critical-path', 'X64')
        assert out['path'][-1] == 'CRefine'
        assert out['path'][0] == 'isabelle'


# ---------------------------------------------------------------------------
# Cross-Validation
# ---------------------------------------------------------------------------

class TestCrossValidate:
    def test_ok_count(self):
        """24 matched sessions have all ROOT deps covered by XML transitive deps."""
        out = run_pipeline('cross-validate')
        assert out['ok_count'] == 24

    def test_mismatch_count(self):
        """7 matched sessions have ROOT deps not covered by XML transitive deps."""
        out = run_pipeline('cross-validate')
        assert out['mismatch_count'] == 7

    def test_baserefine_uncovered(self):
        """BaseRefine ROOT dep ExecSpec is not in its XML transitive deps."""
        out = run_pipeline('cross-validate')
        br = next(r for r in out['results'] if r['name'] == 'BaseRefine')
        assert br['status'] == 'mismatch'
        assert br['uncovered_deps'] == ['ExecSpec']

    def test_ckernel_uncovered(self):
        """CKernel ROOT deps AsmRefine and ExecSpec not in its XML transitive deps."""
        out = run_pipeline('cross-validate')
        ck = next(r for r in out['results'] if r['name'] == 'CKernel')
        assert ck['status'] == 'mismatch'
        assert ck['uncovered_deps'] == ['AsmRefine', 'ExecSpec']

    def test_dspec_uncovered(self):
        """DSpec ROOT deps ASpec and ExecSpec not in its XML transitive deps."""
        out = run_pipeline('cross-validate')
        ds = next(r for r in out['results'] if r['name'] == 'DSpec')
        assert ds['status'] == 'mismatch'
        assert ds['uncovered_deps'] == ['ASpec', 'ExecSpec']

    def test_infoflowcbase_ok(self):
        """InfoFlowCBase ROOT deps are all covered by XML transitive deps."""
        out = run_pipeline('cross-validate')
        ifcb = next(r for r in out['results'] if r['name'] == 'InfoFlowCBase')
        assert ifcb['status'] == 'ok'
        assert ifcb['uncovered_deps'] == []

    def test_access_ok(self):
        """Access ROOT dep AInvs is covered by XML transitive deps."""
        out = run_pipeline('cross-validate')
        acc = next(r for r in out['results'] if r['name'] == 'Access')
        assert acc['status'] == 'ok'
        assert acc['checked_deps'] == ['AInvs']


# ---------------------------------------------------------------------------
# Change Impact
# ---------------------------------------------------------------------------

class TestChangeImpact:
    def _write_change(self, add=None, remove=None):
        """Write a change file and return its path."""
        change = {
            'add_exclusions': add or [],
            'remove_exclusions': remove or [],
        }
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as f:
            json.dump(change, f)
        return path

    def test_arm_add_ainvs_runnable(self):
        """Excluding AInvs on ARM cascades to 12 total exclusions."""
        path = self._write_change(add=['AInvs'])
        try:
            out = run_pipeline('change-impact', 'ARM', path)
            assert out['old_runnable_count'] == 43
            assert out['new_runnable_count'] == 31
            assert out['delta'] == -12
            assert 'Access' in out['newly_excluded']
            assert 'Bisim' in out['newly_excluded']
            assert 'InfoFlowC' in out['newly_excluded']
        finally:
            os.unlink(path)

    def test_arm_add_ainvs_critical_path(self):
        """Excluding AInvs on ARM shortens critical path by 21600s."""
        path = self._write_change(add=['AInvs'])
        try:
            out = run_pipeline('change-impact', 'ARM', path)
            assert out['old_critical_path_seconds'] == 142200
            assert out['new_critical_path_seconds'] == 120600
            assert out['critical_path_delta'] == -21600
        finally:
            os.unlink(path)

    def test_x64_remove_access_runnable(self):
        """Removing Access exclusion on X64 restores 4 tests."""
        path = self._write_change(remove=['Access'])
        try:
            out = run_pipeline('change-impact', 'X64', path)
            assert out['old_runnable_count'] == 29
            assert out['new_runnable_count'] == 33
            assert out['delta'] == 4
            expected_included = ['Access', 'InfoFlow', 'InfoFlowC', 'InfoFlowCBase']
            assert out['newly_included'] == expected_included
            assert out['newly_excluded'] == []
        finally:
            os.unlink(path)

    def test_x64_remove_access_critical_path(self):
        """Removing Access exclusion on X64 lengthens critical path by 21600s."""
        path = self._write_change(remove=['Access'])
        try:
            out = run_pipeline('change-impact', 'X64', path)
            assert out['old_critical_path_seconds'] == 120600
            assert out['new_critical_path_seconds'] == 142200
            assert out['critical_path_delta'] == 21600
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Schedule (List Scheduling)
# ---------------------------------------------------------------------------

class TestSchedule:
    def test_arm_1cpu_equals_total(self):
        """With 1 CPU, makespan equals total CPU time across all tests."""
        out = run_pipeline('schedule', 'ARM', '1')
        assert out['makespan'] == 357360

    def test_arm_unlimited_equals_critical(self):
        """With unlimited CPUs, makespan equals critical path length."""
        out = run_pipeline('schedule', 'ARM', '100')
        assert out['makespan'] == 142200

    def test_schedule_monotone(self):
        """More CPUs never increases makespan."""
        out2 = run_pipeline('schedule', 'ARM', '2')
        out4 = run_pipeline('schedule', 'ARM', '4')
        assert out4['makespan'] <= out2['makespan']
        assert out2['makespan'] <= 357360
        assert out4['makespan'] >= 142200
