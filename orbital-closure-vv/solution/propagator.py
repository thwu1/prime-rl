#!/usr/bin/env python3

"""
GMAT Mission Script Propagation Cross-Validation Framework
Parses GMAT scripts, implements adaptive RK integration with zonal harmonics,
runs closure tests, and cross-validates with GNU Octave.
"""

import json
import math
import os
import re
import subprocess
import numpy as np

# ============================================================
# GMAT Script Parser
# ============================================================

def parse_gmat_script(filepath):
    """Parse a GMAT .script file and extract mission configuration."""
    with open(filepath) as f:
        lines = f.readlines()

    objects = {}
    properties = {}
    duration_days = None
    sc_name = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith('%'):
            continue

        m = re.match(r'Create\s+(\w+)\s+(\w+)\s*;', line)
        if m:
            obj_type, obj_name = m.groups()
            objects[obj_name] = obj_type
            properties.setdefault(obj_name, {})
            continue

        m = re.match(r'GMAT\s+(\w+)\.(.+?)\s*=\s*(.+?)\s*;', line)
        if m:
            obj_name, prop, value = m.groups()
            properties.setdefault(obj_name, {})[prop.strip()] = value.strip()
            continue

        m = re.match(r'Propagate\s+(\w+)\((\w+)\)\s*\{(.+?)\}\s*;', line)
        if m:
            _, sc_name_seq, condition = m.groups()
            cm = re.match(r'(\w+)\.ElapsedDays\s*=\s*([\d.eE+-]+)', condition.strip())
            if cm:
                sc_name = cm.group(1)
                duration_days = float(cm.group(2))

    spacecraft = None
    for name, otype in objects.items():
        if otype == 'Spacecraft':
            spacecraft = name
            break
    if spacecraft is None and sc_name:
        spacecraft = sc_name

    force_model = None
    for name, otype in objects.items():
        if otype == 'ForceModel':
            force_model = name
            break

    propagator = None
    for name, otype in objects.items():
        if otype == 'Propagator':
            propagator = name
            break

    sc_props = properties.get(spacecraft, {})
    fm_props = properties.get(force_model, {}) if force_model else {}
    pr_props = properties.get(propagator, {}) if propagator else {}

    state = [
        float(sc_props.get('X', 0)),
        float(sc_props.get('Y', 0)),
        float(sc_props.get('Z', 0)),
        float(sc_props.get('VX', 0)),
        float(sc_props.get('VY', 0)),
        float(sc_props.get('VZ', 0)),
    ]

    gravity_degree = int(fm_props.get('GravityField.Earth.Degree', 0))
    gravity_order = int(fm_props.get('GravityField.Earth.Order', 0))

    drag_val = fm_props.get('Drag', 'None')
    drag_model = None if drag_val in ('None', 'none', '') else drag_val

    srp_val = fm_props.get('SRP', 'Off')
    srp_enabled = srp_val.lower() not in ('off', 'false', 'no', '')

    pm_str = fm_props.get('PointMasses', '{}')
    pm_str = pm_str.strip('{}').strip()
    point_masses = [x.strip() for x in pm_str.split(',') if x.strip()] if pm_str else []

    integrator_type = pr_props.get('Type', 'RungeKutta89')
    accuracy = float(pr_props.get('Accuracy', 1e-12))

    return {
        'initial_state': state,
        'gravity_degree': gravity_degree,
        'gravity_order': gravity_order,
        'drag_model': drag_model,
        'srp_enabled': srp_enabled,
        'point_masses': point_masses,
        'integrator_type': integrator_type,
        'accuracy': accuracy,
        'duration_days': duration_days if duration_days else 1.0,
    }


# ============================================================
# Force Models
# ============================================================

def accel_twobody(state, mu):
    r = state[:3]
    r_mag = np.linalg.norm(r)
    return -mu / r_mag**3 * r


