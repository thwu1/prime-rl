"""
Tests for Location-Routing Problem with MIP Depot Selection.

Verifies GLPK integration artifacts and solution correctness.
"""

import math
import os
import subprocess
import pytest


# ---------------------------------------------------------------------------
# GLPK Integration Tests
# ---------------------------------------------------------------------------


def test_model_complete():
    """Completed GMPL model exists with no TODO markers and required elements."""
    model_path = "/app/models/depot_selection.mod"
    assert os.path.isfile(model_path), (
        "Completed GMPL model not found at /app/models/depot_selection.mod"
    )

    with open(model_path) as f:
        content = f.read()

    assert "TODO" not in content, (
        "Model still contains TODO markers — all sections must be completed"
    )
    assert "depot_capacity" in content, (
        "Model missing depot capacity constraint (expected name 'depot_capacity')"
    )
    assert "fleet_limit" in content, (
        "Model missing fleet limit constraint (expected name 'fleet_limit')"
    )
    assert "printf" in content, (
        "Model missing printf output section"
    )
    assert "solve" in content, (
        "Model missing 'solve' directive"
    )


def test_data_files_exist():
    """GMPL data files exist for all instances with valid structure."""
    for idx in range(1, 4):
        path = f"/app/models/instance_{idx}.dat"
        assert os.path.isfile(path), f"GMPL data file missing: {path}"

        with open(path) as f:
            content = f.read()

        assert "data;" in content, (
            f"Data file {path} missing 'data;' header"
        )
        assert "set DEPOTS" in content, (
            f"Data file {path} missing DEPOTS set definition"
        )
        assert "set CUSTOMERS" in content, (
            f"Data file {path} missing CUSTOMERS set definition"
        )
        assert "param dist" in content, (
            f"Data file {path} missing distance parameter"
        )
        assert "param setup" in content, (
            f"Data file {path} missing setup cost parameter"
        )
        assert "end;" in content, (
            f"Data file {path} missing 'end;' terminator"
        )


def test_glpsol_logs_exist():
    """GLPK log files exist for all instances with non-trivial content."""
    for idx in range(1, 4):
        path = f"/app/logs/glpsol_instance_{idx}.log"
        assert os.path.isfile(path), f"GLPK log file missing: {path}"
        size = os.path.getsize(path)
        assert size > 50, (
            f"GLPK log {path} too small ({size} bytes) — "
            "does not appear to contain real glpsol output"
        )


def test_glpsol_model_solves():
    """Completed GMPL model solves successfully with glpsol for all instances."""
    model_path = "/app/models/depot_selection.mod"
    assert os.path.isfile(model_path), "GMPL model not found"

    for idx in range(1, 4):
        data_path = f"/app/models/instance_{idx}.dat"
        assert os.path.isfile(data_path), f"Data file not found: {data_path}"

        result = subprocess.run(
            ["glpsol", "--model", model_path, "--data", data_path,
             "--tmlim", "60"],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"glpsol failed for instance_{idx} (exit code {result.returncode}):\n"
            f"{result.stdout[-400:]}\n{result.stderr[-400:]}"
        )

        stdout = result.stdout
        has_depot = any(
            l.strip().startswith("DEPOT ")
            for l in stdout.split("\n")
        )
        has_assign = any(
            l.strip().startswith("ASSIGN ")
            for l in stdout.split("\n")
        )
        assert has_depot, (
            f"No DEPOT lines in glpsol output for instance_{idx} — "
            "model printf section is missing or incorrect"
        )
        assert has_assign, (
            f"No ASSIGN lines in glpsol output for instance_{idx} — "
            "model printf section is missing or incorrect"
        )

        # At least one depot must be opened
        open_count = sum(
            1 for l in stdout.split("\n")
            if l.strip().startswith("DEPOT ") and l.strip().split()[2] == "1"
        )
        assert open_count > 0, (
            f"No depots opened by MIP for instance_{idx}"
        )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_instance(path):
    with open(path) as f:
        lines = f.read().strip().split("\n")
    parts = lines[0].split()
    nd, nc, vpd, vc = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])

    depots = []
    for i in range(1, nd + 1):
        p = lines[i].split()
        depots.append({
            "setup": int(p[0]),
            "capacity": int(p[1]),
            "x": float(p[2]),
            "y": float(p[3]),
        })

    customers = []
    for i in range(nd + 1, nd + 1 + nc):
        p = lines[i].split()
        customers.append({
            "demand": int(p[0]),
            "x": float(p[1]),
            "y": float(p[2]),
        })

    return {
        "nd": nd, "nc": nc, "vpd": vpd, "vc": vc,
        "depots": depots, "customers": customers,
    }


def parse_solution(path, nd):
    with open(path) as f:
        lines = f.read().strip().split("\n")

    obj_parts = lines[0].split()
    obj = float(obj_parts[0])
    opt = int(obj_parts[1])

    flags = list(map(int, lines[1].split()))
    assert len(flags) == nd, f"Expected {nd} depot flags, got {len(flags)}"
    opened = [i for i in range(nd) if flags[i] == 1]

    idx = 2
    depot_routes = {}
    for dep in opened:
        r_count = int(lines[idx].strip())
        idx += 1
        routes = []
        for _ in range(r_count):
            custs = list(map(int, lines[idx].split()))
            routes.append(custs)
            idx += 1
        depot_routes[dep] = routes

    return {
        "obj": obj, "opt": opt, "opened": opened,
        "flags": flags, "depot_routes": depot_routes,
    }


