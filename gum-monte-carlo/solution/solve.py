#!/usr/bin/env python3
"""
JCGM 101:2008 measurement uncertainty evaluation.
Reads model data from JSON (comparison loss) and SQLite (gauge block),
implements GUM and adaptive MCM, and performs GUM validation.
"""

import numpy as np
from scipy import stats
import json
import math
import sqlite3


# ---- Utility functions ----

def numerical_tolerance(u_y, ndig):
    """Compute numerical tolerance delta: 0.5 * 10^(floor(log10(u_y)) - ndig + 1)."""
    if u_y <= 0:
        return 0.0
    l = int(math.floor(math.log10(abs(u_y)))) - ndig + 1
    return 0.5 * 10.0 ** l


def sample_distribution(spec, n, rng):
    """Sample n values from the distribution described by spec dict."""
    dist = spec["distribution"]
    if dist == "gaussian":
        return rng.normal(spec["mean"], spec["std"], n)
    elif dist == "t":
        return spec["mean"] + spec["std"] * rng.standard_t(spec["dof"], n)
    elif dist == "rectangular":
        return rng.uniform(spec["lower"], spec["upper"], n)
    elif dist == "arcsine":
        a, b = spec["lower"], spec["upper"]
        u = rng.uniform(0.0, 1.0, n)
        return a + (b - a) * np.sin(np.pi / 2.0 * u) ** 2
    elif dist == "curvilinear_trapezoidal":
        a, b, d = spec["lower"], spec["upper"], spec["d"]
        a_prime = rng.uniform(a - d, a + d, n)
        b_prime = rng.uniform(b - d, b + d, n)
        u = rng.uniform(0.0, 1.0, n)
        return a_prime + (b_prime - a_prime) * u
    else:
        raise ValueError(f"Unknown distribution type: {dist}")


def gum_params(spec):
    """Extract GUM parameters (estimate, standard uncertainty, DOF) from a
    distribution spec. Returns (best_estimate, standard_uncertainty, dof)."""
    dist = spec["distribution"]
    if dist == "gaussian":
        return spec["mean"], spec["std"], float("inf")
    elif dist == "t":
        return spec["mean"], spec["std"], float(spec["dof"])
    elif dist == "rectangular":
        a, b = spec["lower"], spec["upper"]
        return (a + b) / 2.0, (b - a) / (2.0 * math.sqrt(3.0)), float("inf")
    elif dist == "arcsine":
        a, b = spec["lower"], spec["upper"]
        return (a + b) / 2.0, (b - a) / (2.0 * math.sqrt(2.0)), float("inf")
    elif dist == "curvilinear_trapezoidal":
        a, b = spec["lower"], spec["upper"]
        dof = float(spec.get("dof", float("inf")))
        return (a + b) / 2.0, (b - a) / (2.0 * math.sqrt(3.0)), dof
    else:
        raise ValueError(f"Unknown distribution type: {dist}")


def shortest_coverage_interval(sorted_vals, p):
    """Find the shortest coverage interval from sorted values."""
    n = len(sorted_vals)
    q = int(math.ceil(p * n))
    if q >= n:
        return float(sorted_vals[0]), float(sorted_vals[-1])
    widths = sorted_vals[q:] - sorted_vals[:n - q]
    j = int(np.argmin(widths))
    return float(sorted_vals[j]), float(sorted_vals[j + q])


# ---- GUM evaluation ----

def gum_evaluate(model_func, input_specs, input_names, coverage_prob, extra_args=None):
    """GUM uncertainty framework with first-order Taylor expansion."""
    params = [gum_params(input_specs[name]) for name in input_names]
    estimates = [p[0] for p in params]
    uncertainties = [p[1] for p in params]
    dofs = [p[2] for p in params]

    args = dict(zip(input_names, estimates))
    if extra_args:
        args.update(extra_args)
    y = model_func(**args)

    N = len(input_names)
    sensitivities = []
    for i in range(N):
        hi = max(abs(estimates[i]) * 1e-7, uncertainties[i] * 1e-4, 1e-15)
        args_plus = dict(zip(input_names, estimates))
        args_minus = dict(zip(input_names, estimates))
        args_plus[input_names[i]] = estimates[i] + hi
        args_minus[input_names[i]] = estimates[i] - hi
        if extra_args:
            args_plus.update(extra_args)
            args_minus.update(extra_args)
        ci = (model_func(**args_plus) - model_func(**args_minus)) / (2.0 * hi)
        sensitivities.append(ci)

    u_y_sq = sum(ci ** 2 * ui ** 2 for ci, ui in zip(sensitivities, uncertainties))
    u_y = math.sqrt(u_y_sq)

    nu_eff = None
    if u_y > 0:
        numerator = u_y ** 4
        denom = 0.0
        for ci, ui, vi in zip(sensitivities, uncertainties, dofs):
            contrib = abs(ci * ui)
            if vi < float("inf") and contrib > 0:
                denom += contrib ** 4 / vi
        if denom > 0:
            nu_eff = int(numerator / denom)
        else:
            nu_eff = None
    else:
        nu_eff = None

    p = coverage_prob
    if nu_eff is None or nu_eff > 10000:
        k = stats.norm.ppf((1.0 + p) / 2.0)
    else:
        k = stats.t.ppf((1.0 + p) / 2.0, nu_eff)
    Up = k * u_y

    return {
        "estimate": float(y),
        "uncertainty": float(u_y),
        "coverage_interval": [float(y - Up), float(y + Up)],
        "coverage_probability": float(p),
        "effective_dof": float(nu_eff) if nu_eff is not None else None,
    }


