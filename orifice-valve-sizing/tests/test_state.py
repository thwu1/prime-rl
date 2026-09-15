"""Tests for the flow measurement calibration system.

Verifies the C shared library build, direct function correctness across the
C/Python boundary, and the calibration report pipeline.
"""

import ctypes
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, "/app")


# ──────────────────────────────────────────────────────────────
# Shared library build verification
# ──────────────────────────────────────────────────────────────

def test_shared_library_exists_and_loads():
    """Verify libflowcore.so exists and can be loaded via ctypes."""
    lib_path = "/app/libflowcore.so"
    assert os.path.exists(lib_path), (
        f"Shared library not found at {lib_path}. "
        "The Makefile must produce a loadable .so file."
    )
    lib = ctypes.CDLL(lib_path)
    assert hasattr(lib, "orifice_C"), "Missing symbol orifice_C"
    assert hasattr(lib, "orifice_eps"), "Missing symbol orifice_eps"
    assert hasattr(lib, "orifice_flow"), "Missing symbol orifice_flow"


# ──────────────────────────────────────────────────────────────
# Orifice discharge coefficient — direct function tests
# ──────────────────────────────────────────────────────────────

def test_orifice_C_corner():
    from flowcal import orifice_discharge_coefficient
    C = orifice_discharge_coefficient(
        D=0.07391, Do=0.0222,
        rho=1.1645909036, mu=1.8586175309e-05,
        m=0.124431876, taps="corner",
    )
    assert math.isclose(C, 0.6000085121443794, rel_tol=1e-4), f"C={C}"


def test_orifice_C_D_taps():
    from flowcal import orifice_discharge_coefficient
    C = orifice_discharge_coefficient(
        D=0.07391, Do=0.0222,
        rho=1.1645909036, mu=1.8586175309e-05,
        m=0.124431876, taps="D",
    )
    assert math.isclose(C, 0.5988219225153737, rel_tol=1e-4), f"C={C}"


def test_orifice_C_flange():
    from flowcal import orifice_discharge_coefficient
    C = orifice_discharge_coefficient(
        D=0.07391, Do=0.0222,
        rho=1.1645909036, mu=1.8586175309e-05,
        m=0.124431876, taps="flange",
    )
    assert math.isclose(C, 0.5990042535666640, rel_tol=1e-4), f"C={C}"


# ──────────────────────────────────────────────────────────────
# Orifice expansibility — direct function test
# ──────────────────────────────────────────────────────────────

def test_orifice_expansibility():
    from flowcal import orifice_expansibility
    eps = orifice_expansibility(
        D=0.0739, Do=0.0222, P1=1e5, P2=9.9e4, k=1.4,
    )
    assert math.isclose(eps, 0.9974739057343425, rel_tol=1e-4), f"eps={eps}"


# ──────────────────────────────────────────────────────────────
# Orifice flow rate solver — direct function test
# ──────────────────────────────────────────────────────────────

def test_orifice_flow_rate():
    from flowcal import solve_orifice_flow_rate
    m = solve_orifice_flow_rate(
        D=0.07366, Do=0.05,
        P1=200000.0, P2=183000.0,
        rho=999.1, mu=0.0011, k=1.33,
        taps="D",
    )
    assert math.isclose(m, 7.702338035732143, rel_tol=1e-4), f"m={m}"


# ──────────────────────────────────────────────────────────────
# Liquid valve sizing — direct function tests
# ──────────────────────────────────────────────────────────────

def test_liquid_valve_non_choked():
    from flowcal import size_liquid_valve
    Kv = size_liquid_valve(
        rho=965.4, Psat=70.1e3, Pc=22120e3, mu=3.1472e-4,
        P1=680e3, P2=220e3, Q=0.1,
        D1=0.15, D2=0.15, d=0.15,
        FL=0.9, Fd=0.46,
    )
    assert math.isclose(Kv, 164.9954763704956, rel_tol=1e-4), f"Kv={Kv}"


