
import difflib
import importlib.util
import json
import os
import subprocess
import sys


def load_results():
    """Load the agent's results from /app/results.json."""
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}"
    )
    with open(results_path) as f:
        results = json.load(f)
    assert isinstance(results, list), "results.json must contain a JSON array"
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    return results


def load_targets():
    """Load the target ciphertexts from /app/targets.json."""
    with open("/app/targets.json") as f:
        data = json.load(f)
    return data["targets"]


def load_test_vectors():
    """Load the known plaintext/ciphertext pairs."""
    with open("/app/test_vectors.json") as f:
        return json.load(f)["test_vectors"]


def load_module(path, name):
    """Import a Python file as a module."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- Plaintext recovery tests ---

def test_results_file_exists():
    """Check that results.json exists and is valid JSON."""
    results = load_results()
    for i, r in enumerate(results):
        assert isinstance(r, str), f"Result {i} must be a string, got {type(r)}"
        assert len(r) == 16, (
            f"Result {i} must be 16 hex chars, got {len(r)} chars: '{r}'"
        )
        int(r, 16)  # Verify it's valid hex


def test_result_0_correct():
    """Verify plaintext 0 transforms to target 0."""
    results = load_results()
    targets = load_targets()
    out = subprocess.run(
        ["python3", "/app/runner.py", results[0]],
        capture_output=True, text=True, timeout=60
    )
    computed = out.stdout.strip()
    assert computed == targets[0], (
        f"transform({results[0]}) = {computed}, expected {targets[0]}"
    )


def test_result_1_correct():
    """Verify plaintext 1 transforms to target 1."""
    results = load_results()
    targets = load_targets()
    out = subprocess.run(
        ["python3", "/app/runner.py", results[1]],
        capture_output=True, text=True, timeout=60
    )
    computed = out.stdout.strip()
    assert computed == targets[1], (
        f"transform({results[1]}) = {computed}, expected {targets[1]}"
    )


def test_result_2_correct():
    """Verify plaintext 2 transforms to target 2."""
    results = load_results()
    targets = load_targets()
    out = subprocess.run(
        ["python3", "/app/runner.py", results[2]],
        capture_output=True, text=True, timeout=60
    )
    computed = out.stdout.strip()
    assert computed == targets[2], (
        f"transform({results[2]}) = {computed}, expected {targets[2]}"
    )


def test_result_3_correct():
    """Verify plaintext 3 transforms to target 3."""
    results = load_results()
    targets = load_targets()
    out = subprocess.run(
        ["python3", "/app/runner.py", results[3]],
        capture_output=True, text=True, timeout=60
    )
    computed = out.stdout.strip()
    assert computed == targets[3], (
        f"transform({results[3]}) = {computed}, expected {targets[3]}"
    )


def test_result_4_correct():
    """Verify plaintext 4 transforms to target 4."""
    results = load_results()
    targets = load_targets()
    out = subprocess.run(
        ["python3", "/app/runner.py", results[4]],
        capture_output=True, text=True, timeout=60
    )
    computed = out.stdout.strip()
    assert computed == targets[4], (
        f"transform({results[4]}) = {computed}, expected {targets[4]}"
    )


def test_all_results_are_distinct():
    """Verify all 5 recovered plaintexts are distinct."""
    results = load_results()
    assert len(set(results)) == 5, (
        f"Expected 5 distinct plaintexts, got {len(set(results))} distinct values"
    )


# --- Fixed candidate tests ---

def test_fixed_a_exists():
    """Check that fixed_a.py exists."""
    assert os.path.exists("/app/candidates/fixed_a.py"), (
        "fixed_a.py not found at /app/candidates/fixed_a.py"
    )


def test_fixed_b_exists():
    """Check that fixed_b.py exists."""
    assert os.path.exists("/app/candidates/fixed_b.py"), (
        "fixed_b.py not found at /app/candidates/fixed_b.py"
    )


def test_fixed_c_exists():
    """Check that fixed_c.py exists."""
    assert os.path.exists("/app/candidates/fixed_c.py"), (
        "fixed_c.py not found at /app/candidates/fixed_c.py"
    )


def test_fixed_a_decrypts_correctly():
    """Verify fixed candidate A decrypts all test vectors correctly."""
    mod = load_module("/app/candidates/fixed_a.py", "fixed_a")
    tv = load_test_vectors()
    for v in tv:
        ct = int(v["ciphertext"], 16)
        pt_expected = int(v["plaintext"], 16)
        pt_actual = mod.decrypt(ct)
        assert pt_actual == pt_expected, (
            f"fixed_a: decrypt(0x{ct:016x}) = 0x{pt_actual:016x}, "
            f"expected 0x{pt_expected:016x}"
        )


def test_fixed_b_decrypts_correctly():
    """Verify fixed candidate B decrypts all test vectors correctly."""
    mod = load_module("/app/candidates/fixed_b.py", "fixed_b")
    tv = load_test_vectors()
    for v in tv:
        ct = int(v["ciphertext"], 16)
        pt_expected = int(v["plaintext"], 16)
        pt_actual = mod.decrypt(ct)
        assert pt_actual == pt_expected, (
            f"fixed_b: decrypt(0x{ct:016x}) = 0x{pt_actual:016x}, "
            f"expected 0x{pt_expected:016x}"
        )


def test_fixed_c_decrypts_correctly():
    """Verify fixed candidate C decrypts all test vectors correctly."""
    mod = load_module("/app/candidates/fixed_c.py", "fixed_c")
    tv = load_test_vectors()
    for v in tv:
        ct = int(v["ciphertext"], 16)
        pt_expected = int(v["plaintext"], 16)
        pt_actual = mod.decrypt(ct)
        assert pt_actual == pt_expected, (
            f"fixed_c: decrypt(0x{ct:016x}) = 0x{pt_actual:016x}, "
            f"expected 0x{pt_expected:016x}"
        )


def test_fix_a_is_minimal():
    """Verify fix A is a minimal correction, not a rewrite."""
    with open("/app/candidates/candidate_a.py") as f:
        original = f.read()
    with open("/app/candidates/fixed_a.py") as f:
        fixed = f.read()
    ratio = difflib.SequenceMatcher(None, original, fixed).ratio()
    assert ratio > 0.95, (
        f"Fix A should be a minimal correction (similarity {ratio:.3f} < 0.95)"
    )


def test_fix_b_is_minimal():
    """Verify fix B is a minimal correction, not a rewrite."""
    with open("/app/candidates/candidate_b.py") as f:
        original = f.read()
    with open("/app/candidates/fixed_b.py") as f:
        fixed = f.read()
    ratio = difflib.SequenceMatcher(None, original, fixed).ratio()
    assert ratio > 0.95, (
        f"Fix B should be a minimal correction (similarity {ratio:.3f} < 0.95)"
    )


def test_fix_c_is_minimal():
    """Verify fix C is a minimal correction, not a rewrite."""
    with open("/app/candidates/candidate_c.py") as f:
        original = f.read()
    with open("/app/candidates/fixed_c.py") as f:
        fixed = f.read()
    ratio = difflib.SequenceMatcher(None, original, fixed).ratio()
    assert ratio > 0.95, (
        f"Fix C should be a minimal correction (similarity {ratio:.3f} < 0.95)"
    )


# --- Known-plaintext attack tests ---

def test_kpa_attack_module_exists():
    """Check that kpa_attack.py exists and has required functions."""
    path = "/app/kpa_attack.py"
    assert os.path.exists(path), f"kpa_attack.py not found at {path}"
    mod = load_module(path, "kpa_attack")
    assert hasattr(mod, "recover_params"), (
        "kpa_attack.py must export a recover_params function"
    )
    assert hasattr(mod, "attack_decrypt"), (
        "kpa_attack.py must export an attack_decrypt function"
    )


def test_kpa_recover_with_vectors_01():
    """Use test vectors 0 and 1 to recover parameters, verify on held-out vector 2."""
    mod = load_module("/app/kpa_attack.py", "kpa_attack")
    tv = load_test_vectors()
    pairs = [
        (int(tv[0]["plaintext"], 16), int(tv[0]["ciphertext"], 16)),
        (int(tv[1]["plaintext"], 16), int(tv[1]["ciphertext"], 16)),
    ]
    A, B = mod.recover_params(pairs)
    assert isinstance(A, int), f"A must be an integer, got {type(A)}"
    assert isinstance(B, int), f"B must be an integer, got {type(B)}"
    # Verify on held-out vector 2 (not used for recovery)
    pt2 = int(tv[2]["plaintext"], 16)
    ct2 = int(tv[2]["ciphertext"], 16)
    predicted = mod.attack_decrypt(ct2, A, B)
    assert predicted == pt2, (
        f"KPA attack failed on held-out vector 2: "
        f"got 0x{predicted:016x}, expected 0x{pt2:016x}"
    )


def test_kpa_recover_with_vectors_12():
    """Use test vectors 1 and 2 to recover parameters, verify on held-out vector 0."""
    mod = load_module("/app/kpa_attack.py", "kpa_attack")
    tv = load_test_vectors()
    pairs = [
        (int(tv[1]["plaintext"], 16), int(tv[1]["ciphertext"], 16)),
        (int(tv[2]["plaintext"], 16), int(tv[2]["ciphertext"], 16)),
    ]
    A, B = mod.recover_params(pairs)
    # Verify on held-out vector 0
    pt0 = int(tv[0]["plaintext"], 16)
    ct0 = int(tv[0]["ciphertext"], 16)
    predicted = mod.attack_decrypt(ct0, A, B)
    assert predicted == pt0, (
        f"KPA attack failed on held-out vector 0: "
        f"got 0x{predicted:016x}, expected 0x{pt0:016x}"
    )


def test_kpa_recover_with_vectors_02():
    """Use test vectors 0 and 2 to recover parameters, verify on held-out vector 1."""
    mod = load_module("/app/kpa_attack.py", "kpa_attack")
    tv = load_test_vectors()
    pairs = [
        (int(tv[0]["plaintext"], 16), int(tv[0]["ciphertext"], 16)),
        (int(tv[2]["plaintext"], 16), int(tv[2]["ciphertext"], 16)),
    ]
    A, B = mod.recover_params(pairs)
    # Verify on held-out vector 1
    pt1 = int(tv[1]["plaintext"], 16)
    ct1 = int(tv[1]["ciphertext"], 16)
    predicted = mod.attack_decrypt(ct1, A, B)
    assert predicted == pt1, (
        f"KPA attack failed on held-out vector 1: "
        f"got 0x{predicted:016x}, expected 0x{pt1:016x}"
    )


def test_kpa_decrypts_all_targets():
    """Verify KPA attack decrypts all 5 targets consistently with results.json."""
    mod = load_module("/app/kpa_attack.py", "kpa_attack")
    tv = load_test_vectors()
    pairs = [
        (int(tv[0]["plaintext"], 16), int(tv[0]["ciphertext"], 16)),
        (int(tv[1]["plaintext"], 16), int(tv[1]["ciphertext"], 16)),
    ]
    A, B = mod.recover_params(pairs)
    targets = load_targets()
    results = load_results()
    for i, (ct_hex, pt_hex) in enumerate(zip(targets, results)):
        ct = int(ct_hex, 16)
        pt_expected = int(pt_hex, 16)
        pt_recovered = mod.attack_decrypt(ct, A, B)
        assert pt_recovered == pt_expected, (
            f"KPA target {i}: got 0x{pt_recovered:016x}, "
            f"expected 0x{pt_expected:016x}"
        )


def test_kpa_targets_verified_by_library():
    """Verify that KPA-decrypted targets actually transform to the target ciphertexts."""
    mod = load_module("/app/kpa_attack.py", "kpa_attack")
    tv = load_test_vectors()
    pairs = [
        (int(tv[0]["plaintext"], 16), int(tv[0]["ciphertext"], 16)),
        (int(tv[1]["plaintext"], 16), int(tv[1]["ciphertext"], 16)),
    ]
    A, B = mod.recover_params(pairs)
    targets = load_targets()
    for i, ct_hex in enumerate(targets):
        ct = int(ct_hex, 16)
        pt = mod.attack_decrypt(ct, A, B)
        pt_hex = f"{pt:016x}"
        out = subprocess.run(
            ["python3", "/app/runner.py", pt_hex],
            capture_output=True, text=True, timeout=60
        )
        computed = out.stdout.strip()
        assert computed == ct_hex, (
            f"KPA target {i}: transform({pt_hex}) = {computed}, "
            f"expected {ct_hex}"
        )


# --- Security assessment tests ---

def test_security_assessment_exists():
    """Check that security_assessment.md exists and has substantive content."""
    path = "/app/security_assessment.md"
    assert os.path.exists(path), f"Security assessment not found at {path}"
    with open(path) as f:
        content = f.read()
    assert len(content) >= 500, (
        f"Assessment is too short ({len(content)} chars, need >= 500)"
    )


def test_security_assessment_identifies_algebraic_structure():
    """Verify assessment identifies the core algebraic weakness."""
    with open("/app/security_assessment.md") as f:
        content = f.read().lower()
    has_structure = any(kw in content for kw in ["affine", "linear map", "linear over"])
    assert has_structure, (
        "Assessment must identify the affine or linear algebraic structure"
    )


def test_security_assessment_identifies_attack_class():
    """Verify assessment identifies the known-plaintext attack class."""
    with open("/app/security_assessment.md") as f:
        content = f.read().lower()
    has_attack = any(kw in content for kw in [
        "known-plaintext", "known plaintext", "kpa", "chosen-plaintext"
    ])
    assert has_attack, (
        "Assessment must identify the attack class (known-plaintext)"
    )


def test_security_assessment_identifies_field_context():
    """Verify assessment references the finite field context."""
    with open("/app/security_assessment.md") as f:
        content = f.read().lower()
    has_field = any(kw in content for kw in [
        "gf(", "galois", "finite field", "binary field", "gf(2"
    ])
    assert has_field, (
        "Assessment must reference the finite field algebraic context"
    )
