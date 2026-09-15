
import subprocess
import re
import os


def test_coqc_compiles_successfully():
    """The file must compile with coqc without errors."""
    result = subprocess.run(
        ["coqc", "/app/MultiLimbArith.v"],
        capture_output=True,
        text=True,
        timeout=240
    )
    assert result.returncode == 0, (
        f"coqc failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_no_admitted_remains():
    """The file must not contain any Admitted declarations (outside comments)."""
    with open("/app/MultiLimbArith.v", "r") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip lines that are inside Coq comments
        if stripped.startswith("(*"):
            continue
        if re.search(r'\bAdmitted\b', stripped):
            assert False, (
                f"Found 'Admitted' on line {i+1}: {stripped}. "
                "All lemmas must be fully proved."
            )


def test_no_admit_tactic():
    """The file must not use the admit tactic."""
    with open("/app/MultiLimbArith.v", "r") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("(*"):
            continue
        if re.search(r'\badmit\b', stripped):
            assert False, (
                f"Found 'admit' tactic on line {i+1}: {stripped}. "
                "All proofs must be complete without admit."
            )


def test_no_axiom_added():
    """The file must not introduce new axioms."""
    with open("/app/MultiLimbArith.v", "r") as f:
        content = f.read()
    axiom_matches = re.findall(r'^\s*Axiom\b', content, re.MULTILINE)
    assert len(axiom_matches) == 0, (
        f"Found {len(axiom_matches)} Axiom declaration(s). No new axioms allowed."
    )


def test_definitions_unchanged():
    """Key definitions must not be modified."""
    with open("/app/MultiLimbArith.v", "r") as f:
        content = f.read()

    required_defs = [
        "Definition eval (p : list (Z * Z)) : Z :=",
        "Definition mul (p q : list (Z * Z)) : list (Z * Z) :=",
        "Definition split (s : Z) (p : list (Z * Z)) : list (Z * Z) * list (Z * Z) :=",
        "Definition reduce (s : Z) (c : list (Z * Z)) (p : list (Z * Z)) : list (Z * Z) :=",
        "Definition partition_val (n : nat) (x : Z) : list Z :=",
        "Definition uweight (lgr : Z) (i : nat) : Z := 2 ^ (lgr * Z.of_nat i).",
    ]
    for defn in required_defs:
        assert defn in content, (
            f"Required definition not found (may have been modified): {defn}"
        )


def test_lemma_signatures_intact():
    """Lemma type signatures must remain unchanged."""
    with open("/app/MultiLimbArith.v", "r") as f:
        content = f.read()

    required_lemmas = [
        "Lemma eval_split s p (s_nz : s <> 0)",
        "Lemma eval_reduce s c p (s_nz : s <> 0) (mod_nz : s - eval c <> 0)",
        "Lemma eval_partition n x",
        "Lemma partition_bounded n x i",
        "Lemma uweight_divides lgr (Hr : 0 < lgr) i",
        "Lemma uweight_sum lgr (Hr : 0 <= lgr) i j",
        "Lemma uweight_mod_mod lgr (Hr : 0 < lgr) x m n",
    ]
    for lem in required_lemmas:
        assert lem in content, (
            f"Required lemma signature not found (may have been modified): {lem}"
        )


def test_output_file_exists():
    """coqc must produce the .vo output file."""
    # First compile
    subprocess.run(
        ["coqc", "/app/MultiLimbArith.v"],
        capture_output=True,
        text=True,
        timeout=240
    )
    assert os.path.exists("/app/MultiLimbArith.vo"), (
        "Expected output file /app/MultiLimbArith.vo not found after compilation."
    )
