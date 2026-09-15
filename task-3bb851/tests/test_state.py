
"""Tests for FDB Simulation Trace Forensics task."""

import json
import os
import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


def json_contains(obj, value):
    """Recursively check if value (string) appears anywhere in JSON."""
    if isinstance(obj, str):
        return value.lower() in obj.lower()
    if isinstance(obj, (int, float, bool)):
        return str(value).lower() == str(obj).lower()
    if isinstance(obj, dict):
        return any(json_contains(v, value) for v in obj.values())
    if isinstance(obj, list):
        return any(json_contains(v, value) for v in obj)
    return False


def get_nested(obj, *keys, default=None):
    """Safely get nested dict values, trying multiple key conventions."""
    for key in keys:
        if isinstance(obj, dict) and key in obj:
            return obj[key]
    return default


def find_phase(data, phase_num):
    """Find phase data by phase number, searching common structures."""
    phases = get_nested(data, "phases", default=[])
    if not phases:
        return None
    for p in phases:
        pn = get_nested(p, "phase", "phase_number", "phase_num", default=0)
        if pn == phase_num:
            return p
    # Fallback: use index
    if 0 < phase_num <= len(phases):
        return phases[phase_num - 1]
    return None


def find_spec(data, name_substring):
    """Find a spec validation result by name substring."""
    specs = get_nested(data, "specs", "results", "validations", default=[])
    for s in specs:
        spec_name = get_nested(s, "name", "spec_name", "pair_name", default="")
        if name_substring.lower() in spec_name.lower():
            return s
    return None


def find_command(data, test_type):
    """Find orchestrator command by test type."""
    commands = get_nested(data, "commands", "scenarios", "results", default=[])
    for c in commands:
        ct = get_nested(c, "test_type", "direction", "type", default="")
        if test_type.lower() in ct.lower():
            return c
    return None


# ========== ANALYZER TESTS ==========

