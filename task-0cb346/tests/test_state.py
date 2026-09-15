"""
Tests for kernel specification security audit task.

Verifies that:
1. /app/audit.json correctly classifies all specifications as SOUND or VULNERABLE
2. Violated invariants are correctly identified for each vulnerable specification
3. Counterexamples are valid (re-verified with Z3)
4. /app/specs_fixed.py contains correct minimal fixes verified by Z3

"""

import json
import os
import sys
import importlib.util
import pytest

# Ground truth: which specs are vulnerable and which invariant each violates
EXPECTED_VULNERABLE = {
    "spec_map_page_desc": ["S1"],
    "spec_free_frame": ["S2"],
    "spec_protect_frame": ["S3"],
    "spec_copy_frame": ["S2"],
}
EXPECTED_SOUND = {"spec_alloc_frame", "spec_map_pci_page"}
ALL_SPECS = set(EXPECTED_VULNERABLE.keys()) | EXPECTED_SOUND

AUDIT_PATH = "/app/audit.json"
FIXED_PATH = "/app/specs_fixed.py"


def load_audit():
    with open(AUDIT_PATH) as f:
        return json.load(f)


def parse_int_flexible(s):
    """Parse integer from string, handling decimal and hex formats."""
    s = str(s).strip()
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    if s.startswith("#x"):
        return int(s[2:], 16)
    return int(s)


def _setup_z3():
    """Add /app to path and import Z3 modules."""
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
    import z3
    from kernel_model import KernelState, bv
    return z3, KernelState, bv


def _import_fixed_specs():
    """Import specs_fixed.py from /app/ via importlib."""
    spec = importlib.util.spec_from_file_location("specs_fixed", FIXED_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ================================================================
# Structure tests
# ================================================================

def test_audit_exists():
    assert os.path.exists(AUDIT_PATH), \
        f"audit.json not found at {AUDIT_PATH}"


def test_audit_valid_json():
    data = load_audit()
    assert isinstance(data, dict), "audit.json must be a JSON object"


def test_all_specs_present():
    data = load_audit()
    for spec_name in ALL_SPECS:
        assert spec_name in data, f"Missing specification {spec_name} in audit"


def test_result_format():
    data = load_audit()
    for spec_name in ALL_SPECS:
        if spec_name not in data:
            continue
        entry = data[spec_name]
        assert "status" in entry, \
            f"{spec_name} missing 'status' field"
        assert entry["status"] in ("SOUND", "VULNERABLE"), \
            f"{spec_name} status must be 'SOUND' or 'VULNERABLE', " \
            f"got '{entry['status']}'"
        if entry["status"] == "VULNERABLE":
            assert "violations" in entry, \
                f"{spec_name} is VULNERABLE but missing 'violations'"
            assert isinstance(entry["violations"], list) and len(entry["violations"]) > 0, \
                f"{spec_name} violations must be a non-empty list"
            for v in entry["violations"]:
                assert "invariant" in v, \
                    f"{spec_name} violation missing 'invariant' field"
                assert "counterexample" in v, \
                    f"{spec_name} violation missing 'counterexample' field"
                assert isinstance(v["counterexample"], dict) and len(v["counterexample"]) > 0, \
                    f"{spec_name} counterexample must be a non-empty dict"


# ================================================================
# Classification tests
# ================================================================

def test_vulnerable_specs():
    """Exactly the right set of specs must be classified as VULNERABLE."""
    data = load_audit()
    actual_vulnerable = {name for name, entry in data.items()
                         if name in ALL_SPECS and entry.get("status") == "VULNERABLE"}
    expected = set(EXPECTED_VULNERABLE.keys())
    assert actual_vulnerable == expected, \
        f"Vulnerable specs: expected {expected}, got {actual_vulnerable}"


def test_sound_specs():
    """Exactly the right set of specs must be classified as SOUND."""
    data = load_audit()
    actual_sound = {name for name, entry in data.items()
                    if name in ALL_SPECS and entry.get("status") == "SOUND"}
    assert actual_sound == EXPECTED_SOUND, \
        f"Sound specs: expected {EXPECTED_SOUND}, got {actual_sound}"


def test_violation_invariants():
    """Each vulnerable spec must report the correct violated invariant."""
    data = load_audit()
    for spec_name, expected_invs in EXPECTED_VULNERABLE.items():
        entry = data[spec_name]
        actual_invs = {v["invariant"] for v in entry["violations"]}
        for inv in expected_invs:
            assert inv in actual_invs, \
                f"{spec_name}: expected invariant {inv} in violations, got {actual_invs}"


# ================================================================
# Counterexample value tests
# ================================================================

def test_counterexample_s1_bounds():
    """S1 counterexample for map_page_desc: n must be exactly 64 (off-by-one)."""
    data = load_audit()
    violations = data["spec_map_page_desc"]["violations"]
    s1 = [v for v in violations if v["invariant"] == "S1"]
    assert len(s1) >= 1, "Missing S1 violation for spec_map_page_desc"
    ce = s1[0]["counterexample"]
    n_val = parse_int_flexible(ce.get("n", ce.get("N", "-1")))
    # ULT(n, 65) AND NOT(ULT(n, 64)) => n == 64 exactly
    assert n_val == 64, \
        f"S1 counterexample n={n_val} should be 64 (the off-by-one boundary)"


def test_counterexample_s3_index():
    """S3 counterexample for protect_frame: index must be >= 512."""
    data = load_audit()
    violations = data["spec_protect_frame"]["violations"]
    s3 = [v for v in violations if v["invariant"] == "S3"]
    assert len(s3) >= 1, "Missing S3 violation for spec_protect_frame"
    ce = s3[0]["counterexample"]
    idx_val = parse_int_flexible(ce.get("index", ce.get("Index", "-1")))
    assert idx_val >= 512, \
        f"S3 counterexample index={idx_val} should be >= 512"


# ================================================================
# Z3-based counterexample re-verification
# ================================================================

def test_counterexample_s2_free_z3():
    """Re-verify S2 counterexample for free_frame: to_pn not owned by current."""
    z3mod, KernelState, bv_fn = _setup_z3()
    from specs import spec_free_frame

    data = load_audit()
    violations = data["spec_free_frame"]["violations"]
    s2 = [v for v in violations if v["invariant"] == "S2"]
    assert len(s2) >= 1, "Missing S2 violation for spec_free_frame"
    ce = s2[0]["counterexample"]

    from_pn_val = parse_int_flexible(ce.get("from_pn", "-1"))
    index_val = parse_int_flexible(ce.get("index", "-1"))
    to_pn_val = parse_int_flexible(ce.get("to_pn", "-1"))

    state = KernelState("rvf_")
    precond, _ = spec_free_frame(state,
                                  bv_fn(from_pn_val),
                                  bv_fn(index_val),
                                  bv_fn(to_pn_val))
    prop = z3mod.Select(state.page_owner, bv_fn(to_pn_val)) == state.current

    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(prop))
    result = solver.check()
    assert result == z3mod.sat, \
        "S2 counterexample for free_frame doesn't demonstrate ownership violation"


