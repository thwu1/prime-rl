
import subprocess
import json
import os
import shutil
import tempfile
import pytest

TLA_TOOLS = "/app/tools/tla2tools.jar"


def translate_and_check(tla_file, cfg_file):
    """Copy files to temp dir, translate PlusCal, run TLC, return (passed, output)."""
    tmpdir = tempfile.mkdtemp(prefix="tlc_")
    tla_base = os.path.basename(tla_file)
    cfg_base = os.path.basename(cfg_file)
    module = tla_base.replace(".tla", "")

    try:
        shutil.copy2(tla_file, os.path.join(tmpdir, tla_base))
        shutil.copy2(cfg_file, os.path.join(tmpdir, cfg_base))

        # Translate PlusCal (ignore errors - may be raw TLA+)
        subprocess.run(
            ["java", "-Xmx512m", "-cp", TLA_TOOLS, "pcal.trans", tla_base],
            capture_output=True, text=True, timeout=60, cwd=tmpdir
        )

        # Run TLC model checker
        result = subprocess.run(
            ["java", "-Xmx512m", "-cp", TLA_TOOLS, "tlc2.TLC",
             "-config", cfg_base, module, "-workers", "1"],
            capture_output=True, text=True, timeout=240, cwd=tmpdir
        )

        output = result.stdout + "\n" + result.stderr
        passed = "Model checking completed. No error has been found." in output
        has_error = ("Error:" in output and "is violated" in output) or \
                    "Deadlock reached" in output

        return passed and not has_error, output
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def verify_buggy_spec_fails():
    """Sanity check: the original buggy spec SHOULD fail model checking."""
    if not os.path.exists("/app/commit_protocol.tla"):
        return
    passed, output = translate_and_check(
        "/app/commit_protocol.tla", "/app/commit_protocol.cfg"
    )
    assert not passed, "Original spec should have safety violations"


# ---------------------------------------------------------------------------
# Tests for the fixed specification
# ---------------------------------------------------------------------------

class TestFixedSpec:
    """Verify the agent's fixed specification passes all safety invariants."""

    def test_fixed_spec_exists(self):
        assert os.path.exists("/app/commit_protocol_fixed.tla"), \
            "Fixed spec not found at /app/commit_protocol_fixed.tla"
        assert os.path.exists("/app/commit_protocol_fixed.cfg"), \
            "Fixed config not found at /app/commit_protocol_fixed.cfg"

    def test_fixed_cfg_has_invariants(self):
        with open("/app/commit_protocol_fixed.cfg") as f:
            cfg = f.read()
        assert "Consistency" in cfg, "Fixed config must check Consistency invariant"
        assert "CommitValidity" in cfg, "Fixed config must check CommitValidity invariant"

    def test_fixed_spec_passes_model_checker(self):
        passed, output = translate_and_check(
            "/app/commit_protocol_fixed.tla",
            "/app/commit_protocol_fixed.cfg"
        )
        assert passed, f"Fixed spec failed TLC model checking:\n{output[-2000:]}"

    def test_fixed_spec_retains_protocol_structure(self):
        with open("/app/commit_protocol_fixed.tla") as f:
            spec = f.read()
        # Must still model a coordinator and participants
        assert "Coordinator" in spec or "coordinator" in spec or "coord" in spec, \
            "Fixed spec must have a coordinator process"
        assert "Participants" in spec or "participants" in spec, \
            "Fixed spec must have participant processes"
        # Must still have the core protocol phases
        assert "prepared" in spec or "prepare" in spec, \
            "Fixed spec must model prepare phase"
        assert "committed" in spec, "Fixed spec must model commit state"
        assert "aborted" in spec, "Fixed spec must model abort state"


# ---------------------------------------------------------------------------
# Tests for the recovery extension
# ---------------------------------------------------------------------------