class TestAnalyzerRun001:
    """Tests for the failing restart test analysis (run_001)."""

    @pytest.fixture
    def data(self):
        return load_json("/app/results/run_001_analysis.json")

    def test_result_is_failed(self, data):
        """Run 001 should be identified as FAILED."""
        result = get_nested(data, "test_result", "result", "status", default="")
        assert result.upper() in ("FAILED", "FAILURE", "FAIL"), \
            f"Run 001 should be FAILED, got: {result}"

    def test_has_two_phases(self, data):
        """Run 001 is a restart test with two phases."""
        phases = get_nested(data, "phases", default=[])
        assert len(phases) == 2, f"Expected 2 phases, got {len(phases)}"

    def test_phase1_recovery_completed(self, data):
        """Phase 1 should complete recovery to FULLY_RECOVERED."""
        p1 = find_phase(data, 1)
        assert p1 is not None, "Phase 1 not found"
        # Check recovery completed
        completed = get_nested(p1, "recovery_completed", "recovered",
                               "fully_recovered", default=None)
        if completed is not None:
            assert completed is True, "Phase 1 recovery should be complete"
        else:
            # Check recovery states contain FULLY_RECOVERED
            states = get_nested(p1, "recovery_states", "recovery_phases",
                                "phases", default=[])
            assert "FULLY_RECOVERED" in states, \
                "Phase 1 should reach FULLY_RECOVERED"

    def test_phase2_recovery_stuck(self, data):
        """Phase 2 recovery should NOT complete (stuck at RECRUITING)."""
        p2 = find_phase(data, 2)
        assert p2 is not None, "Phase 2 not found"
        completed = get_nested(p2, "recovery_completed", "recovered",
                               "fully_recovered", default=None)
        if completed is not None:
            assert completed is False, "Phase 2 recovery should NOT complete"
        else:
            states = get_nested(p2, "recovery_states", "recovery_phases",
                                "phases", default=[])
            assert "FULLY_RECOVERED" not in states, \
                "Phase 2 should NOT reach FULLY_RECOVERED"

    def test_phase2_last_recovery_state(self, data):
        """Phase 2 should get stuck at RECRUITING."""
        p2 = find_phase(data, 2)
        assert p2 is not None
        last_state = get_nested(p2, "final_recovery_state", "last_state",
                                "last_recovery_state", default="")
        if last_state:
            assert last_state == "RECRUITING", \
                f"Phase 2 should be stuck at RECRUITING, got: {last_state}"
        else:
            states = get_nested(p2, "recovery_states", "recovery_phases",
                                "phases", default=[])
            assert len(states) > 0 and states[-1] == "RECRUITING"

    def test_phase2_errors_detected(self, data):
        """Phase 2 should have Severity>=40 errors detected."""
        p2 = find_phase(data, 2)
        assert p2 is not None
        errors = get_nested(p2, "errors", default=[])
        # Should have at least 2 TLogRejoinError + 1 SimulationTimeout = 3
        # (injected fault should be excluded)
        assert len(errors) >= 2, \
            f"Phase 2 should have at least 2 real errors, got {len(errors)}"

    def test_phase2_incompatible_protocol(self, data):
        """Phase 2 errors should include incompatible_protocol_version."""
        p2 = find_phase(data, 2)
        assert p2 is not None
        errors = get_nested(p2, "errors", default=[])
        has_proto_error = any(
            json_contains(e, "incompatible_protocol_version")
            for e in errors
        )
        assert has_proto_error, \
            "Phase 2 should contain incompatible_protocol_version error"

    def test_injected_fault_excluded(self, data):
        """Injected faults (ErrorIsInjectedFault=1) should be excluded."""
        p2 = find_phase(data, 2)
        assert p2 is not None
        errors = get_nested(p2, "errors", default=[])
        has_injected = any(
            json_contains(e, "BuggifyInjectedFault")
            for e in errors
        )
        assert not has_injected, \
            "Injected faults should be excluded from error list"

    def test_processes_identified(self, data):
        """Should identify 8 unique processes."""
        p1 = find_phase(data, 1)
        assert p1 is not None
        procs = get_nested(p1, "processes", default=[])
        machines = set()
        for p in procs:
            m = get_nested(p, "machine", "Machine", "address", default="")
            if m:
                machines.add(m)
        assert len(machines) == 8, \
            f"Phase 1 should have 8 unique processes, got {len(machines)}"

    def test_cc_process_roles(self, data):
        """Cluster controller should have CC and CD roles."""
        p1 = find_phase(data, 1)
        assert p1 is not None
        procs = get_nested(p1, "processes", default=[])
        cc_proc = None
        for p in procs:
            m = get_nested(p, "machine", "Machine", "address", default="")
            if "10.0.0.1" in m:
                cc_proc = p
                break
        assert cc_proc is not None, "CC process not found"
        roles = get_nested(cc_proc, "roles", default=[])
        assert "CC" in roles and "CD" in roles, \
            f"CC process should have CC and CD roles, got: {roles}"

    def test_root_cause_analysis(self, data):
        """Root cause should mention protocol version or TLog."""
        root_cause = get_nested(data, "root_cause", "root_cause_analysis",
                                "failure_analysis", default={})
        if isinstance(root_cause, dict):
            rc_text = json.dumps(root_cause).lower()
        else:
            rc_text = str(root_cause).lower()
        assert ("protocol" in rc_text or "tlog" in rc_text or
                "incompatible" in rc_text or "rejoin" in rc_text), \
            f"Root cause should mention protocol/TLog/incompatible, got: {rc_text[:200]}"

    def test_root_cause_has_protocol_version_ids(self, data):
        """Root cause must include protocol version hex identifiers from the knowledge database."""
        root_cause = get_nested(data, "root_cause", "root_cause_analysis",
                                "failure_analysis", default={})
        if isinstance(root_cause, dict):
            rc_text = json.dumps(root_cause)
        else:
            rc_text = str(root_cause)
        # These hex protocol version IDs are ONLY available in fdb_knowledge.db
        has_old_proto = "0x0FDB00B072040000" in rc_text or "0FDB00B072" in rc_text
        has_new_proto = "0x0FDB00B073000000" in rc_text or "0FDB00B073" in rc_text
        assert has_old_proto and has_new_proto, \
            f"Root cause must include protocol version hex IDs from the knowledge database (7.2.4 and 7.3.0 protocols)"

    def test_root_cause_protocol_incompatible(self, data):
        """Root cause protocol_versions.compatible must be false (from protocol_compat table)."""
        root_cause = get_nested(data, "root_cause", "root_cause_analysis",
                                "failure_analysis", default={})
        proto = get_nested(root_cause, "protocol_versions", default={})
        if proto:
            compat = get_nested(proto, "compatible", "is_compatible", default=None)
            assert compat is False, \
                "protocol_versions.compatible should be false (7.2<->7.3 are incompatible)"
        else:
            # Allow protocol info in description if not structured
            rc_text = json.dumps(root_cause) if isinstance(root_cause, dict) else str(root_cause)
            assert "incompatible" in rc_text.lower(), \
                "Root cause must indicate protocol incompatibility"

    def test_phase1_saveandkill(self, data):
        """Phase 1 should show SaveAndKill was triggered."""
        p1 = find_phase(data, 1)
        assert p1 is not None
        # Check various ways this could be reported
        sak = get_nested(p1, "saveandkill_triggered", "save_and_kill",
                         "saveandkill", default=None)
        if sak is not None:
            assert sak is True
        else:
            # Check workloads
            assert json_contains(p1, "SaveAndKill"), \
                "Phase 1 should report SaveAndKill activity"

    def test_phase1_binary_version(self, data):
        """Phase 1 should report binary version 7.2.4."""
        p1 = find_phase(data, 1)
        assert p1 is not None
        ver = get_nested(p1, "binary_version", "version", default="")
        assert "7.2" in ver, f"Phase 1 binary should be 7.2.x, got: {ver}"

    def test_phase2_binary_version(self, data):
        """Phase 2 should report binary version 7.3.0."""
        p2 = find_phase(data, 2)
        assert p2 is not None
        ver = get_nested(p2, "binary_version", "version", default="")
        assert "7.3" in ver, f"Phase 2 binary should be 7.3.x, got: {ver}"


