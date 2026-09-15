#!/usr/bin/env python3
"""Apply all five fixes across the multi-layer simulation pipeline and
produce the structured audit report.

Bug 1 — C library (lib/integrators.c, verlet_step):
    Velocity update uses  dt*dt  instead of  dt.
    The position update (x += v*dt + 0.5*a*dt^2) is correct, but the
    velocity update (v += 0.5*(a_old+a_new)*dt) erroneously multiplies
    by dt^2 again, making the velocity change ~10^4 times too small.
    Fix: replace  dt * dt  with  dt  in the velocity loop.

Bug 2 — Python ctypes wrapper (engine.py, ftcs_step_c):
    Returns the INPUT buffer u_in instead of the OUTPUT buffer u_out,
    so the diffusion stencil result is discarded and the temperature
    profile never evolves from its initial condition.
    Fix: change the return list comprehension to read from u_out.

Bug 3 — TOML config (config/ballistic.toml):
    reference_area is set to 4*pi*r^2 = 0.031416 (full sphere surface
    area) instead of the correct projected cross-section pi*r^2 = 0.007854.
    This makes aerodynamic drag 4x too strong.
    Fix: set reference_area = 0.007854.

Bug 4 — Python physics (simulations/oscillator.py):
    The coupling spring force on mass 2 has the wrong sign.  The code
    uses  +k_c*(q2-q1)  for BOTH masses, violating Newton's third law.
    Mass 2's coupling contribution should be  -k_c*(q2-q1).
    Fix: negate the coupling term in the f2 expression.

Bug 5 — Python physics (simulations/collision.py):
    The elastic-collision normal-velocity formula uses  (m1+m2)  in the
    numerator where it should be  (m1-m2).  Correct 1D elastic:
      v1' = ((m1-m2)*v1 + 2*m2*v2) / (m1+m2)
      v2' = ((m2-m1)*v2 + 2*m1*v1) / (m1+m2)
    Fix: replace  (m1 + m2)  with  (m1 - m2)  and  (m2 + m1)  with
    (m2 - m1) in the respective numerators.
"""
import subprocess
import os
import json


def fix_verlet_c():
    """Fix 1: Correct the velocity-Verlet dt*dt -> dt in C code, rebuild."""
    path = "/app/lib/integrators.c"
    with open(path) as fh:
        src = fh.read()
    old = "vel[i] += 0.5 * (acc_old[i] + acc_new[i]) * dt * dt;"
    new = "vel[i] += 0.5 * (acc_old[i] + acc_new[i]) * dt;"
    assert old in src, "Cannot find buggy verlet velocity line"
    src = src.replace(old, new)
    with open(path, "w") as fh:
        fh.write(src)
    result = subprocess.run(["make", "-C", "/app/lib"], capture_output=True, text=True)
    assert result.returncode == 0, f"make failed: {result.stderr}"
    print("Fix 1 applied: verlet_step velocity update (C rebuild)")


def fix_ftcs_wrapper():
    """Fix 2: Return u_out instead of u_in in engine.py ftcs_step_c."""
    path = "/app/engine.py"
    with open(path) as fh:
        src = fh.read()
    old = "return [u_in[i] for i in range(n)]"
    new = "return [u_out[i] for i in range(n)]"
    assert old in src, "Cannot find buggy ftcs return line"
    src = src.replace(old, new)
    with open(path, "w") as fh:
        fh.write(src)
    print("Fix 2 applied: ftcs_step_c returns u_out")


def fix_ballistic_config():
    """Fix 3: Set correct projected area in ballistic.toml."""
    path = "/app/config/ballistic.toml"
    with open(path) as fh:
        src = fh.read()
    old = "reference_area = 0.031416"
    new = "reference_area = 0.007854"
    assert old in src, "Cannot find buggy reference_area"
    src = src.replace(old, new)
    with open(path, "w") as fh:
        fh.write(src)
    print("Fix 3 applied: ballistic reference_area = pi*r^2")


def fix_oscillator_coupling():
    """Fix 4: Correct the coupling sign on mass 2."""
    path = "/app/simulations/oscillator.py"
    with open(path) as fh:
        src = fh.read()
    old = "f2 = (-k2 * q2 + k_c * (q2 - q1)) / m2"
    new = "f2 = (-k2 * q2 - k_c * (q2 - q1)) / m2"
    assert old in src, "Cannot find buggy oscillator f2 line"
    src = src.replace(old, new)
    with open(path, "w") as fh:
        fh.write(src)
    print("Fix 4 applied: oscillator coupling sign (Newton's 3rd law)")