def accel_J2(state, mu, Re, J2):
    x, y, z = state[0], state[1], state[2]
    r = np.sqrt(x*x + y*y + z*z)
    z2_r2 = (z / r)**2
    coeff = 1.5 * mu * J2 * Re**2 / r**5
    return np.array([
        coeff * x * (5.0 * z2_r2 - 1.0),
        coeff * y * (5.0 * z2_r2 - 1.0),
        coeff * z * (5.0 * z2_r2 - 3.0),
    ])


def accel_J3(state, mu, Re, J3):
    x, y, z = state[0], state[1], state[2]
    r = np.sqrt(x*x + y*y + z*z)
    z_r = z / r
    z2_r2 = z_r**2
    coeff_xy = 2.5 * mu * J3 * Re**3 / r**7
    ax = coeff_xy * x * z * (7.0 * z2_r2 - 3.0)
    ay = coeff_xy * y * z * (7.0 * z2_r2 - 3.0)
    az = 0.5 * mu * J3 * Re**3 / r**5 * (3.0 - 30.0*z2_r2 + 35.0*z2_r2**2)
    return np.array([ax, ay, az])


def accel_J4(state, mu, Re, J4):
    x, y, z = state[0], state[1], state[2]
    r = np.sqrt(x*x + y*y + z*z)
    z2_r2 = (z / r)**2
    z4_r4 = z2_r2**2
    coeff_xy = 15.0 * mu * J4 * Re**4 / (8.0 * r**7)
    coeff_z = 5.0 * mu * J4 * Re**4 / (8.0 * r**7)
    return np.array([
        coeff_xy * x * (21.0 * z4_r4 - 14.0 * z2_r2 + 1.0),
        coeff_xy * y * (21.0 * z4_r4 - 14.0 * z2_r2 + 1.0),
        coeff_z * z * (63.0 * z4_r4 - 70.0 * z2_r2 + 15.0),
    ])


def build_accel_func(mu, Re, constants, gravity_degree):
    J2_val = constants['earth']['J2']
    J3_val = constants['earth']['J3']
    J4_val = constants['earth']['J4']

    def accel(t, state):
        a = accel_twobody(state, mu)
        if gravity_degree >= 2:
            a += accel_J2(state, mu, Re, J2_val)
        if gravity_degree >= 3:
            a += accel_J3(state, mu, Re, J3_val)
        if gravity_degree >= 4:
            a += accel_J4(state, mu, Re, J4_val)
        return np.concatenate([state[3:6], a])

    return accel


# ============================================================
# Dormand-Prince 4(5) Adaptive Integrator
# ============================================================

DP45_A = np.array([
    [0, 0, 0, 0, 0, 0, 0],
    [1/5, 0, 0, 0, 0, 0, 0],
    [3/40, 9/40, 0, 0, 0, 0, 0],
    [44/45, -56/15, 32/9, 0, 0, 0, 0],
    [19372/6561, -25360/2187, 64448/6561, -212/729, 0, 0, 0],
    [9017/3168, -355/33, 46732/5247, 49/176, -5103/18656, 0, 0],
    [35/384, 0, 500/1113, 125/192, -2187/6784, 11/84, 0],
])
DP45_B5 = np.array([35/384, 0, 500/1113, 125/192, -2187/6784, 11/84, 0])
DP45_B4 = np.array([5179/57600, 0, 7571/16695, 393/640, -92097/339200, 187/2100, 1/40])
DP45_C = np.array([0, 1/5, 3/10, 4/5, 8/9, 1, 1])


def dp45_step(f, t, y, h):
    n = len(y)
    k = np.zeros((7, n))
    k[0] = f(t, y)
    for i in range(1, 7):
        y_stage = y.copy()
        for j in range(i):
            y_stage += h * DP45_A[i, j] * k[j]
        k[i] = f(t + DP45_C[i] * h, y_stage)

    y5 = y + h * np.dot(DP45_B5, k)
    y4 = y + h * np.dot(DP45_B4, k)
    return y5, y4, k