class TestAnalyzerRun002:
    """Tests for the passing restart test analysis (run_002)."""

    @pytest.fixture
    def data(self):
        return load_json("/app/results/run_002_analysis.json")

    def test_result_is_passed(self, data):
        """Run 002 should be identified as PASSED."""
        result = get_nested(data, "test_result", "result", "status", default="")
        assert result.upper() in ("PASSED", "SUCCESS", "PASS"), \
            f"Run 002 should be PASSED, got: {result}"

    def test_has_two_phases(self, data):
        """Run 002 is a restart test with two phases."""
        phases = get_nested(data, "phases", default=[])
        assert len(phases) == 2

    def test_both_phases_recovered(self, data):
        """Both phases should complete recovery."""
        for i in (1, 2):
            p = find_phase(data, i)
            assert p is not None
            completed = get_nested(p, "recovery_completed", "recovered",
                                   "fully_recovered", default=None)
            if completed is not None:
                assert completed is True, f"Phase {i} recovery should complete"
            else:
                states = get_nested(p, "recovery_states", "recovery_phases",
                                    "phases", default=[])
                assert "FULLY_RECOVERED" in states

    def test_no_errors(self, data):
        """Run 002 should have no errors in either phase."""
        for i in (1, 2):
            p = find_phase(data, i)
            assert p is not None
            errors = get_nested(p, "errors", default=[])
            assert len(errors) == 0, \
                f"Phase {i} should have 0 errors, got {len(errors)}"


