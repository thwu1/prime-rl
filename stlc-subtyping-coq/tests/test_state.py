
"""Tests for STLC+Subtyping Coq formalization."""

import subprocess
import os
import re

PROJECT_DIR = "/app/stlc_sub"

COQ_FILES = ["Types.v", "Subtyping.v", "Terms.v", "Typing.v", "Algorithmic.v"]


def run_cmd(cmd, cwd=PROJECT_DIR, timeout=240):
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


class TestCoqCompilation:
    """Test that the Coq project compiles successfully."""

    def test_all_source_files_exist(self):
        for f in COQ_FILES:
            path = os.path.join(PROJECT_DIR, f)
            assert os.path.isfile(path), f"Missing source file: {f}"

    def test_no_admitted_remains(self):
        """No Admitted. should remain in any source file."""
        for f in COQ_FILES:
            path = os.path.join(PROJECT_DIR, f)
            with open(path, "r") as fh:
                content = fh.read()
            assert "Admitted." not in content, (
                f"{f} still contains 'Admitted.'"
            )

    def test_no_fill_in_here_remains(self):
        """No FILL IN HERE markers should remain."""
        for f in COQ_FILES:
            path = os.path.join(PROJECT_DIR, f)
            with open(path, "r") as fh:
                content = fh.read()
            assert "FILL IN HERE" not in content, (
                f"{f} still contains 'FILL IN HERE'"
            )

    def test_make_succeeds(self):
        """Running make in the project directory must succeed."""
        run_cmd("make clean")
        rc, stdout, stderr = run_cmd("make")
        assert rc == 0, (
            f"make failed with exit code {rc}.\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )

    def test_vo_files_produced(self):
        """All .vo files should be produced after make."""
        run_cmd("make")
        for f in COQ_FILES:
            vo = f.replace(".v", ".vo")
            path = os.path.join(PROJECT_DIR, vo)
            assert os.path.isfile(path), f"Missing compiled file: {vo}"

    def test_typecheck_function_exists(self):
        """The typecheck function in Algorithmic.v must not be the placeholder."""
        path = os.path.join(PROJECT_DIR, "Algorithmic.v")
        with open(path, "r") as fh:
            content = fh.read()
        match = re.search(
            r"Fixpoint\s+typecheck.*?:=\s*(.*?)(?:\.\s*$|\.\s*(?:Lemma|Theorem|Definition|Fixpoint|End))",
            content,
            re.DOTALL | re.MULTILINE,
        )
        assert match is not None, "Could not find typecheck Fixpoint"
        body = match.group(1).strip()
        assert body != "None", (
            "typecheck is still the placeholder"
        )
        assert "match" in body, (
            "typecheck body does not contain 'match'"
        )

    def test_definitions_not_altered(self):
        """Key inductive definitions must not be altered."""
        path = os.path.join(PROJECT_DIR, "Types.v")
        with open(path, "r") as fh:
            content = fh.read()
        for constructor in ["Ty_Top", "Ty_Arrow", "Ty_Prod", "Ty_Unit"]:
            assert constructor in content, (
                f"Type constructor {constructor} missing from Types.v"
            )

        path2 = os.path.join(PROJECT_DIR, "Typing.v")
        with open(path2, "r") as fh:
            content2 = fh.read()
        for rule in ["T_Var", "T_Abs", "T_App", "T_Pair", "T_Fst",
                      "T_Snd", "T_Unit", "T_Sub"]:
            assert rule in content2, (
                f"Typing rule {rule} missing from Typing.v"
            )

    def test_subtyping_rules_intact(self):
        """Subtyping rules must not be altered."""
        path = os.path.join(PROJECT_DIR, "Subtyping.v")
        with open(path, "r") as fh:
            content = fh.read()
        for rule in ["S_Refl", "S_Top", "S_Arrow", "S_Prod"]:
            assert rule in content, (
                f"Subtyping rule {rule} missing from Subtyping.v"
            )
        # S_Trans should NOT be a constructor
        assert "| S_Trans" not in content, (
            "S_Trans should not be added as a constructor"
        )
