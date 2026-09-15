
import subprocess
import os
import re
import pytest

SPEC_DIR = "/app/spec"
TLA_TOOLS = "/opt/tla2tools.jar"


class TestTicketLockSpec:
    """Verify the fixed ticket_lock TLA+ specification."""

    def test_sany_passes(self):
        """The spec must pass SANY syntax checking without errors."""
        result = subprocess.run(
            ["java", "-cp", TLA_TOOLS, "tla2sany.SANY", "ticket_lock.tla"],
            capture_output=True, text=True, cwd=SPEC_DIR, timeout=60
        )
        output = result.stdout + result.stderr
        assert "*** Errors" not in output, f"SANY reported errors:\n{output}"
        assert "***Parse Error***" not in output, f"SANY parse error:\n{output}"
        assert "Semantic processing of module ticket_lock" in output, \
            f"SANY did not complete semantic processing:\n{output}"

    def test_nil_is_constant(self):
        """Nil must be a CONSTANT, not defined via unbounded CHOOSE."""
        with open(os.path.join(SPEC_DIR, "ticket_lock.tla")) as f:
            spec = f.read()
        assert "CHOOSE v : v" not in spec, \
            "Spec still contains unbounded CHOOSE for Nil"
        constants_match = re.search(
            r"CONSTANTS?\s+(.+?)(?:\n\n|\nVARIABLES)", spec, re.DOTALL
        )
        assert constants_match is not None, "No CONSTANTS declaration found"
        assert "Nil" in constants_match.group(1), \
            f"Nil not in CONSTANTS: {constants_match.group(1)}"

    def test_config_correct(self):
        """Config must have correct SPECIFICATION, bind Nil, declare all invariants."""
        with open(os.path.join(SPEC_DIR, "ticket_lock.cfg")) as f:
            config = f.read()
        spec_match = re.search(r"SPECIFICATION\s+(\w+)", config)
        assert spec_match is not None, "No SPECIFICATION in config"
        assert spec_match.group(1) == "Specification", \
            f"SPECIFICATION is '{spec_match.group(1)}', expected 'Specification'"
        assert re.search(r"Nil\s*=", config), "Config does not bind Nil"
        for inv in ["MutualExclusion", "HolderConsistency",
                     "QueueValidity", "NoStaleHolder"]:
            assert inv in config, f"Config missing invariant: {inv}"

    def test_tlc_verifies(self):
        """TLC must complete with no errors, violations, or deadlocks."""
        result = subprocess.run(
            ["java", "-cp", TLA_TOOLS, "tlc2.TLC",
             "-config", "ticket_lock.cfg",
             "-workers", "1",
             "ticket_lock.tla"],
            capture_output=True, text=True, cwd=SPEC_DIR, timeout=240
        )
        output = result.stdout + result.stderr
        assert "Model checking completed. No error has been found." in output, \
            f"TLC did not complete successfully:\n{output[-3000:]}"
        assert "is violated" not in output, \
            f"Invariant violation detected:\n{output[-3000:]}"
        assert "Deadlock reached" not in output, \
            f"Deadlock reached:\n{output[-3000:]}"
        assert "TLC threw an unexpected exception" not in output, \
            f"TLC exception:\n{output[-3000:]}"


class TestRWLockSpec:
    """Verify the fixed and completed rwlock TLA+ specification."""

    def test_sany_passes(self):
        """The spec must pass SANY syntax checking without errors."""
        result = subprocess.run(
            ["java", "-cp", TLA_TOOLS, "tla2sany.SANY", "rwlock.tla"],
            capture_output=True, text=True, cwd=SPEC_DIR, timeout=60
        )
        output = result.stdout + result.stderr
        assert "*** Errors" not in output, f"SANY reported errors:\n{output}"
        assert "***Parse Error***" not in output, f"SANY parse error:\n{output}"
        assert "Semantic processing of module rwlock" in output, \
            f"SANY did not complete semantic processing:\n{output}"

    def test_nil_is_constant(self):
        """Nil must be a CONSTANT, not via unbounded CHOOSE."""
        with open(os.path.join(SPEC_DIR, "rwlock.tla")) as f:
            spec = f.read()
        assert "CHOOSE v : v" not in spec, \
            "Spec still contains unbounded CHOOSE for Nil"
        constants_match = re.search(
            r"CONSTANTS?\s+(.+?)(?:\n\n|\nVARIABLES)", spec, re.DOTALL
        )
        assert constants_match is not None, "No CONSTANTS declaration found"
        assert "Nil" in constants_match.group(1), \
            f"Nil not in CONSTANTS: {constants_match.group(1)}"

    def test_stubs_implemented(self):
        """UpgradeToWrite and CompleteUpgrade must not have FALSE placeholders."""
        with open(os.path.join(SPEC_DIR, "rwlock.tla")) as f:
            spec = f.read()
        for action in ["UpgradeToWrite", "CompleteUpgrade"]:
            pattern = rf"{action}\(n\)\s*==\s*\n\s*/\\ FALSE"
            assert not re.search(pattern, spec), \
                f"{action} still contains /\\ FALSE stub — must be implemented"

    def test_upgrade_safety_nontrivial(self):
        """UpgradeSafety must be a substantive invariant, not trivially TRUE."""
        with open(os.path.join(SPEC_DIR, "rwlock.tla")) as f:
            spec = f.read()
        assert not re.search(r"UpgradeSafety\s*==\s*\n?\s*TRUE", spec), \
            "UpgradeSafety is still the trivial TRUE stub"
        idx = spec.find("UpgradeSafety ==")
        assert idx != -1, "Could not find UpgradeSafety definition"
        defn_text = spec[idx:idx + 300]
        assert "upgrader" in defn_text, \
            "UpgradeSafety should reference the 'upgrader' variable"

    def test_config_correct(self):
        """Config must have correct SPECIFICATION, bind Nil, declare all invariants."""
        with open(os.path.join(SPEC_DIR, "rwlock.cfg")) as f:
            config = f.read()
        spec_match = re.search(r"SPECIFICATION\s+(\w+)", config)
        assert spec_match is not None, "No SPECIFICATION in config"
        assert spec_match.group(1) == "Specification", \
            f"SPECIFICATION is '{spec_match.group(1)}', expected 'Specification'"
        assert re.search(r"Nil\s*=", config), "Config does not bind Nil"
        for inv in ["NoReadWriteConflict", "SingleWriter", "QueueIntegrity",
                     "UpgradeSafety", "WriterTracking"]:
            assert inv in config, f"Config missing invariant: {inv}"

    def test_tlc_verifies(self):
        """TLC must complete with no errors, violations, or deadlocks."""
        result = subprocess.run(
            ["java", "-cp", TLA_TOOLS, "tlc2.TLC",
             "-config", "rwlock.cfg",
             "-workers", "1",
             "rwlock.tla"],
            capture_output=True, text=True, cwd=SPEC_DIR, timeout=240
        )
        output = result.stdout + result.stderr
        assert "Model checking completed. No error has been found." in output, \
            f"TLC did not complete successfully:\n{output[-3000:]}"
        assert "is violated" not in output, \
            f"Invariant violation detected:\n{output[-3000:]}"
        assert "Deadlock reached" not in output, \
            f"Deadlock reached:\n{output[-3000:]}"
        assert "TLC threw an unexpected exception" not in output, \
            f"TLC exception:\n{output[-3000:]}"
