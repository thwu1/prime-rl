
"""Tests for MultiLimbArith.v — verify that all Admitted lemmas are proved
and the file compiles cleanly with coqc."""

import subprocess
import re
import os
import pytest


COQ_FILE = "/app/MultiLimbArith.v"

REQUIRED_LEMMAS = [
    "eval_mul",
    "eval_negate_snd",
    "eval_map_scale",
    "eval_carry",
    "eval_rev",
    "eval_snoc",
    "eval_part",
    "eval_add_lists",
    "uweight_0",
    "uweight_S",
    "uweight_mul",
    "uweight_sum",
]


def read_source():
    with open(COQ_FILE, "r") as f:
        return f.read()


def strip_comments(source):
    """Remove Coq block comments (* ... *) — handles nesting."""
    result = []
    i = 0
    depth = 0
    while i < len(source):
        if source[i:i+2] == "(*":
            depth += 1
            i += 2
        elif source[i:i+2] == "*)" and depth > 0:
            depth -= 1
            i += 2
        elif depth == 0:
            result.append(source[i])
            i += 1
        else:
            i += 1
    return "".join(result)


class TestCoqCompilation:
    """Test that the Coq file compiles without errors."""

    def test_file_exists(self):
        assert os.path.isfile(COQ_FILE), f"{COQ_FILE} does not exist"

    def test_coqc_compiles(self):
        """coqc must accept the file with exit code 0."""
        result = subprocess.run(
            ["coqc", "-Q", "/app", "", COQ_FILE],
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert result.returncode == 0, (
            f"coqc failed with exit code {result.returncode}.\n"
            f"STDOUT:\n{result.stdout[:2000]}\n"
            f"STDERR:\n{result.stderr[:2000]}"
        )

    def test_no_admitted(self):
        """The source must contain zero occurrences of Admitted outside comments."""
        source = read_source()
        clean = strip_comments(source)
        admitted = re.findall(r'\bAdmitted\b', clean)
        assert len(admitted) == 0, (
            f"Found {len(admitted)} remaining Admitted in non-comment code"
        )


class TestLemmaPresence:
    """Verify that all required lemma statements are still present."""

    def test_all_lemmas_present(self):
        source = read_source()
        missing = []
        for lemma in REQUIRED_LEMMAS:
            pattern = rf'\bLemma\s+{re.escape(lemma)}\b'
            if not re.search(pattern, source):
                missing.append(lemma)
        assert len(missing) == 0, (
            f"Missing lemma declarations: {missing}"
        )


class TestModuleStructure:
    """Verify that the module structure is intact."""

    def test_assoc_module(self):
        source = read_source()
        assert re.search(r'\bModule\s+Assoc\b', source), "Module Assoc not found"
        assert re.search(r'\bEnd\s+Assoc\b', source), "End Assoc not found"

    def test_pos_module(self):
        source = read_source()
        assert re.search(r'\bModule\s+Pos\b', source), "Module Pos not found"
        assert re.search(r'\bEnd\s+Pos\b', source), "End Pos not found"

    def test_uweight_module(self):
        source = read_source()
        assert re.search(r'\bModule\s+UWeight\b', source), "Module UWeight not found"
        assert re.search(r'\bEnd\s+UWeight\b', source), "End UWeight not found"


class TestNoTrivialBypass:
    """Ensure proofs are not trivially bypassed."""

    def test_no_axiom(self):
        """No new axioms should be introduced."""
        source = read_source()
        clean = strip_comments(source)
        axiom_lines = re.findall(
            r'^\s*(Axiom|Parameter|Conjecture)\s+\w+',
            clean,
            re.MULTILINE,
        )
        assert len(axiom_lines) == 0, (
            f"Found axiom/parameter declarations:\n"
            + "\n".join(f"  {l.strip()}" for l in axiom_lines)
        )

    def test_no_admit_tactic(self):
        """No proofs should use the admit tactic."""
        source = read_source()
        clean = strip_comments(source)
        # 'admit' as a standalone tactic (not part of 'Admitted' which is caught above)
        admits = re.findall(r'\badmit\b', clean)
        assert len(admits) == 0, (
            f"Found {len(admits)} uses of 'admit' tactic"
        )