class TestAnalyzerRun003:
    """Tests for the fast test analysis (run_003)."""

    @pytest.fixture
    def data(self):
        return load_json("/app/results/run_003_analysis.json")

    def test_result_is_passed(self, data):
        """Run 003 should be identified as PASSED."""
        result = get_nested(data, "test_result", "result", "status", default="")
        assert result.upper() in ("PASSED", "SUCCESS", "PASS")

    def test_single_phase(self, data):
        """Run 003 is a fast test with one phase."""
        phases = get_nested(data, "phases", default=[])
        assert len(phases) == 1, f"Fast test should have 1 phase, got {len(phases)}"

    def test_recovery_completed(self, data):
        """Single phase should complete recovery."""
        p = find_phase(data, 1)
        assert p is not None
        completed = get_nested(p, "recovery_completed", "recovered",
                               "fully_recovered", default=None)
        if completed is not None:
            assert completed is True
        else:
            states = get_nested(p, "recovery_states", "recovery_phases",
                                "phases", default=[])
            assert "FULLY_RECOVERED" in states

    def test_six_processes(self, data):
        """Fast test should identify 6 processes."""
        p = find_phase(data, 1)
        assert p is not None
        procs = get_nested(p, "processes", default=[])
        assert len(procs) == 6, f"Should have 6 processes, got {len(procs)}"


# ========== SPEC VALIDATOR TESTS ==========

class TestSpecValidator:
    """Tests for the TOML spec validator."""

    @pytest.fixture
    def data(self):
        return load_json("/app/results/spec_validation.json")

    def test_broken_upgrade_invalid(self, data):
        """broken_upgrade pair should be flagged as invalid."""
        spec = find_spec(data, "upgrade")
        assert spec is not None, "broken_upgrade spec result not found"
        valid = get_nested(spec, "valid", "is_valid", default=None)
        assert valid is False, "broken_upgrade should be invalid"

    def test_broken_upgrade_saveandkill_error(self, data):
        """broken_upgrade should report missing SaveAndKill in phase 1."""
        spec = find_spec(data, "upgrade")
        assert spec is not None
        errors = get_nested(spec, "errors", "issues", "violations", default=[])
        errors_text = " ".join(str(e).lower() for e in errors)
        assert ("saveandkill" in errors_text or "save_and_kill" in errors_text
                or "save and kill" in errors_text), \
            f"Should report SaveAndKill issue, errors: {errors}"

    def test_broken_downgrade_invalid(self, data):
        """broken_downgrade pair should be flagged as invalid."""
        spec = find_spec(data, "downgrade")
        assert spec is not None, "broken_downgrade spec result not found"
        valid = get_nested(spec, "valid", "is_valid", default=None)
        assert valid is False, "broken_downgrade should be invalid"

    def test_broken_downgrade_phase2_saveandkill(self, data):
        """broken_downgrade should report SaveAndKill in phase 2."""
        spec = find_spec(data, "downgrade")
        assert spec is not None
        errors = get_nested(spec, "errors", "issues", "violations", default=[])
        errors_text = " ".join(str(e).lower() for e in errors)
        assert ("phase 2" in errors_text or "phase2" in errors_text), \
            f"Should report phase 2 issue, errors: {errors}"

    def test_broken_cycle_invalid(self, data):
        """broken_cycle pair should be flagged as invalid."""
        spec = find_spec(data, "cycle")
        assert spec is not None, "broken_cycle spec result not found"
        valid = get_nested(spec, "valid", "is_valid", default=None)
        assert valid is False, "broken_cycle should be invalid"

    def test_broken_cycle_runsetup_error(self, data):
        """broken_cycle should report runSetup issue in phase 2."""
        spec = find_spec(data, "cycle")
        assert spec is not None
        errors = get_nested(spec, "errors", "issues", "violations", default=[])
        errors_text = " ".join(str(e).lower() for e in errors)
        assert ("runsetup" in errors_text or "run_setup" in errors_text
                or "setup" in errors_text), \
            f"Should report runSetup issue, errors: {errors}"

    def test_broken_cycle_inconsistent_config(self, data):
        """broken_cycle should report inconsistent configuration."""
        spec = find_spec(data, "cycle")
        assert spec is not None
        errors = get_nested(spec, "errors", "issues", "violations", default=[])
        errors_text = " ".join(str(e).lower() for e in errors)
        assert ("inconsisten" in errors_text or "mismatch" in errors_text
                or "differ" in errors_text or "storageengine" in errors_text
                or "configuration" in errors_text), \
            f"Should report config inconsistency, errors: {errors}"

    def test_correct_storefront_valid(self, data):
        """correct_storefront pair should be flagged as valid."""
        spec = find_spec(data, "storefront")
        assert spec is not None, "correct_storefront spec result not found"
        valid = get_nested(spec, "valid", "is_valid", default=None)
        assert valid is True, "correct_storefront should be valid"

    def test_correct_storefront_no_errors(self, data):
        """correct_storefront should have no errors."""
        spec = find_spec(data, "storefront")
        assert spec is not None
        errors = get_nested(spec, "errors", "issues", "violations", default=[])
        assert len(errors) == 0, \
            f"correct_storefront should have 0 errors, got: {errors}"

    def test_all_four_pairs_validated(self, data):
        """All four spec pairs should be in validation results."""
        specs = get_nested(data, "specs", "results", "validations", default=[])
        assert len(specs) >= 4, \
            f"Should validate at least 4 spec pairs, got {len(specs)}"