def fix_collision_formula():
    """Fix 5: Correct the elastic collision numerator."""
    path = "/app/simulations/collision.py"
    with open(path) as fh:
        src = fh.read()
    src = src.replace(
        "((m1 + m2) * v1n + 2 * m2 * v2n)",
        "((m1 - m2) * v1n + 2 * m2 * v2n)",
    )
    src = src.replace(
        "((m2 + m1) * v2n + 2 * m1 * v1n)",
        "((m2 - m1) * v2n + 2 * m1 * v1n)",
    )
    with open(path, "w") as fh:
        fh.write(src)
    print("Fix 5 applied: collision elastic formula (m1-m2)")


def create_audit_report():
    """Create the structured audit report documenting each defect."""
    os.makedirs("/app/audit", exist_ok=True)
    report = {
        "ballistic": {
            "layer": "TOML parameter configuration",
            "root_cause": (
                "reference_area in config/ballistic.toml is set to 0.031416 "
                "(4*pi*r^2, the total sphere surface area) instead of the "
                "correct projected cross-sectional area pi*r^2 = 0.007854. "
                "This quadruples the aerodynamic drag force, causing the "
                "projectile to fall far short of the correct range."
            ),
            "conservation_law_violated": (
                "Newton's second law — the drag force magnitude is incorrect "
                "due to a dimensional analysis error in the aerodynamic "
                "reference area, producing 4x the physical drag deceleration"
            ),
        },
        "oscillator": {
            "layer": "Python simulation equations",
            "root_cause": (
                "In simulations/oscillator.py, the coupling spring force on "
                "mass 2 uses +k_c*(q2-q1) instead of -k_c*(q2-q1). Both "
                "masses experience the coupling force in the same direction, "
                "violating Newton's third law. The correct sign makes the "
                "action-reaction pair: f1_coupling = +k_c*(q2-q1)/m1, "
                "f2_coupling = -k_c*(q2-q1)/m2."
            ),
            "conservation_law_violated": (
                "Newton's third law (action-reaction symmetry) — the coupling "
                "spring exerts force in the same direction on both masses, "
                "causing spurious energy injection and unbounded oscillation"
            ),
        },
        "diffusion": {
            "layer": "Python-C ctypes interface layer",
            "root_cause": (
                "In engine.py, the ftcs_step_c wrapper function returns "
                "values from the input buffer u_in instead of the output "
                "buffer u_out. The C library correctly computes the FTCS "
                "stencil into u_out, but the Python wrapper discards this "
                "result by reading from u_in, so the temperature profile "
                "never evolves from its initial condition."
            ),
            "conservation_law_violated": (
                "Conservation of energy / heat equation — the thermal "
                "diffusion process is completely stalled because the "
                "computed update is discarded at the FFI boundary, leaving "
                "the temperature field frozen at initial conditions"
            ),
        },
        "orbit": {
            "layer": "C numerical integration library",
            "root_cause": (
                "In lib/integrators.c, the velocity-Verlet velocity update "
                "loop uses dt*dt instead of dt: "
                "'vel[i] += 0.5 * (acc_old[i] + acc_new[i]) * dt * dt'. "
                "The position update correctly uses dt and dt^2, but the "
                "velocity update erroneously squares dt, reducing velocity "
                "changes by a factor of ~10^4 and effectively freezing "
                "orbital velocity evolution."
            ),
            "conservation_law_violated": (
                "Conservation of orbital energy and angular momentum — the "
                "broken velocity update destroys the symplectic structure of "
                "the Verlet integrator, causing the orbit to fail to close "
                "and violating Kepler's laws"
            ),
        },
        "collision": {
            "layer": "Python simulation equations",
            "root_cause": (
                "In simulations/collision.py, the 1D elastic collision "
                "formula uses (m1+m2) in the numerator where it should be "
                "(m1-m2): the code computes v1n_new = ((m1+m2)*v1n + "
                "2*m2*v2n)/(m1+m2) instead of the correct "
                "((m1-m2)*v1n + 2*m2*v2n)/(m1+m2). Similarly for v2n_new "
                "with (m2+m1) instead of (m2-m1)."
            ),
            "conservation_law_violated": (
                "Conservation of kinetic energy and linear momentum — the "
                "incorrect elastic collision formula fails to satisfy both "
                "conservation laws simultaneously for unequal masses"
            ),
        },
    }
    with open("/app/audit/report.json", "w") as fh:
        json.dump(report, fh, indent=2)
    print("Audit report created at /app/audit/report.json")


def run_all():
    """Run every simulation after fixes."""
    for name in ["ballistic", "oscillator", "diffusion", "orbit", "collision"]:
        print(f"Running {name}...")
        result = subprocess.run(
            ["python3", f"/app/simulations/{name}.py"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr[:300]}")
        else:
            print(f"  OK")


if __name__ == "__main__":
    fix_verlet_c()
    fix_ftcs_wrapper()
    fix_ballistic_config()
    fix_oscillator_coupling()
    fix_collision_formula()
    run_all()
    create_audit_report()