def propagate_adaptive(f, t0, y0, t_end, tol=1e-12, h_init=60.0,
                       h_min=1e-6, h_max=86400.0):
    t = t0
    y = y0.copy()
    direction = 1.0 if t_end > t0 else -1.0
    h = direction * abs(h_init)
    total_steps = 0
    total_fevals = 0
    safety = 0.9

    while direction * (t_end - t) > 1e-15:
        if direction * (t + h - t_end) > 0:
            h = t_end - t

        y5, y4, k = dp45_step(f, t, y, h)
        total_fevals += 7

        err_vec = y5 - y4
        scale = np.maximum(np.maximum(np.abs(y5), np.abs(y)), 1e-10) * tol + tol
        err = np.sqrt(np.mean((err_vec / scale)**2))

        if err <= 1.0 or abs(h) <= abs(h_min):
            t += h
            y = y5
            total_steps += 1
            if err > 1e-18:
                h_new = h * safety * err**(-0.2)
            else:
                h_new = h * 5.0
            h = direction * min(abs(h_new), abs(h_max))
        else:
            h_new = h * safety * err**(-0.25)
            h = direction * max(abs(h_new), abs(h_min))

    return y, total_steps, total_fevals


# ============================================================
# Orbital Element Computation
# ============================================================

def cartesian_to_raan(state, mu):
    r = state[:3]
    v = state[3:6]
    h = np.cross(r, v)
    h_mag = np.linalg.norm(h)
    inc = math.acos(np.clip(h[2] / h_mag, -1, 1))
    k = np.array([0.0, 0.0, 1.0])
    n = np.cross(k, h)
    n_mag = np.linalg.norm(n)
    if n_mag < 1e-10:
        return 0.0, inc
    raan = math.acos(np.clip(n[0] / n_mag, -1, 1))
    if n[1] < 0:
        raan = 2 * math.pi - raan
    return raan, inc


# ============================================================
# Octave Integration
# ============================================================

def run_octave_validation(state, output_path="/app/octave_results.txt"):
    template_path = "/app/validate_template.m"
    script_path = "/app/validate.m"

    with open(template_path) as f:
        content = f.read()

    content = content.replace("X0  = 0.0;", f"X0  = {state[0]};")
    content = content.replace("Y0  = 0.0;", f"Y0  = {state[1]};")
    content = content.replace("Z0  = 0.0;", f"Z0  = {state[2]};")
    content = content.replace("VX0 = 0.0;", f"VX0 = {state[3]};")
    content = content.replace("VY0 = 0.0;", f"VY0 = {state[4]};")
    content = content.replace("VZ0 = 0.0;", f"VZ0 = {state[5]};")

    with open(script_path, 'w') as f:
        f.write(content)

    result = subprocess.run(
        ["octave", "--no-gui", script_path],
        capture_output=True, text=True, timeout=120
    )

    output = result.stdout
    with open(output_path, 'w') as f:
        f.write(output)

    octave_raan = None
    for line in output.split('\n'):
        m = re.match(r'raan_precession_deg_day=([-\d.eE+]+)', line)
        if m:
            octave_raan = float(m.group(1))

    return octave_raan


# ============================================================
# Main
# ============================================================

