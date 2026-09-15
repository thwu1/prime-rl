
import os


def read_build_results():
    results = {}
    with open("/tmp/build_results.txt") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                results[key] = val
    return results


class TestCoqVerifiedCompiler:
    """Verify that the Coq verified-compiler project is correctly fixed."""

    def test_project_builds(self):
        """All Coq source files compile successfully via coqc."""
        results = read_build_results()
        assert results["BUILD_OK"] == "1", "Coq project failed to build"

    def test_verification_passes(self):
        """Independent verification file compiles, confirming correct computation."""
        results = read_build_results()
        assert results["VERIFY_OK"] == "1", (
            "Independent verification tests failed to compile"
        )

    def test_no_admitted(self):
        """No Admitted proofs remain in core source files."""
        results = read_build_results()
        count = int(results["ADMITTED_COUNT"])
        assert count == 0, f"Found {count} Admitted proof(s) in source files"

    def test_no_unauthorized_axioms(self):
        """No Axiom/Parameter/Conjecture declarations added to source files."""
        results = read_build_results()
        count = int(results["AXIOM_COUNT"])
        assert count == 0, f"Found {count} unauthorized axiom(s)"

    def test_vo_files_exist(self):
        """All compiled .vo files were generated."""
        expected = [
            "Syntax.vo",
            "Semantics.vo",
            "StackMachine.vo",
            "Compiler.vo",
            "Optimizer.vo",
            "Tests.vo",
        ]
        missing = []
        for vo in expected:
            if not os.path.exists(os.path.join("/app", vo)):
                missing.append(vo)
        assert not missing, f"Missing compiled files: {missing}"

    def test_verify_vo_exists(self):
        """The independent verification file was compiled."""
        assert os.path.exists("/app/Verify.vo"), "Verify.vo was not generated"