# ---- Adaptive MCM ----

def adaptive_mcm(model_func, input_specs, input_names, coverage_prob, ndig,
                 seed=42, extra_args=None, max_batches=200):
    """Adaptive Monte Carlo method with batched stabilization checking."""
    rng = np.random.default_rng(seed)
    p = coverage_prob
    J = int(math.ceil(100.0 / (1.0 - p)))
    M = max(J, 10_000)

    batch_estimates = []
    batch_uncertainties = []
    batch_lows = []
    batch_highs = []
    all_values = []

    for h in range(1, max_batches + 1):
        samples = {}
        for name in input_names:
            samples[name] = sample_distribution(input_specs[name], M, rng)

        args = {name: samples[name] for name in input_names}
        if extra_args:
            for k, v in extra_args.items():
                args[k] = v
        y_vals = model_func(**args)
        all_values.append(np.asarray(y_vals))

        batch_estimates.append(float(np.mean(y_vals)))
        batch_uncertainties.append(float(np.std(y_vals, ddof=0)))
        sorted_batch = np.sort(y_vals)
        bl, bh = shortest_coverage_interval(sorted_batch, p)
        batch_lows.append(bl)
        batch_highs.append(bh)

        if h < 2:
            continue

        arr_e = np.array(batch_estimates)
        arr_u = np.array(batch_uncertainties)
        arr_l = np.array(batch_lows)
        arr_h = np.array(batch_highs)

        s_y = np.std(arr_e, ddof=1) / math.sqrt(h)
        s_u = np.std(arr_u, ddof=1) / math.sqrt(h)
        s_low = np.std(arr_l, ddof=1) / math.sqrt(h)
        s_high = np.std(arr_h, ddof=1) / math.sqrt(h)

        all_arr = np.concatenate(all_values)
        u_est = float(np.std(all_arr, ddof=0))
        delta = numerical_tolerance(u_est, ndig)

        if delta > 0 and all(
            2.0 * s < delta for s in [s_y, s_u, s_low, s_high]
        ):
            break

    all_arr = np.concatenate(all_values)
    y_est = float(np.mean(all_arr))
    u_est = float(np.std(all_arr, ddof=0))
    sorted_all = np.sort(all_arr)
    y_low, y_high = shortest_coverage_interval(sorted_all, p)

    return {
        "estimate": y_est,
        "uncertainty": u_est,
        "shortest_coverage_interval": [y_low, y_high],
        "num_trials": int(len(all_arr)),
    }


def validate_gum(gum_result, mcm_result, ndig):
    """Compare GUM coverage interval against MCM shortest coverage interval."""
    gum_low, gum_high = gum_result["coverage_interval"]
    mcm_low, mcm_high = mcm_result["shortest_coverage_interval"]

    d_low = abs(gum_low - mcm_low)
    d_high = abs(gum_high - mcm_high)

    u_mcm = mcm_result["uncertainty"]
    delta = numerical_tolerance(u_mcm, ndig)

    validated = bool(d_low <= delta and d_high <= delta)

    return {
        "d_low": float(d_low),
        "d_high": float(d_high),
        "delta": float(delta),
        "validated": validated,
    }


# ---- Measurement models ----

def comparison_loss_model(X1, X2):
    return X1 ** 2 + X2 ** 2


def gauge_block_model(Ls, D, d1, d2, alpha_s, theta_0, Delta, delta_alpha, delta_theta, L_nom):
    return (
        Ls + D + d1 + d2
        - Ls * (delta_alpha * (theta_0 + Delta) + alpha_s * delta_theta)
        - L_nom
    )