def test_liquid_valve_choked():
    from flowcal import size_liquid_valve
    Kv = size_liquid_valve(
        rho=965.4, Psat=70.1e3, Pc=22120e3, mu=3.1472e-4,
        P1=680e3, P2=220e3, Q=0.1,
        D1=0.1, D2=0.1, d=0.1,
        FL=0.6, Fd=0.98,
    )
    assert math.isclose(Kv, 238.05817216710483, rel_tol=1e-4), f"Kv={Kv}"


def test_liquid_valve_piping():
    from flowcal import size_liquid_valve
    Kv = size_liquid_valve(
        rho=965.4, Psat=70.1e3, Pc=22120e3, mu=3.1472e-4,
        P1=680e3, P2=220e3, Q=0.1,
        D1=0.1, D2=0.1, d=0.095,
        FL=0.6, Fd=0.98,
    )
    assert math.isclose(Kv, 241.6812562245056, rel_tol=1e-4), f"Kv={Kv}"


# ──────────────────────────────────────────────────────────────
# Gas valve sizing — direct function tests
# ──────────────────────────────────────────────────────────────

def test_gas_valve_piping():
    from flowcal import size_gas_valve
    Kv = size_gas_valve(
        T=433.0, MW=44.01, mu=1.4665e-4, gamma=1.30, Z=0.988,
        P1=680e3, P2=310e3, Q=38.0 / 36.0,
        D1=0.08, D2=0.1, d=0.05,
        FL=0.85, Fd=0.42, xT=0.60,
    )
    assert math.isclose(Kv, 72.58664545391050, rel_tol=1e-4), f"Kv={Kv}"


def test_gas_valve_choked():
    from flowcal import size_gas_valve
    Kv = size_gas_valve(
        T=433.0, MW=44.01, mu=1.4665e-4, gamma=1.30, Z=0.988,
        P1=680e3, P2=100e3, Q=0.5,
        D1=None, D2=None, d=None,
        FL=0.85, Fd=0.42, xT=0.60,
    )
    assert math.isclose(Kv, 29.671162740732292, rel_tol=1e-4), f"Kv={Kv}"


# ──────────────────────────────────────────────────────────────
# Calibration report pipeline test
# ──────────────────────────────────────────────────────────────

def test_calibration_report():
    """Run the calibration script and verify the output report."""
    results_path = "/app/results.json"
    if os.path.exists(results_path):
        os.remove(results_path)

    result = subprocess.run(
        [sys.executable, "/app/run_calibration.py"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Calibration script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(results_path), "results.json not created"

    with open(results_path) as f:
        report = json.load(f)

    # Schema checks
    assert "test_results" in report, "Missing 'test_results' key"
    assert "summary" in report, "Missing 'summary' key"
    assert isinstance(report["test_results"], list), "test_results must be a list"

    summary = report["summary"]
    assert "total" in summary and "passed" in summary and "failed" in summary

    # Verify all required fields in each result
    for r in report["test_results"]:
        for key in ("id", "category", "computed", "expected", "error_pct", "status"):
            assert key in r, f"Missing key '{key}' in result {r.get('id', '?')}"

    # All five categories must be present
    categories = set(r["category"] for r in report["test_results"])
    expected_cats = {"orifice_C", "orifice_eps", "orifice_flow", "valve_liquid", "valve_gas"}
    assert categories == expected_cats, (
        f"Missing categories: {expected_cats - categories}"
    )

    # All tests must pass
    assert summary["failed"] == 0, (
        f"Expected 0 failures, got {summary['failed']}. "
        f"Failing tests: {[r['id'] for r in report['test_results'] if r['status'] == 'fail']}"
    )

    # Summary consistency
    assert summary["total"] == len(report["test_results"])
    assert summary["passed"] + summary["failed"] == summary["total"]
    assert summary["total"] == summary["passed"]