def test_counterexample_s2_copy_z3():
    """Re-verify S2 counterexample for copy_frame: from_pn not owned by current."""
    z3mod, KernelState, bv_fn = _setup_z3()
    from specs import spec_copy_frame

    data = load_audit()
    violations = data["spec_copy_frame"]["violations"]
    s2 = [v for v in violations if v["invariant"] == "S2"]
    assert len(s2) >= 1, "Missing S2 violation for spec_copy_frame"
    ce = s2[0]["counterexample"]

    from_pn_val = parse_int_flexible(ce.get("from_pn", "-1"))
    pid_val = parse_int_flexible(ce.get("pid", "-1"))
    to_pn_val = parse_int_flexible(ce.get("to_pn", "-1"))

    state = KernelState("rvc_")
    precond, _ = spec_copy_frame(state,
                                  bv_fn(from_pn_val),
                                  bv_fn(pid_val),
                                  bv_fn(to_pn_val))
    prop = z3mod.Select(state.page_owner, bv_fn(from_pn_val)) == state.current

    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(prop))
    result = solver.check()
    assert result == z3mod.sat, \
        "S2 counterexample for copy_frame doesn't demonstrate source ownership violation"


# ================================================================
# Fixed specifications tests
# ================================================================

def test_fixed_specs_exist():
    assert os.path.exists(FIXED_PATH), \
        f"specs_fixed.py not found at {FIXED_PATH}"


def test_fixed_specs_importable():
    mod = _import_fixed_specs()
    for fn_name in ["spec_alloc_frame", "spec_map_page_desc", "spec_free_frame",
                     "spec_protect_frame", "spec_map_pci_page", "spec_copy_frame"]:
        assert hasattr(mod, fn_name), \
            f"specs_fixed.py missing function {fn_name}"


def test_fixed_s1_holds():
    """Fixed spec_map_page_desc must satisfy S1 (bounds safety)."""
    z3mod, KernelState, bv_fn = _setup_z3()
    from kernel_model import NPAGES_PAGE_DESC_TABLE
    mod = _import_fixed_specs()

    state = KernelState("fs1_")
    pid = z3mod.BitVec("fs1_pid", 64)
    from_pn = z3mod.BitVec("fs1_from", 64)
    index = z3mod.BitVec("fs1_idx", 64)
    n = z3mod.BitVec("fs1_n", 64)
    perm = z3mod.BitVec("fs1_perm", 64)

    precond, _ = mod.spec_map_page_desc(state, pid, from_pn, index, n, perm)
    prop = z3mod.ULT(n, bv_fn(NPAGES_PAGE_DESC_TABLE))

    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(prop))
    result = solver.check()
    assert result == z3mod.unsat, \
        "Fixed spec_map_page_desc still violates S1 (bounds safety)"