# ---- SQLite data extraction ----

def load_gauge_block_from_db(db_path):
    """Extract gauge block model parameters from the SQLite calibration database.
    Type A inputs: compute mean, std uncertainty (s/sqrt(n)), dof (n-1) from raw observations.
    Type B inputs: read distribution parameters directly."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Model metadata
    model = conn.execute("SELECT * FROM models WHERE model_id='gauge_block'").fetchone()
    nominal_length = model["nominal_length_nm"]
    coverage_prob = model["coverage_probability"]
    ndig = model["ndig"]

    # Input variables
    variables = conn.execute(
        "SELECT * FROM input_variables WHERE model_id='gauge_block' ORDER BY var_order"
    ).fetchall()

    input_specs = {}
    input_names = []

    for var in variables:
        name = var["var_name"]
        # Normalize DB name to match model function parameter names
        param_name = name
        if name == "L_s":
            param_name = "Ls"
        input_names.append(param_name)

        if var["eval_type"] == "type_a":
            # Compute from raw measurement observations
            obs = conn.execute(
                "SELECT value_nm FROM measurement_observations WHERE quantity=? ORDER BY trial_number",
                (name if name != "L_s" else name,)
            ).fetchall()
            values = [row["value_nm"] for row in obs]
            n = len(values)
            mean_val = sum(values) / n
            s_sq = sum((x - mean_val) ** 2 for x in values) / (n - 1)
            s = math.sqrt(s_sq)
            u = s / math.sqrt(n)  # standard uncertainty of the mean
            dof = n - 1

            input_specs[param_name] = {
                "distribution": "t",
                "mean": mean_val,
                "std": u,
                "dof": dof,
            }
        else:
            # Type B: read from distribution table
            dist_row = conn.execute(
                "SELECT * FROM type_b_distributions WHERE var_id=?",
                (var["id"],)
            ).fetchone()

            dist_type = dist_row["distribution"]
            spec = {"distribution": dist_type}

            if dist_type == "gaussian":
                spec["mean"] = dist_row["param_mean"]
                spec["std"] = dist_row["param_std"]
            elif dist_type == "t":
                spec["mean"] = dist_row["param_mean"]
                spec["std"] = dist_row["param_std"]
                spec["dof"] = dist_row["param_dof"]
            elif dist_type == "rectangular":
                spec["lower"] = dist_row["param_lower"]
                spec["upper"] = dist_row["param_upper"]
            elif dist_type == "arcsine":
                spec["lower"] = dist_row["param_lower"]
                spec["upper"] = dist_row["param_upper"]
            elif dist_type == "curvilinear_trapezoidal":
                spec["lower"] = dist_row["param_lower"]
                spec["upper"] = dist_row["param_upper"]
                spec["d"] = dist_row["param_d"]
                spec["dof"] = dist_row["param_dof"]

            input_specs[param_name] = spec

    conn.close()
    return input_specs, input_names, nominal_length, coverage_prob, ndig


# ---- Processing ----

def process_comparison_loss():
    with open("/app/models/comparison_loss.json") as f:
        spec = json.load(f)

    input_names = ["X1", "X2"]
    results = {}

    for case in spec["cases"]:
        case_id = case["case_id"]
        p = case["coverage_probability"]
        ndig = case["ndig"]

        print(f"  Comparison loss {case_id}...")
        gum = gum_evaluate(comparison_loss_model, case["inputs"], input_names, p)
        mcm = adaptive_mcm(
            comparison_loss_model, case["inputs"], input_names, p, ndig, seed=42
        )
        val = validate_gum(gum, mcm, ndig)
        results[case_id] = {"gum": gum, "mcm": mcm, "validation": val}

    return results


def process_gauge_block():
    input_specs, input_names, L_nom, p, ndig = load_gauge_block_from_db("/app/calibration.db")
    extra_args = {"L_nom": L_nom}

    print("  Gauge block GUM...")
    gum = gum_evaluate(gauge_block_model, input_specs, input_names, p, extra_args)

    print("  Gauge block MCM...")
    mcm = adaptive_mcm(
        gauge_block_model, input_specs, input_names, p, ndig,
        seed=42, extra_args=extra_args,
    )

    val = validate_gum(gum, mcm, ndig)
    return {"gum": gum, "mcm": mcm, "validation": val}


def main():
    results = {}

    print("Processing comparison loss model...")
    results["comparison_loss"] = process_comparison_loss()

    print("Processing gauge block model...")
    results["gauge_block"] = process_gauge_block()

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
