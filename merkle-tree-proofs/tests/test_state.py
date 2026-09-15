
import subprocess
import os
import re


def test_file_exists():
    """MerkleTree.v must exist at /app/MerkleTree.v."""
    assert os.path.isfile("/app/MerkleTree.v"), "MerkleTree.v not found at /app/"


def test_no_admitted():
    """The file must contain zero occurrences of the Admitted command."""
    with open("/app/MerkleTree.v") as f:
        content = f.read()
    # Strip Coq comments before checking
    cleaned = re.sub(r"\(\*.*?\*\)", "", content, flags=re.DOTALL)
    matches = re.findall(r"\bAdmitted\b", cleaned)
    assert len(matches) == 0, (
        f"Found {len(matches)} occurrence(s) of 'Admitted' — all proofs must be completed"
    )


def test_no_admit_tactic():
    """The file must not use the admit tactic (outside comments)."""
    with open("/app/MerkleTree.v") as f:
        content = f.read()
    # Strip Coq comments (handles non-nested (* ... *))
    cleaned = re.sub(r"\(\*.*?\*\)", "", content, flags=re.DOTALL)
    assert not re.search(
        r"\badmit\b", cleaned
    ), "Found 'admit' tactic usage outside comments"


def test_compiles():
    """The file must compile successfully with coqc."""
    result = subprocess.run(
        ["coqc", "MerkleTree.v"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"coqc failed with:\n{result.stderr}"


def test_theorems_present():
    """All five required theorems must be declared."""
    with open("/app/MerkleTree.v") as f:
        content = f.read()
    required = [
        "completeness",
        "binding",
        "gen_proof_extracts_leaf",
        "update_soundness",
        "gen_proof_path_length",
    ]
    for thm in required:
        pattern = rf"Theorem\s+{thm}\b"
        assert re.search(pattern, content), f"Required theorem '{thm}' not found"


def test_definitions_intact():
    """Core definitions and axioms must not be removed or renamed."""
    with open("/app/MerkleTree.v") as f:
        content = f.read()
    required = [
        "Parameter hash",
        "Axiom hash_inj",
        "Inductive tree",
        "Fixpoint root",
        "Fixpoint reconstruct",
        "Definition verify",
        "Fixpoint gen_proof",
        "Fixpoint set_leaf",
        "Fixpoint get_leaf",
        "Fixpoint leaf_depth",
        "Fixpoint num_leaves",
        "Inductive dir",
    ]
    for defn in required:
        assert defn in content, f"Core definition '{defn}' is missing or altered"


def test_no_extra_axioms():
    """No axioms beyond hash_inj should be introduced."""
    with open("/app/MerkleTree.v") as f:
        content = f.read()
    # Strip comments
    cleaned = re.sub(r"\(\*.*?\*\)", "", content, flags=re.DOTALL)
    axiom_count = len(re.findall(r"\bAxiom\b", cleaned))
    assert axiom_count == 1, (
        f"Expected exactly 1 Axiom (hash_inj), found {axiom_count}"
    )
    param_count = len(re.findall(r"\bParameter\b", cleaned))
    assert param_count == 1, (
        f"Expected exactly 1 Parameter (hash), found {param_count}"
    )


def test_theorem_signatures():
    """Theorem signatures must match the originals."""
    with open("/app/MerkleTree.v") as f:
        content = f.read()
    # Check key fragments of each theorem's type signature
    sig_fragments = [
        ("completeness", "gen_proof t i = Some (v, p)"),
        ("completeness", "verify v p (root t) = true"),
        ("binding", "verify v1 p r = true"),
        ("binding", "verify v2 p r = true"),
        ("binding", "v1 = v2"),
        ("gen_proof_extracts_leaf", "get_leaf t i = Some v"),
        ("update_soundness", "root (set_leaf t i new_val)"),
        ("gen_proof_path_length", "leaf_depth t i = Some (length p)"),
    ]
    for thm_name, fragment in sig_fragments:
        assert fragment in content, (
            f"Theorem '{thm_name}' signature fragment missing: '{fragment}'"
        )
