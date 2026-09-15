#!/usr/bin/env python3
"""
Kernel specification security audit tool.

Systematically checks all six syscall specifications against all applicable
security invariants (S1-S4), reports violations with Z3-generated
counterexamples, and produces corrected specifications.

"""

import json
import sys
import importlib.util

sys.path.insert(0, '/app')

import z3
from kernel_model import (
    KernelState, bv, is_page_index_valid,
    NPAGES_PAGE_DESC_TABLE, NPAGES_DEVICES,
    PAGE_TYPE_FREE, PAGE_TYPE_FRAME, PAGE_TYPE_X86_PT,
    PTE_W,
)
from specs import (
    spec_alloc_frame, spec_map_page_desc, spec_free_frame,
    spec_protect_frame, spec_map_pci_page, spec_copy_frame,
)


def extract_ce(model, arg_names, args):
    """Extract counterexample values from Z3 model as decimal strings."""
    ce = {}
    for name, var in zip(arg_names, args):
        val = model.eval(var, model_completion=True)
        if z3.is_bv_value(val):
            ce[name] = str(val.as_long())
        else:
            ce[name] = str(val)
    return ce


def check_invariant(spec_fn, state, args, arg_names, prop):
    """
    Check if spec_fn's precondition implies prop.
    Returns ("VIOLATED", counterexample_dict) or ("HOLDS", None).
    """
    precond, _ = spec_fn(state, *args)

    solver = z3.Solver()
    solver.set("timeout", 60000)
    solver.add(precond)
    solver.add(z3.Not(prop))

    result = solver.check()
    if result == z3.sat:
        ce = extract_ce(solver.model(), arg_names, args)
        return "VIOLATED", ce
    elif result == z3.unsat:
        return "HOLDS", None
    else:
        return "UNKNOWN", None


# ---- Argument constructors ----

def make_args_5(prefix):
    """Args for map_page_desc / map_pci_page: pid, from_pn, index, n, perm."""
    state = KernelState(f"{prefix}_s_")
    pid = z3.BitVec(f"{prefix}_pid", 64)
    from_pn = z3.BitVec(f"{prefix}_from_pn", 64)
    index = z3.BitVec(f"{prefix}_index", 64)
    n = z3.BitVec(f"{prefix}_n", 64)
    perm = z3.BitVec(f"{prefix}_perm", 64)
    return state, [pid, from_pn, index, n, perm], \
           ["pid", "from_pn", "index", "n", "perm"]


def make_args_free(prefix):
    """Args for free_frame: from_pn, index, to_pn."""
    state = KernelState(f"{prefix}_s_")
    from_pn = z3.BitVec(f"{prefix}_from_pn", 64)
    index = z3.BitVec(f"{prefix}_index", 64)
    to_pn = z3.BitVec(f"{prefix}_to_pn", 64)
    return state, [from_pn, index, to_pn], ["from_pn", "index", "to_pn"]


def make_args_protect(prefix):
    """Args for protect_frame: pt, index, frame, perm."""
    state = KernelState(f"{prefix}_s_")
    pt = z3.BitVec(f"{prefix}_pt", 64)
    index = z3.BitVec(f"{prefix}_index", 64)
    frame = z3.BitVec(f"{prefix}_frame", 64)
    perm = z3.BitVec(f"{prefix}_perm", 64)
    return state, [pt, index, frame, perm], ["pt", "index", "frame", "perm"]


def make_args_copy(prefix):
    """Args for copy_frame: from_pn, pid, to_pn."""
    state = KernelState(f"{prefix}_s_")
    from_pn = z3.BitVec(f"{prefix}_from_pn", 64)
    pid = z3.BitVec(f"{prefix}_pid", 64)
    to_pn = z3.BitVec(f"{prefix}_to_pn", 64)
    return state, [from_pn, pid, to_pn], ["from_pn", "pid", "to_pn"]