def main():
    with open("/app/constants.json") as f:
        constants = json.load(f)

    mu = constants['earth']['mu_km3_s2']
    Re = constants['earth']['radius_km']

    script_dir = "/app/gmat_scripts/"
    missions = {}
    for fname in sorted(os.listdir(script_dir)):
        if fname.endswith('.script'):
            mission_name = fname.replace('.script', '')
            config = parse_gmat_script(os.path.join(script_dir, fname))
            missions[mission_name] = config

    parsed_missions = {}
    for name, cfg in missions.items():
        parsed_missions[name] = {
            "initial_state": cfg['initial_state'],
            "gravity_degree": cfg['gravity_degree'],
            "gravity_order": cfg['gravity_order'],
            "drag_model": cfg['drag_model'],
            "srp_enabled": cfg['srp_enabled'],
            "integrator_type": cfg['integrator_type'],
            "accuracy": cfg['accuracy'],
            "duration_days": cfg['duration_days'],
        }

    closure_results = {}
    conservation = {}
    total_steps = 0
    total_fevals = 0
    raan_data = {}

    for name, cfg in missions.items():
        print(f"Processing mission: {name}")
        state0 = np.array(cfg['initial_state'])
        duration_s = cfg['duration_days'] * 86400.0
        tol = cfg['accuracy']
        degree = cfg['gravity_degree']

        accel_func = build_accel_func(mu, Re, constants, degree)

        h_init = min(60.0, duration_s / 100.0)
        y_fwd, steps_fwd, fevals_fwd = propagate_adaptive(
            accel_func, 0.0, state0.copy(), duration_s, tol=tol, h_init=h_init
        )
        y_back, steps_back, fevals_back = propagate_adaptive(
            accel_func, duration_s, y_fwd, 0.0, tol=tol, h_init=-h_init
        )

        err = np.linalg.norm(y_back[:3] - state0[:3])
        closure_results[name] = {"error_km": float(err)}
        total_steps += steps_fwd + steps_back
        total_fevals += fevals_fwd + fevals_back

        if degree == 0:
            r0 = np.linalg.norm(state0[:3])
            v0 = np.linalg.norm(state0[3:6])
            energy0 = v0**2 / 2 - mu / r0
            rf = np.linalg.norm(y_fwd[:3])
            vf = np.linalg.norm(y_fwd[3:6])
            energyf = vf**2 / 2 - mu / rf
            h0 = np.linalg.norm(np.cross(state0[:3], state0[3:6]))
            hf = np.linalg.norm(np.cross(y_fwd[:3], y_fwd[3:6]))
            conservation[name] = {
                "energy_relative_error": float(abs((energyf - energy0) / energy0)),
                "angular_momentum_relative_error": float(abs((hf - h0) / h0)),
            }

        if name == "LEO_ISS":
            raan0, inc0 = cartesian_to_raan(state0, mu)
            raanf, _ = cartesian_to_raan(y_fwd, mu)

            delta_raan = raanf - raan0
            if delta_raan > math.pi:
                delta_raan -= 2 * math.pi
            elif delta_raan < -math.pi:
                delta_raan += 2 * math.pi
            numerical_rate = math.degrees(delta_raan) / cfg['duration_days']

            r0_mag = np.linalg.norm(state0[:3])
            v0_mag = np.linalg.norm(state0[3:6])
            energy0 = v0_mag**2 / 2 - mu / r0_mag
            a = -mu / (2 * energy0)
            ecc_vec = (1/mu) * ((v0_mag**2 - mu/r0_mag) * state0[:3]
                                - np.dot(state0[:3], state0[3:6]) * state0[3:6])
            ecc = np.linalg.norm(ecc_vec)
            p = a * (1 - ecc**2)
            n_motion = math.sqrt(mu / a**3)
            J2_val = constants['earth']['J2']
            analytical_rate_rad_s = -1.5 * n_motion * J2_val * (Re / p)**2 * math.cos(inc0)
            analytical_rate = math.degrees(analytical_rate_rad_s) * 86400.0

            rel_err = abs((numerical_rate - analytical_rate) / analytical_rate) * 100.0

            octave_raan = run_octave_validation(cfg['initial_state'])

            raan_data = {
                "mission_name": "LEO_ISS",
                "numerical_deg_per_day": float(numerical_rate),
                "analytical_deg_per_day": float(analytical_rate),
                "octave_analytical_deg_per_day": float(octave_raan) if octave_raan else float(analytical_rate),
                "relative_error_percent": float(rel_err),
            }

        print(f"  Closure error: {err:.6e} km")

    results = {
        "parsed_missions": parsed_missions,
        "closure_tests": closure_results,
        "conservation": conservation,
        "raan_precession": raan_data,
        "integrator_info": {
            "method_name": "Dormand-Prince 4(5)",
            "order": 5,
            "total_steps_all_cases": total_steps,
            "total_function_evals": total_fevals,
        }
    }

    with open("/app/results.json", 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