# ---------------------------------------------------------------------------
# Distance helper
# ---------------------------------------------------------------------------


def dist(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


# ---------------------------------------------------------------------------
# Compute actual objective
# ---------------------------------------------------------------------------


def compute_cost(inst, sol):
    total = 0.0
    depots = inst["depots"]
    customers = inst["customers"]

    for i in sol["opened"]:
        total += depots[i]["setup"]

    for dep_idx, routes in sol["depot_routes"].items():
        dep = depots[dep_idx]
        for route in routes:
            if not route:
                continue
            c0 = customers[route[0]]
            total += dist(dep["x"], dep["y"], c0["x"], c0["y"])
            for k in range(len(route) - 1):
                c1 = customers[route[k]]
                c2 = customers[route[k + 1]]
                total += dist(c1["x"], c1["y"], c2["x"], c2["y"])
            cl = customers[route[-1]]
            total += dist(cl["x"], cl["y"], dep["x"], dep["y"])

    return total


# ---------------------------------------------------------------------------
# Trivial upper bound
# ---------------------------------------------------------------------------


def trivial_upper_bound(inst):
    depots = inst["depots"]
    customers = inst["customers"]

    total_setup = sum(d["setup"] for d in depots)
    total_routing = 0.0
    for c in customers:
        nearest = min(
            dist(c["x"], c["y"], d["x"], d["y"]) for d in depots
        )
        total_routing += 2.0 * nearest

    return total_setup + total_routing


# ---------------------------------------------------------------------------
# Constraint verification
# ---------------------------------------------------------------------------


def verify_solution(inst, sol):
    errors = []
    nd, nc = inst["nd"], inst["nc"]
    vpd, vc = inst["vpd"], inst["vc"]
    depots = inst["depots"]
    customers = inst["customers"]

    for i, f in enumerate(sol["flags"]):
        if f not in (0, 1):
            errors.append(f"Depot flag {i} is {f}, must be 0 or 1")

    for dep_idx in sol["depot_routes"]:
        if dep_idx not in sol["opened"]:
            errors.append(f"Depot {dep_idx} has routes but is not opened")

    served = []
    for dep_idx, routes in sol["depot_routes"].items():
        if len(routes) > vpd:
            errors.append(
                f"Depot {dep_idx} has {len(routes)} routes, max is {vpd}"
            )

        dep_demand = 0
        for r_idx, route in enumerate(routes):
            route_demand = 0
            for cid in route:
                if cid < 0 or cid >= nc:
                    errors.append(
                        f"Depot {dep_idx} route {r_idx}: "
                        f"customer id {cid} out of range [0,{nc-1}]"
                    )
                    continue
                route_demand += customers[cid]["demand"]
                served.append(cid)

            if route_demand > vc:
                errors.append(
                    f"Depot {dep_idx} route {r_idx}: demand {route_demand} "
                    f"exceeds vehicle capacity {vc}"
                )
            dep_demand += route_demand

        if dep_demand > depots[dep_idx]["capacity"]:
            errors.append(
                f"Depot {dep_idx}: total demand {dep_demand} exceeds "
                f"depot capacity {depots[dep_idx]['capacity']}"
            )

    served_set = set(served)
    if len(served) != len(served_set):
        dupes = [c for c in served_set if served.count(c) > 1]
        errors.append(f"Duplicate customers in routes: {dupes}")

    missing = set(range(nc)) - served_set
    if missing:
        errors.append(f"Customers not served: {sorted(missing)}")

    return errors


# ---------------------------------------------------------------------------
# Per-instance solution tests
# ---------------------------------------------------------------------------

QUALITY_RATIO = 0.72


def _run_instance_test(inst_name):
    inst_path = f"/app/data/{inst_name}.txt"
    sol_path = f"/app/solutions/{inst_name}.sol"

    assert os.path.isfile(inst_path), f"Instance file missing: {inst_path}"
    assert os.path.isfile(sol_path), (
        f"Solution file missing: {sol_path}. "
        "Your solver must write solution files to /app/solutions/."
    )

    inst = parse_instance(inst_path)
    sol = parse_solution(sol_path, inst["nd"])

    errors = verify_solution(inst, sol)
    assert not errors, "Constraint violations:\n" + "\n".join(errors)

    actual_cost = compute_cost(inst, sol)
    assert abs(actual_cost - sol["obj"]) <= max(1.0, 0.01 * actual_cost), (
        f"Reported objective {sol['obj']:.2f} differs from actual "
        f"cost {actual_cost:.2f}"
    )

    ub = trivial_upper_bound(inst)
    threshold = QUALITY_RATIO * ub
    assert actual_cost <= threshold, (
        f"Solution cost {actual_cost:.2f} exceeds quality threshold "
        f"{threshold:.2f} (= {QUALITY_RATIO} x trivial bound {ub:.2f}). "
        f"A better algorithm is needed."
    )


def test_instance_1():
    _run_instance_test("instance_1")


def test_instance_2():
    _run_instance_test("instance_2")


def test_instance_3():
    _run_instance_test("instance_3")