def make_args_alloc(prefix):
    """Args for alloc_frame: pid, from_pn, index, to_pn, perm."""
    state = KernelState(f"{prefix}_s_")
    pid = z3.BitVec(f"{prefix}_pid", 64)
    from_pn = z3.BitVec(f"{prefix}_from_pn", 64)
    index = z3.BitVec(f"{prefix}_index", 64)
    to_pn = z3.BitVec(f"{prefix}_to_pn", 64)
    perm = z3.BitVec(f"{prefix}_perm", 64)
    return state, [pid, from_pn, index, to_pn, perm], \
           ["pid", "from_pn", "index", "to_pn", "perm"]


def run_all_checks():
    """Run all applicable invariant checks across all specifications."""
    findings = {}

    # ---- spec_map_page_desc ----
    violations = []

    # S1: table offset n < NPAGES_PAGE_DESC_TABLE
    state, args, names = make_args_5("mpd_s1")
    _, _, _, n, _ = args
    result, ce = check_invariant(spec_map_page_desc, state, args, names,
                                  z3.ULT(n, bv(NPAGES_PAGE_DESC_TABLE)))
    if result == "VIOLATED":
        violations.append({"invariant": "S1", "counterexample": ce})
    print(f"  map_page_desc S1: {result}")

    # S3: index < 512
    state, args, names = make_args_5("mpd_s3")
    _, _, index, _, _ = args
    result, ce = check_invariant(spec_map_page_desc, state, args, names,
                                  is_page_index_valid(index))
    if result == "VIOLATED":
        violations.append({"invariant": "S3", "counterexample": ce})
    print(f"  map_page_desc S3: {result}")

    # S4: no write permission
    state, args, names = make_args_5("mpd_s4")
    _, _, _, _, perm = args
    result, ce = check_invariant(spec_map_page_desc, state, args, names,
                                  perm & bv(PTE_W) == bv(0))
    if result == "VIOLATED":
        violations.append({"invariant": "S4", "counterexample": ce})
    print(f"  map_page_desc S4: {result}")

    findings["spec_map_page_desc"] = {
        "status": "VULNERABLE" if violations else "SOUND",
        "violations": violations
    }

    # ---- spec_map_pci_page ----
    violations = []

    # S1: n < NPAGES_DEVICES
    state, args, names = make_args_5("mpp_s1")
    _, _, _, n, _ = args
    result, ce = check_invariant(spec_map_pci_page, state, args, names,
                                  z3.ULT(n, bv(NPAGES_DEVICES)))
    if result == "VIOLATED":
        violations.append({"invariant": "S1", "counterexample": ce})
    print(f"  map_pci_page S1: {result}")

    # S3: index < 512
    state, args, names = make_args_5("mpp_s3")
    _, _, index, _, _ = args
    result, ce = check_invariant(spec_map_pci_page, state, args, names,
                                  is_page_index_valid(index))
    if result == "VIOLATED":
        violations.append({"invariant": "S3", "counterexample": ce})
    print(f"  map_pci_page S3: {result}")

    # S4: no write permission
    state, args, names = make_args_5("mpp_s4")
    _, _, _, _, perm = args
    result, ce = check_invariant(spec_map_pci_page, state, args, names,
                                  perm & bv(PTE_W) == bv(0))
    if result == "VIOLATED":
        violations.append({"invariant": "S4", "counterexample": ce})
    print(f"  map_pci_page S4: {result}")

    findings["spec_map_pci_page"] = {
        "status": "VULNERABLE" if violations else "SOUND",
        "violations": violations
    }

    # ---- spec_free_frame ----
    violations = []

    # S2: to_pn owned by current
    state, args, names = make_args_free("ff_s2")
    _, _, to_pn = args
    result, ce = check_invariant(spec_free_frame, state, args, names,
                                  z3.Select(state.page_owner, to_pn) == state.current)
    if result == "VIOLATED":
        violations.append({"invariant": "S2", "counterexample": ce})
    print(f"  free_frame S2 (to_pn): {result}")

    # S3: index < 512
    state, args, names = make_args_free("ff_s3")
    _, index, _ = args
    result, ce = check_invariant(spec_free_frame, state, args, names,
                                  is_page_index_valid(index))
    if result == "VIOLATED":
        violations.append({"invariant": "S3", "counterexample": ce})
    print(f"  free_frame S3: {result}")

    findings["spec_free_frame"] = {
        "status": "VULNERABLE" if violations else "SOUND",
        "violations": violations
    }

    # ---- spec_protect_frame ----
    violations = []

    # S2: pt owned by current
    state, args, names = make_args_protect("pf_s2a")
    pt, _, _, _ = args
    result, ce = check_invariant(spec_protect_frame, state, args, names,
                                  z3.Select(state.page_owner, pt) == state.current)
    if result == "VIOLATED":
        violations.append({"invariant": "S2", "counterexample": ce})
    print(f"  protect_frame S2 (pt): {result}")

    # S2: frame owned by current
    state, args, names = make_args_protect("pf_s2b")
    _, _, frame, _ = args
    result, ce = check_invariant(spec_protect_frame, state, args, names,
                                  z3.Select(state.page_owner, frame) == state.current)
    if result == "VIOLATED":
        violations.append({"invariant": "S2", "counterexample": ce})
    print(f"  protect_frame S2 (frame): {result}")

    # S3: index < 512
    state, args, names = make_args_protect("pf_s3")
    _, index, _, _ = args
    result, ce = check_invariant(spec_protect_frame, state, args, names,
                                  is_page_index_valid(index))
    if result == "VIOLATED":
        violations.append({"invariant": "S3", "counterexample": ce})
    print(f"  protect_frame S3: {result}")

    findings["spec_protect_frame"] = {
        "status": "VULNERABLE" if violations else "SOUND",
        "violations": violations
    }

    # ---- spec_copy_frame ----
    violations = []

    # S2: from_pn owned by current (source ownership)
    state, args, names = make_args_copy("cf_s2")
    from_pn, _, _ = args
    result, ce = check_invariant(spec_copy_frame, state, args, names,
                                  z3.Select(state.page_owner, from_pn) == state.current)
    if result == "VIOLATED":
        violations.append({"invariant": "S2", "counterexample": ce})
    print(f"  copy_frame S2 (from_pn): {result}")

    findings["spec_copy_frame"] = {
        "status": "VULNERABLE" if violations else "SOUND",
        "violations": violations
    }

    # ---- spec_alloc_frame ----
    violations = []

    # S2: from_pn owned by pid
    state, args, names = make_args_alloc("af_s2")
    pid, from_pn, _, _, _ = args
    result, ce = check_invariant(spec_alloc_frame, state, args, names,
                                  z3.Select(state.page_owner, from_pn) == pid)
    if result == "VIOLATED":
        violations.append({"invariant": "S2", "counterexample": ce})
    print(f"  alloc_frame S2 (from_pn): {result}")

    # S3: index < 512
    state, args, names = make_args_alloc("af_s3")
    _, _, index, _, _ = args
    result, ce = check_invariant(spec_alloc_frame, state, args, names,
                                  is_page_index_valid(index))
    if result == "VIOLATED":
        violations.append({"invariant": "S3", "counterexample": ce})
    print(f"  alloc_frame S3: {result}")

    findings["spec_alloc_frame"] = {
        "status": "VULNERABLE" if violations else "SOUND",
        "violations": violations
    }

    return findings