class TestRecoverySpec:
    """Verify the recovery extension handles coordinator failure correctly."""

    def test_recovery_spec_exists(self):
        assert os.path.exists("/app/commit_protocol_recovery.tla"), \
            "Recovery spec not found at /app/commit_protocol_recovery.tla"
        assert os.path.exists("/app/commit_protocol_recovery.cfg"), \
            "Recovery config not found at /app/commit_protocol_recovery.cfg"

    def test_recovery_cfg_has_liveness(self):
        with open("/app/commit_protocol_recovery.cfg") as f:
            cfg = f.read()
        assert "PROPERTY" in cfg, \
            "Recovery config must include a PROPERTY for liveness checking"

    def test_recovery_cfg_has_safety_invariants(self):
        with open("/app/commit_protocol_recovery.cfg") as f:
            cfg = f.read()
        assert "Consistency" in cfg, "Recovery config must check Consistency"
        assert "CommitValidity" in cfg, "Recovery config must check CommitValidity"

    def test_recovery_models_coordinator_failure(self):
        with open("/app/commit_protocol_recovery.tla") as f:
            spec = f.read().lower()
        crash_terms = [
            "crash", "fail", "dead", "alive", "fault", "halt",
            "timeout", "down", "unavailable", "lost"
        ]
        has_crash = any(term in spec for term in crash_terms)
        assert has_crash, \
            "Recovery spec must model coordinator failure (expected crash/fail/fault terminology)"

    def test_recovery_has_recovery_mechanism(self):
        with open("/app/commit_protocol_recovery.tla") as f:
            spec = f.read().lower()
        recovery_terms = [
            "recovery", "recover", "backup", "resolve", "termination",
            "leader", "election", "helper", "monitor", "watchdog",
            "fallback", "substitute", "delegate", "rescue", "repair"
        ]
        has_recovery = any(term in spec for term in recovery_terms)
        # Also check for additional process (any process beyond coord/part)
        import re
        process_count = len(re.findall(r'process\s*\(', spec))
        has_extra_process = process_count >= 3
        assert has_recovery or has_extra_process, \
            "Recovery spec must include a recovery mechanism or additional process"

    def test_recovery_spec_passes_model_checker(self):
        """The recovery spec must pass TLC with both safety and liveness."""
        passed, output = translate_and_check(
            "/app/commit_protocol_recovery.tla",
            "/app/commit_protocol_recovery.cfg"
        )
        assert passed, f"Recovery spec failed TLC model checking:\n{output[-2000:]}"


# ---------------------------------------------------------------------------
# Tests for the analysis report
# ---------------------------------------------------------------------------

class TestAnalysis:
    """Verify the analysis report is complete and well-structured."""

    def test_analysis_exists(self):
        assert os.path.exists("/app/analysis.json"), \
            "Analysis not found at /app/analysis.json"

    def test_analysis_valid_json(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert "bugs" in data, "analysis.json must contain 'bugs' key"
        assert "recovery_mechanism" in data, "analysis.json must contain 'recovery_mechanism'"
        assert "liveness_property" in data, "analysis.json must contain 'liveness_property'"

    def test_analysis_identifies_bugs(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        bugs = data["bugs"]
        assert len(bugs) >= 2, \
            f"Should identify at least 2 bugs, found {len(bugs)}"
        for i, bug in enumerate(bugs):
            assert "description" in bug, f"Bug {i} missing 'description'"
            assert "fix" in bug, f"Bug {i} missing 'fix'"
            assert "invariant_violated" in bug, f"Bug {i} missing 'invariant_violated'"
            assert len(bug["description"]) > 10, f"Bug {i} description too short"
            assert len(bug["fix"]) > 10, f"Bug {i} fix description too short"

    def test_analysis_describes_recovery(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert len(data["recovery_mechanism"]) > 30, \
            "Recovery mechanism description too short"
        assert len(data["liveness_property"]) > 10, \
            "Liveness property description too short"

    def test_analysis_bug_invariants_valid(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        valid_invariants = {"Consistency", "CommitValidity", "TypeOK"}
        for bug in data["bugs"]:
            inv = bug["invariant_violated"]
            assert inv in valid_invariants, \
                f"Unknown invariant '{inv}' - expected one of {valid_invariants}"
