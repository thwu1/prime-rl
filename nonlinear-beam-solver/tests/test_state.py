
"""
End-to-end tests for the beam analysis pipeline.

Verifies:
- C library compilation and ctypes integration
- MBDyn format parsing (implicit via result accuracy)
- Solver accuracy against analytical / BVP references
- Output schemas and validation report
- Dynamic model handling (anti-cheat: model generated at test time)
"""

import json
import math
import os
import subprocess

import numpy as np
import pytest
from scipy.integrate import solve_bvp


# ------------------------------------------------------------------ #
#  Constants                                                          #
# ------------------------------------------------------------------ #

PROBE_STEM = "verify_probe"

ORIGINAL_STEMS = [
    "cantilever_linear",
    "rollup_half",
    "rollup_full",
    "elastica_large",
    "coupled_loading",
]

ALL_STEMS = ORIGINAL_STEMS + [PROBE_STEM]


# ------------------------------------------------------------------ #
#  Fixtures                                                           #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="session")
def probe_model_info():
    """Create a verification model at test time with unique parameters.

    This model does NOT exist in the shipped environment; it is written
    here so that any solver must actually work on novel inputs.
    """
    L = 1.7
    nn = 11
    ne_mbd = 5
    dx = L / (nn - 1)
    EI = 137.0
    EA = 1e8
    GA = 1e8
    GJ = 137.0
    P = 0.3

    lines = [
        "begin: data;",
        "    problem: initial value;",
        "end: data;",
        "",
        "begin: initial value;",
        "    initial time: 0.;",
        "    final time: 1.;",
        "    time step: 1.;",
        "    max iterations: 50;",
        "    tolerance: 1.e-6;",
        "end: initial value;",
        "",
        "begin: control data;",
        f"    structural nodes: {nn};",
        f"    beams: {ne_mbd};",
        "    joints: 1;",
        "    forces: 1;",
        "end: control data;",
        "",
        "begin: nodes;",
    ]
    for i in range(nn):
        ntype = "static" if i == 0 else "dynamic"
        x = i * dx
        lines.append(
            f"    structural: {i+1}, {ntype}, {x:.10f}, 0., 0., eye, null, null;"
        )
    lines.append("end: nodes;")
    lines.append("")
    lines.append("begin: elements;")
    lines.append("    joint: 1, clamp, 1, node, node;")
    lines.append("")
    for e in range(ne_mbd):
        n1 = 2 * e + 1
        n2 = 2 * e + 2
        n3 = 2 * e + 3
        lines.append(f"    beam: {e+1},")
        lines.append(f"        {n1}, null, {n2}, null, {n3}, null,")
        lines.append("        eye,")
        lines.append("        linear elastic generic,")
        lines.append(f"            diag, {EA}, {GA}, {GA}, {GJ}, {EI}, {EI},")
        lines.append("        same,")
        lines.append("        same;")

    lines.append(
        f"    force: 1, absolute, {nn}, position, null, 0., 1., 0., const, {P};"
    )
    lines.append("end: elements;")

    mbd_path = f"/app/models/{PROBE_STEM}.mbd"
    with open(mbd_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return {"L": L, "EI": EI, "P": P}


@pytest.fixture(scope="session", autouse=True)
def pipeline_result(probe_model_info):
    """Run the beam pipeline once before all tests."""
    result = subprocess.run(
        ["python3", "/app/beam_pipeline.py"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd="/app",
    )
    return result


def _load_result(stem):
    path = f"/app/results/{stem}.json"
    with open(path) as f:
        return json.load(f)


# ------------------------------------------------------------------ #
#  Infrastructure tests                                               #
# ------------------------------------------------------------------ #

def test_library_compiled():
    """libso3.so must exist after pipeline execution."""
    assert os.path.isfile("/app/kernels/libso3.so"), "libso3.so not found"


def test_pipeline_exit_code(pipeline_result):
    """Pipeline must exit 0."""
    assert pipeline_result.returncode == 0, (
        f"Pipeline exited {pipeline_result.returncode}.\n"
        f"stderr: {pipeline_result.stderr[-800:]}"
    )


def test_ctypes_usage():
    """beam_pipeline.py must load the C library via ctypes."""
    with open("/app/beam_pipeline.py") as f:
        src = f.read()
    assert "ctypes" in src, "beam_pipeline.py does not reference ctypes"
    assert "libso3" in src, "beam_pipeline.py does not reference libso3"


# ------------------------------------------------------------------ #
#  Output schema tests                                                #
# ------------------------------------------------------------------ #

def test_all_results_exist():
    """All per-model result JSONs must exist (including dynamic probe)."""
    for stem in ALL_STEMS:
        path = f"/app/results/{stem}.json"
        assert os.path.isfile(path), f"Missing result: {path}"


def test_result_schema():
    """Each result JSON must contain the required fields."""
    for stem in ALL_STEMS:
        r = _load_result(stem)
        assert "model" in r, f"{stem}: missing 'model'"
        assert "converged" in r, f"{stem}: missing 'converged'"
        assert "tip_displacement" in r, f"{stem}: missing 'tip_displacement'"
        assert len(r["tip_displacement"]) == 3, (
            f"{stem}: tip_displacement must have 3 components"
        )
        assert "tip_rotation" in r, f"{stem}: missing 'tip_rotation'"
        assert len(r["tip_rotation"]) == 3, (
            f"{stem}: tip_rotation must have 3 components"
        )
        assert "final_residual" in r, f"{stem}: missing 'final_residual'"


def test_validation_report():
    """validation.json must exist with correct schema and all_pass == True."""
    path = "/app/validation.json"
    assert os.path.isfile(path), "validation.json not found"
    with open(path) as f:
        v = json.load(f)
    assert "models" in v, "validation.json missing 'models'"
    assert "all_pass" in v, "validation.json missing 'all_pass'"
    for stem in ALL_STEMS:
        assert stem in v["models"], f"validation.json missing model '{stem}'"
        m = v["models"][stem]
        assert "converged" in m, f"{stem}: missing 'converged'"
        assert "final_residual" in m, f"{stem}: missing 'final_residual'"
        assert "pass" in m, f"{stem}: missing 'pass'"
    assert v["all_pass"] is True, (
        "validation.json reports all_pass=False. Model details: "
        + json.dumps(v["models"], indent=2)
    )


# ------------------------------------------------------------------ #
#  Accuracy tests — original models                                   #
# ------------------------------------------------------------------ #

def test_cantilever_linear():
    """Small transverse load: tip deflection must match Euler-Bernoulli."""
    r = _load_result("cantilever_linear")
    assert r["converged"], "cantilever_linear did not converge"
    uy = r["tip_displacement"][1]
    # PL^3 / (3 EI) with P=0.01, L=1.0, EI=1000
    uy_ref = 0.01 * 1.0 ** 3 / (3.0 * 1000.0)
    assert abs(uy - uy_ref) / abs(uy_ref) < 0.02, (
        f"Linear uy={uy:.6e} vs ref={uy_ref:.6e}"
    )


def test_rollup_semicircle():
    """End moment producing large curvature: check tip position."""
    r = _load_result("rollup_half")
    assert r["converged"], "rollup_half did not converge"
    ux, uy, uz = r["tip_displacement"]
    L = 10.0
    # Analytical for M = pi*EI/L: tip at (0, 2L/pi) => disp (-L, 2L/pi, 0)
    ux_ref = -L
    uy_ref = 2.0 * L / math.pi
    assert abs(ux - ux_ref) / L < 0.03, f"ux={ux:.4f} vs {ux_ref:.4f}"
    assert abs(uy - uy_ref) / uy_ref < 0.03, f"uy={uy:.4f} vs {uy_ref:.4f}"
    assert abs(uz) / L < 0.02, f"uz should be ~0, got {uz:.6f}"


def test_rollup_full_circle():
    """Large end moment: tip returns near root position."""
    r = _load_result("rollup_full")
    assert r["converged"], "rollup_full did not converge"
    ux, uy, uz = r["tip_displacement"]
    L = 10.0
    assert abs(ux - (-L)) / L < 0.05, f"ux={ux:.4f} vs {-L}"
    assert abs(uy) / L < 0.05, f"uy should be ~0, got {uy:.6f}"
    assert abs(uz) / L < 0.03, f"uz should be ~0, got {uz:.6f}"


def test_elastica_large_deflection():
    """Large transverse load: compare against inextensible elastica BVP."""
    r = _load_result("elastica_large")
    assert r["converged"], "elastica_large did not converge"

    L, EI, P = 1.0, 1.0, 5.0
    alpha = P / EI

    def ode(s, y):
        return np.vstack([y[1], -alpha * np.cos(y[0])])

    def bc(ya, yb):
        return np.array([ya[0], yb[1]])

    s_mesh = np.linspace(0, L, 300)
    y_init = np.zeros((2, 300))
    y_init[1, :] = alpha * (L - s_mesh)
    sol = solve_bvp(ode, bc, s_mesh, y_init, tol=1e-10, max_nodes=10000)
    assert sol.success, f"Elastica BVP failed: {sol.message}"

    s_fine = np.linspace(0, L, 5000)
    theta = sol.sol(s_fine)[0]
    ds = s_fine[1] - s_fine[0]
    ux_ref = np.sum(np.cos(theta)) * ds - L
    uy_ref = np.sum(np.sin(theta)) * ds

    ux, uy, uz = r["tip_displacement"]
    assert abs(ux - ux_ref) / L < 0.03, f"ux={ux:.4f} vs ref={ux_ref:.4f}"
    assert abs(uy - uy_ref) / L < 0.03, f"uy={uy:.4f} vs ref={uy_ref:.4f}"
    assert abs(uz) / L < 0.01, f"uz should be ~0, got {uz:.6f}"


def test_combined_loading():
    """Combined bending + torsion: check 3D coupling and bending accuracy."""
    r = _load_result("coupled_loading")
    assert r["converged"], "coupled_loading did not converge"

    ux, uy, uz = r["tip_displacement"]
    rx, ry, rz = r["tip_rotation"]

    # Nonzero uz proves 3D bending-torsion coupling
    assert abs(uz) > 0.01, (
        f"Combined loading must produce out-of-plane displacement, got uz={uz:.6f}"
    )

    # Bending part: solve 2D elastica for the Fy component
    L, EI, P = 2.0, 50.0, 20.0
    alpha = P / EI

    def ode(s, y):
        return np.vstack([y[1], -alpha * np.cos(y[0])])

    def bc(ya, yb):
        return np.array([ya[0], yb[1]])

    s_mesh = np.linspace(0, L, 300)
    y_init = np.zeros((2, 300))
    y_init[1, :] = alpha * (L - s_mesh)
    sol = solve_bvp(ode, bc, s_mesh, y_init, tol=1e-10, max_nodes=10000)
    assert sol.success

    s_fine = np.linspace(0, L, 5000)
    theta = sol.sol(s_fine)[0]
    ds = s_fine[1] - s_fine[0]
    uy_bvp = np.sum(np.sin(theta)) * ds

    # uy should be close to bending-only reference (torsion modifies slightly)
    assert abs(uy - uy_bvp) / uy_bvp < 0.15, (
        f"uy={uy:.4f} vs bending-only BVP={uy_bvp:.4f}"
    )

    # Torsional rotation should be significant
    assert abs(rx) > 0.2, f"rx should be significant, got {rx:.4f}"
    # Linear torsion: rx = Mx*L/GJ = 20*2/80 = 0.5
    rx_linear = 20.0 * 2.0 / 80.0
    assert abs(rx - rx_linear) / rx_linear < 0.40, (
        f"rx={rx:.4f} vs linear={rx_linear:.4f}"
    )


# ------------------------------------------------------------------ #
#  Dynamic probe model test (anti-cheat)                              #
# ------------------------------------------------------------------ #

def test_probe_model(probe_model_info):
    """Dynamically generated model must match Euler-Bernoulli prediction.

    This model is created at test time with parameters that do not exist
    anywhere in the shipped environment, so the solver must actually work.
    """
    r = _load_result(PROBE_STEM)
    assert r["converged"], f"{PROBE_STEM} did not converge"

    L = probe_model_info["L"]
    EI = probe_model_info["EI"]
    P = probe_model_info["P"]

    uy_ref = P * L ** 3 / (3.0 * EI)
    uy = r["tip_displacement"][1]

    assert abs(uy - uy_ref) / abs(uy_ref) < 0.02, (
        f"Probe model: uy={uy:.6e} vs Euler-Bernoulli ref={uy_ref:.6e}"
    )
    # ux should be negligible in linear regime
    ux = r["tip_displacement"][0]
    assert abs(ux) / L < 1e-4, (
        f"Probe model: ux should be ~0, got {ux:.6e}"
    )
    # uz should be zero (planar problem)
    uz = r["tip_displacement"][2]
    assert abs(uz) / L < 1e-6, (
        f"Probe model: uz should be ~0, got {uz:.6e}"
    )