def generate_fixed_specs():
    """Apply minimal targeted fixes to specs.py and write specs_fixed.py."""
    with open('/app/specs.py') as f:
        content = f.read()

    # Fix 1: map_page_desc bounds check off-by-one
    # ULT(n, NPAGES_PAGE_DESC_TABLE + 1) allows n=64 which is out of bounds
    content = content.replace(
        'z3.ULT(n, bv(NPAGES_PAGE_DESC_TABLE + 1))',
        'z3.ULT(n, bv(NPAGES_PAGE_DESC_TABLE))'
    )

    # Fix 2: free_frame duplicate from_pn ownership check
    # Second occurrence checks from_pn again instead of to_pn
    content = content.replace(
        'z3.Select(state.page_type, to_pn) == bv(PAGE_TYPE_FRAME),\n        z3.Select(state.page_owner, from_pn) == state.current,',
        'z3.Select(state.page_type, to_pn) == bv(PAGE_TYPE_FRAME),\n        z3.Select(state.page_owner, to_pn) == state.current,'
    )

    # Fix 3: protect_frame missing index validity check
    content = content.replace(
        'z3.Select(state.page_owner, pt) == state.current,\n        is_pn_valid(frame),',
        'z3.Select(state.page_owner, pt) == state.current,\n        is_page_index_valid(index),\n        is_pn_valid(frame),'
    )

    # Fix 4: copy_frame wrong operand in source ownership check
    # Checks to_pn owner instead of from_pn owner
    content = content.replace(
        'z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_FRAME),\n        z3.Select(state.page_owner, to_pn) == state.current,',
        'z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_FRAME),\n        z3.Select(state.page_owner, from_pn) == state.current,'
    )

    with open('/app/specs_fixed.py', 'w') as f:
        f.write(content)

    print("specs_fixed.py written")