# ========== ORCHESTRATOR TESTS ==========

class TestOrchestrator:
    """Tests for the restart test orchestrator."""

    @pytest.fixture
    def data(self):
        return load_json("/app/results/reproduction_commands.json")

    def test_has_two_scenarios(self, data):
        """Should generate commands for 2 scenarios."""
        commands = get_nested(data, "commands", "scenarios", "results", default=[])
        assert len(commands) >= 2, \
            f"Should have at least 2 command sets, got {len(commands)}"

    def test_upgrade_binary_selection(self, data):
        """Upgrade test: Phase 1 uses old binary (7.2.x), Phase 2 uses new (7.3.x)."""
        cmd = find_command(data, "upgrade")
        assert cmd is not None, "Upgrade command not found"
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        p1_binary = get_nested(p1, "binary", "binary_path", "fdbserver", default="")
        p2_binary = get_nested(p2, "binary", "binary_path", "fdbserver", default="")
        # Old binary for phase 1
        assert "7.2" in p1_binary, \
            f"Upgrade phase 1 should use 7.2.x binary, got: {p1_binary}"
        # New binary for phase 2
        assert "7.3" in p2_binary, \
            f"Upgrade phase 2 should use 7.3.x binary, got: {p2_binary}"

    def test_downgrade_binary_selection(self, data):
        """Downgrade test: Phase 1 uses new binary (7.3.x), Phase 2 uses old (7.2.x)."""
        cmd = find_command(data, "downgrade")
        assert cmd is not None, "Downgrade command not found"
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        p1_binary = get_nested(p1, "binary", "binary_path", "fdbserver", default="")
        p2_binary = get_nested(p2, "binary", "binary_path", "fdbserver", default="")
        # New binary for phase 1
        assert "7.3" in p1_binary, \
            f"Downgrade phase 1 should use 7.3.x binary, got: {p1_binary}"
        # Old binary for phase 2
        assert "7.2" in p2_binary, \
            f"Downgrade phase 2 should use 7.2.x binary, got: {p2_binary}"

    def test_upgrade_seed_increment(self, data):
        """Phase 2 seed should be phase 1 seed + 1."""
        cmd = find_command(data, "upgrade")
        assert cmd is not None
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        s1 = get_nested(p1, "seed", default=0)
        s2 = get_nested(p2, "seed", default=0)
        assert s2 == s1 + 1, f"Phase 2 seed should be {s1 + 1}, got {s2}"

    def test_downgrade_seed_increment(self, data):
        """Downgrade test should also use seed+1 for phase 2."""
        cmd = find_command(data, "downgrade")
        assert cmd is not None
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        s1 = get_nested(p1, "seed", default=0)
        s2 = get_nested(p2, "seed", default=0)
        assert s2 == s1 + 1, f"Downgrade phase 2 seed should be {s1 + 1}, got {s2}"

    def test_phase2_restarting_flag(self, data):
        """Phase 2 commands must include --restarting flag."""
        commands = get_nested(data, "commands", "scenarios", "results", default=[])
        for cmd in commands:
            p2 = get_nested(cmd, "phase2", "run2", "second", default={})
            # Check command string
            p2_cmd = get_nested(p2, "command", "cmd", "cmdline", default="")
            p2_restarting = get_nested(p2, "restarting", default=None)
            assert ("--restarting" in p2_cmd or p2_restarting is True), \
                f"Phase 2 should have --restarting, cmd: {p2_cmd}"

    def test_phase1_no_restarting_flag(self, data):
        """Phase 1 commands must NOT include --restarting flag."""
        commands = get_nested(data, "commands", "scenarios", "results", default=[])
        for cmd in commands:
            p1 = get_nested(cmd, "phase1", "run1", "first", default={})
            p1_cmd = get_nested(p1, "command", "cmd", "cmdline", default="")
            p1_restarting = get_nested(p1, "restarting", default=None)
            assert ("--restarting" not in p1_cmd and p1_restarting is not True), \
                f"Phase 1 should NOT have --restarting, cmd: {p1_cmd}"

    def test_commands_include_simulation_flag(self, data):
        """Commands should include -r simulation flag."""
        commands = get_nested(data, "commands", "scenarios", "results", default=[])
        for cmd in commands:
            for phase_key in ("phase1", "phase2", "run1", "run2", "first", "second"):
                phase = get_nested(cmd, phase_key, default=None)
                if phase:
                    p_cmd = get_nested(phase, "command", "cmd", "cmdline", default="")
                    if p_cmd:
                        assert "-r simulation" in p_cmd, \
                            f"Command should include '-r simulation': {p_cmd}"

    def test_upgrade_specific_seeds(self, data):
        """Upgrade test should use seed 523887594 / 523887595."""
        cmd = find_command(data, "upgrade")
        assert cmd is not None
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        assert get_nested(p1, "seed", default=0) == 523887594
        assert get_nested(p2, "seed", default=0) == 523887595

    def test_upgrade_binary_resolved_from_db(self, data):
        """Upgrade binary paths should be full filesystem paths from binary_registry."""
        cmd = find_command(data, "upgrade")
        assert cmd is not None
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        p1_binary = get_nested(p1, "binary", "binary_path", "fdbserver", default="")
        p2_binary = get_nested(p2, "binary", "binary_path", "fdbserver", default="")
        # Paths must be full filesystem paths resolved from binary_registry
        assert p1_binary.startswith("/opt/fdb/bin/"), \
            f"Phase 1 binary should be a resolved path, got: {p1_binary}"
        assert p2_binary.startswith("/opt/fdb/bin/"), \
            f"Phase 2 binary should be a resolved path, got: {p2_binary}"

    def test_downgrade_binary_resolved_from_db(self, data):
        """Downgrade binary paths should be full filesystem paths from binary_registry."""
        cmd = find_command(data, "downgrade")
        assert cmd is not None
        p1 = get_nested(cmd, "phase1", "run1", "first", default={})
        p2 = get_nested(cmd, "phase2", "run2", "second", default={})
        p1_binary = get_nested(p1, "binary", "binary_path", "fdbserver", default="")
        p2_binary = get_nested(p2, "binary", "binary_path", "fdbserver", default="")
        assert p1_binary.startswith("/opt/fdb/bin/"), \
            f"Phase 1 binary should be a resolved path, got: {p1_binary}"
        assert p2_binary.startswith("/opt/fdb/bin/"), \
            f"Phase 2 binary should be a resolved path, got: {p2_binary}"


# ========== RESULTS FILE EXISTENCE TESTS ==========

class TestResultsExist:
    """Ensure all required output files exist and are valid JSON."""

    @pytest.mark.parametrize("filename", [
        "run_001_analysis.json",
        "run_002_analysis.json",
        "run_003_analysis.json",
        "spec_validation.json",
        "reproduction_commands.json",
    ])
    def test_result_file_exists(self, filename):
        path = f"/app/results/{filename}"
        assert os.path.exists(path), f"Missing result file: {path}"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict), f"{filename} should be a JSON object"