def test_fixed_s2_free_holds():
    """Fixed spec_free_frame must satisfy S2 (to_pn ownership)."""
    z3mod, KernelState, bv_fn = _setup_z3()
    mod = _import_fixed_specs()

    state = KernelState("fs2f_")
    from_pn = z3mod.BitVec("fs2f_from", 64)
    index = z3mod.BitVec("fs2f_idx", 64)
    to_pn = z3mod.BitVec("fs2f_to", 64)

    precond, _ = mod.spec_free_frame(state, from_pn, index, to_pn)
    prop = z3mod.Select(state.page_owner, to_pn) == state.current

    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(prop))
    result = solver.check()
    assert result == z3mod.unsat, \
        "Fixed spec_free_frame still violates S2 (to_pn ownership)"


def test_fixed_s3_holds():
    """Fixed spec_protect_frame must satisfy S3 (index validity)."""
    z3mod, KernelState, bv_fn = _setup_z3()
    from kernel_model import is_page_index_valid
    mod = _import_fixed_specs()

    state = KernelState("fs3_")
    pt = z3mod.BitVec("fs3_pt", 64)
    index = z3mod.BitVec("fs3_idx", 64)
    frame = z3mod.BitVec("fs3_frame", 64)
    perm = z3mod.BitVec("fs3_perm", 64)

    precond, _ = mod.spec_protect_frame(state, pt, index, frame, perm)
    prop = is_page_index_valid(index)

    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(prop))
    result = solver.check()
    assert result == z3mod.unsat, \
        "Fixed spec_protect_frame still violates S3 (index validity)"


def test_fixed_s2_copy_holds():
    """Fixed spec_copy_frame must satisfy S2 (from_pn ownership)."""
    z3mod, KernelState, bv_fn = _setup_z3()
    mod = _import_fixed_specs()

    state = KernelState("fs2c_")
    from_pn = z3mod.BitVec("fs2c_from", 64)
    pid = z3mod.BitVec("fs2c_pid", 64)
    to_pn = z3mod.BitVec("fs2c_to", 64)

    precond, _ = mod.spec_copy_frame(state, from_pn, pid, to_pn)
    prop = z3mod.Select(state.page_owner, from_pn) == state.current

    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(prop))
    result = solver.check()
    assert result == z3mod.unsat, \
        "Fixed spec_copy_frame still violates S2 (from_pn ownership)"


def test_fixed_sound_specs_still_hold():
    """Sound specs must still satisfy all applicable invariants in specs_fixed.py."""
    z3mod, KernelState, bv_fn = _setup_z3()
    from kernel_model import NPAGES_DEVICES, is_page_index_valid, PTE_W
    mod = _import_fixed_specs()

    # S1 for map_pci_page: bounds check holds
    state = KernelState("ss_pci_")
    pid = z3mod.BitVec("ss_pci_pid", 64)
    from_pn = z3mod.BitVec("ss_pci_from", 64)
    index = z3mod.BitVec("ss_pci_idx", 64)
    n = z3mod.BitVec("ss_pci_n", 64)
    perm = z3mod.BitVec("ss_pci_perm", 64)
    precond, _ = mod.spec_map_pci_page(state, pid, from_pn, index, n, perm)
    solver = z3mod.Solver()
    solver.set("timeout", 30000)
    solver.add(precond)
    solver.add(z3mod.Not(z3mod.ULT(n, bv_fn(NPAGES_DEVICES))))
    assert solver.check() == z3mod.unsat, \
        "Fixed map_pci_page violates S1 (bounds)"

    # S3 for alloc_frame: index validity holds
    state2 = KernelState("ss_alloc_")
    pid2 = z3mod.BitVec("ss_alloc_pid", 64)
    from_pn2 = z3mod.BitVec("ss_alloc_from", 64)
    index2 = z3mod.BitVec("ss_alloc_idx", 64)
    to_pn2 = z3mod.BitVec("ss_alloc_to", 64)
    perm2 = z3mod.BitVec("ss_alloc_perm", 64)
    precond2, _ = mod.spec_alloc_frame(state2, pid2, from_pn2, index2, to_pn2, perm2)
    solver2 = z3mod.Solver()
    solver2.set("timeout", 30000)
    solver2.add(precond2)
    solver2.add(z3mod.Not(is_page_index_valid(index2)))
    assert solver2.check() == z3mod.unsat, \
        "Fixed alloc_frame violates S3 (index validity)"

    # S4 for map_page_desc: readonly holds
    state3 = KernelState("ss_mpd_")
    pid3 = z3mod.BitVec("ss_mpd_pid", 64)
    from_pn3 = z3mod.BitVec("ss_mpd_from", 64)
    index3 = z3mod.BitVec("ss_mpd_idx", 64)
    n3 = z3mod.BitVec("ss_mpd_n", 64)
    perm3 = z3mod.BitVec("ss_mpd_perm", 64)
    precond3, _ = mod.spec_map_page_desc(state3, pid3, from_pn3, index3, n3, perm3)
    solver3 = z3mod.Solver()
    solver3.set("timeout", 30000)
    solver3.add(precond3)
    solver3.add(z3mod.Not(perm3 & bv_fn(PTE_W) == bv_fn(0)))
    assert solver3.check() == z3mod.unsat, \
        "Fixed map_page_desc violates S4 (readonly)"