def verify_fixes():
    """Verify that all previously-violated invariants now hold on fixed specs."""
    spec_mod = importlib.util.spec_from_file_location("specs_fixed", "/app/specs_fixed.py")
    sfixed = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(sfixed)

    verifications = [
        ("map_page_desc S1", sfixed.spec_map_page_desc, make_args_5,
         lambda s, a: z3.ULT(a[3], bv(NPAGES_PAGE_DESC_TABLE))),
        ("free_frame S2", sfixed.spec_free_frame, make_args_free,
         lambda s, a: z3.Select(s.page_owner, a[2]) == s.current),
        ("protect_frame S3", sfixed.spec_protect_frame, make_args_protect,
         lambda s, a: is_page_index_valid(a[1])),
        ("copy_frame S2", sfixed.spec_copy_frame, make_args_copy,
         lambda s, a: z3.Select(s.page_owner, a[0]) == s.current),
    ]

    all_fixed = True
    for name, spec_fn, args_fn, prop_fn in verifications:
        state, args, _ = args_fn(f"vfy_{name.replace(' ', '_')}")
        precond, _ = spec_fn(state, *args)
        prop = prop_fn(state, args)

        solver = z3.Solver()
        solver.set("timeout", 30000)
        solver.add(precond)
        solver.add(z3.Not(prop))

        result = solver.check()
        status = "FIXED" if result == z3.unsat else "STILL VIOLATED"
        print(f"  {name}: {status}")
        if result != z3.unsat:
            all_fixed = False

    return all_fixed


def main():
    print("=" * 60)
    print("Kernel Specification Security Audit")
    print("=" * 60)

    print("\nPhase 1: Checking invariants...")
    findings = run_all_checks()

    n_vuln = sum(1 for v in findings.values() if v["status"] == "VULNERABLE")
    n_sound = sum(1 for v in findings.values() if v["status"] == "SOUND")
    print(f"\nSummary: {n_vuln} vulnerable, {n_sound} sound")

    with open('/app/audit.json', 'w') as f:
        json.dump(findings, f, indent=2)
    print("Audit report written to /app/audit.json")

    print("\nPhase 2: Generating fixed specifications...")
    generate_fixed_specs()

    print("\nPhase 3: Verifying fixes...")
    all_ok = verify_fixes()

    if all_ok:
        print("\nAll fixes verified successfully.")
    else:
        print("\nSome fixes failed verification!")
        sys.exit(1)


if __name__ == "__main__":
    main()
