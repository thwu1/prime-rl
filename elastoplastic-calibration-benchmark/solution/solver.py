#!/usr/bin/env python3
"""
Elasto-plastic constitutive model calibration and benchmark evaluation.

"""

import json
import csv
import math
import os
import numpy as np
from scipy.optimize import curve_fit, minimize

DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ============================================================
# Model definitions
# ============================================================

def swift_model(eps_p, K, eps_0, n):
    return K * (eps_0 + eps_p) ** n


def voce_model(eps_p, sigma_sat, sigma_y, theta):
    return sigma_sat - (sigma_sat - sigma_y) * np.exp(-theta * eps_p)


def hockett_sherby_model(eps_p, sigma_sat, sigma_i, m, n):
    return sigma_sat - (sigma_sat - sigma_i) * np.exp(-m * eps_p ** n)


def eval_model_scalar(model_name, params, eps):
    if model_name == "swift":
        return params["K"] * (params["eps_0"] + eps) ** params["n"]
    elif model_name == "voce":
        return params["sigma_sat"] - (params["sigma_sat"] - params["sigma_y"]) * math.exp(-params["theta"] * eps)
    else:
        return params["sigma_sat"] - (params["sigma_sat"] - params["sigma_i"]) * math.exp(-params["m"] * eps ** params["n"])


# ============================================================
# 1. Fit hardening laws
# ============================================================

def get_calibration_data():
    tensile = load_json(os.path.join(DATA_DIR, "tensile_tests.json"))["0"]
    bulge = load_json(os.path.join(DATA_DIR, "bulge_test.json"))
    strains = np.array([d["plastic_strain"] for d in tensile] +
                       [d["equiv_strain"] for d in bulge])
    stresses = np.array([d["true_stress"] for d in tensile] +
                        [d["equiv_stress"] for d in bulge])
    return strains, stresses


def fit_hardening_laws():
    """Fit Swift, Voce, and Hockett-Sherby to combined tensile+bulge data."""
    strains, stresses = get_calibration_data()

    # Swift fit
    p_sw, _ = curve_fit(
        swift_model, strains, stresses,
        p0=[1300.0, 0.005, 0.15],
        bounds=([800, 1e-6, 0.01], [2500, 0.1, 0.5]),
        maxfev=10000
    )

    # Voce fit
    p_vo, _ = curve_fit(
        voce_model, strains, stresses,
        p0=[950.0, 480.0, 15.0],
        bounds=([800, 300, 1], [1200, 600, 100]),
        maxfev=10000
    )

    # Hockett-Sherby fit
    p_hs, _ = curve_fit(
        hockett_sherby_model, strains, stresses,
        p0=[1050.0, 480.0, 8.0, 0.65],
        bounds=([900, 300, 1, 0.1], [1200, 600, 30, 2.0]),
        maxfev=10000
    )

    params = {
        "swift": {"K": float(p_sw[0]), "eps_0": float(p_sw[1]), "n": float(p_sw[2])},
        "voce": {"sigma_sat": float(p_vo[0]), "sigma_y": float(p_vo[1]), "theta": float(p_vo[2])},
        "hockett_sherby": {"sigma_sat": float(p_hs[0]), "sigma_i": float(p_hs[1]),
                           "m": float(p_hs[2]), "n": float(p_hs[3])}
    }

    with open(os.path.join(OUTPUT_DIR, "fitted_parameters.json"), "w") as f:
        json.dump(params, f, indent=2)

    return params


# ============================================================
# 2. Evaluate flow curves
# ============================================================

def evaluate_flow_curves(params):
    """Evaluate fitted models at specified strain points."""
    strains = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
    eps = np.array(strains)

    p = params["swift"]
    swift_vals = [float(v) for v in swift_model(eps, p["K"], p["eps_0"], p["n"])]

    p = params["voce"]
    voce_vals = [float(v) for v in voce_model(eps, p["sigma_sat"], p["sigma_y"], p["theta"])]

    p = params["hockett_sherby"]
    hs_vals = [float(v) for v in hockett_sherby_model(eps, p["sigma_sat"], p["sigma_i"], p["m"], p["n"])]

    result = {
        "strains": strains,
        "swift": swift_vals,
        "voce": voce_vals,
        "hockett_sherby": hs_vals
    }

    with open(os.path.join(OUTPUT_DIR, "flow_curves.json"), "w") as f:
        json.dump(result, f, indent=2)


# ============================================================
# 3. Blended hardening model
# ============================================================

def compute_blended_model(params):
    """Find optimal convex combination of hardening models minimizing RMSE."""
    strains, stresses = get_calibration_data()

    # Precompute individual model predictions at calibration data points
    p_sw = params["swift"]
    p_vo = params["voce"]
    p_hs = params["hockett_sherby"]

    swift_pred = np.array([swift_model(e, p_sw["K"], p_sw["eps_0"], p_sw["n"]) for e in strains])
    voce_pred = np.array([voce_model(e, p_vo["sigma_sat"], p_vo["sigma_y"], p_vo["theta"]) for e in strains])
    hs_pred = np.array([hockett_sherby_model(e, p_hs["sigma_sat"], p_hs["sigma_i"], p_hs["m"], p_hs["n"]) for e in strains])

    actual = np.array(stresses)

    def objective(w2):
        # w2 = [w_swift, w_voce], w_hs = 1 - w_swift - w_voce
        w_hs = 1.0 - w2[0] - w2[1]
        blend = w2[0] * swift_pred + w2[1] * voce_pred + w_hs * hs_pred
        return np.sqrt(np.mean((blend - actual) ** 2))

    constraints = [
        {"type": "ineq", "fun": lambda w: w[0]},
        {"type": "ineq", "fun": lambda w: w[1]},
        {"type": "ineq", "fun": lambda w: 1.0 - w[0] - w[1]},
    ]

    opt_result = minimize(objective, [0.0, 0.0], method="SLSQP",
                          constraints=constraints, bounds=[(0, 1), (0, 1)])

    w_swift = float(opt_result.x[0])
    w_voce = float(opt_result.x[1])
    w_hs = 1.0 - w_swift - w_voce

    # Evaluate at standard strain points
    eval_strains = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
    blend_stresses = []
    for eps in eval_strains:
        s_sw = eval_model_scalar("swift", params["swift"], eps)
        s_vo = eval_model_scalar("voce", params["voce"], eps)
        s_hs = eval_model_scalar("hockett_sherby", params["hockett_sherby"], eps)
        blend_stresses.append(round(w_swift * s_sw + w_voce * s_vo + w_hs * s_hs, 4))

    result = {
        "weights": {
            "swift": round(w_swift, 8),
            "voce": round(w_voce, 8),
            "hockett_sherby": round(w_hs, 8)
        },
        "rmse": round(float(opt_result.fun), 8),
        "stresses_at_eval_strains": blend_stresses
    }

    with open(os.path.join(OUTPUT_DIR, "blended_model.json"), "w") as f:
        json.dump(result, f, indent=2)


# ============================================================
# 4. Hill48 yield criterion
# ============================================================

def calibrate_hill48():
    """Calibrate Hill48 from R-values using associated flow rule."""
    mat = load_json(os.path.join(DATA_DIR, "material_params.json"))
    r0 = mat["r_values"]["0"]
    r45 = mat["r_values"]["45"]
    r90 = mat["r_values"]["90"]

    G = 1.0 / (1.0 + r0)
    H = r0 / (1.0 + r0)
    F = r0 / (r90 * (1.0 + r0))
    N = (r0 + r90) * (1.0 + 2.0 * r45) / (2.0 * r90 * (1.0 + r0))

    hill48 = {"F": F, "G": G, "H": H, "N": N}

    with open(os.path.join(OUTPUT_DIR, "hill48_parameters.json"), "w") as f:
        json.dump(hill48, f, indent=2)

    return hill48


# ============================================================
# 5. Yield locus
# ============================================================

def compute_yield_locus(hill48):
    """Compute Hill48 yield locus in normalized principal stress space."""
    F, G, H = hill48["F"], hill48["G"], hill48["H"]

    rows = []
    for deg in range(360):
        theta = math.radians(deg)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        denom = F * sin_t**2 + G * cos_t**2 + H * (cos_t - sin_t)**2

        if denom <= 0:
            r = 0.0
        else:
            r = 1.0 / math.sqrt(denom)

        s1 = r * cos_t
        s2 = r * sin_t
        rows.append({"angle": deg, "sigma_1": round(s1, 8), "sigma_2": round(s2, 8)})

    with open(os.path.join(OUTPUT_DIR, "yield_locus.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["angle", "sigma_1", "sigma_2"])
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# 6. Directional properties
# ============================================================

def compute_directional_properties(hill48):
    """Compute anisotropic yield stress and R-value predictions from Hill48."""
    mat = load_json(os.path.join(DATA_DIR, "material_params.json"))
    F, G, H, N = hill48["F"], hill48["G"], hill48["H"], hill48["N"]

    angles = [0.0, 22.5, 45.0, 67.5, 90.0]
    angle_keys = ["0", "22.5", "45", "67.5", "90"]
    measured_r = mat["r_values"]

    normalized_yield = []
    predicted_r = []
    r_errors = []

    for i, angle_deg in enumerate(angles):
        theta = math.radians(angle_deg)
        s2 = math.sin(theta) ** 2
        c2 = math.cos(theta) ** 2

        denom_term = F * s2**2 + G * c2**2 + H * (c2 - s2)**2 + 2.0 * N * s2 * c2
        sigma_ratio = math.sqrt((G + H) / denom_term)
        normalized_yield.append(round(sigma_ratio, 8))

        numerator = H + (2.0 * N - F - G - 4.0 * H) * s2 * c2
        denominator = F * s2 + G * c2
        r_val = numerator / denominator if denominator > 1e-10 else 0.0
        predicted_r.append(round(r_val, 8))

        meas = measured_r[angle_keys[i]]
        r_errors.append(round(abs(r_val - meas), 8))

    result = {
        "angles": angles,
        "normalized_yield_stress": normalized_yield,
        "predicted_r_values": predicted_r,
        "r_value_errors": r_errors
    }

    with open(os.path.join(OUTPUT_DIR, "directional_properties.json"), "w") as f:
        json.dump(result, f, indent=2)


# ============================================================
# 7. Anisotropic flow curves (cross-validation)
# ============================================================

def compute_anisotropic_flow_curves(params, hill48):
    """Predict flow curves at 45 and 90 deg using Hill48 + best hardening model."""
    tensile = load_json(os.path.join(DATA_DIR, "tensile_tests.json"))
    F, G, H, N = hill48["F"], hill48["G"], hill48["H"], hill48["N"]

    # Determine best model (lowest calibration RMSE)
    cal_strains, cal_stresses = get_calibration_data()
    model_rmses = {}
    for model_name in ["swift", "voce", "hockett_sherby"]:
        pred = [eval_model_scalar(model_name, params[model_name], float(e)) for e in cal_strains]
        model_rmses[model_name] = math.sqrt(
            sum((p - a) ** 2 for p, a in zip(pred, cal_stresses)) / len(cal_stresses)
        )
    best_model = min(model_rmses, key=model_rmses.get)
    best_params = params[best_model]

    result = {
        "best_model": best_model,
        "yield_stress_ratios": {},
    }

    for angle_str, angle_deg in [("45", 45.0), ("90", 90.0)]:
        theta = math.radians(angle_deg)
        sin2 = math.sin(theta) ** 2
        cos2 = math.cos(theta) ** 2
        sin4 = sin2 ** 2
        cos4 = cos2 ** 2

        A_theta = F * sin4 + G * cos4 + H * (cos2 - sin2) ** 2 + 2.0 * N * sin2 * cos2
        ratio = math.sqrt((G + H) / A_theta)
        result["yield_stress_ratios"][angle_str] = round(ratio, 8)

        # Load measured tensile data at this orientation
        meas_data = tensile[angle_str]
        meas_strains = [d["plastic_strain"] for d in meas_data]
        meas_stresses = [d["true_stress"] for d in meas_data]

        result[f"measured_{angle_str}_strain"] = meas_strains
        result[f"measured_{angle_str}_stress"] = meas_stresses

        # Predict: sigma_theta(eps_axial) = ratio * sigma_model(ratio * eps_axial)
        predicted = []
        for eps_axial in meas_strains:
            eps_equiv = ratio * eps_axial
            sigma_pred = ratio * eval_model_scalar(best_model, best_params, eps_equiv)
            predicted.append(round(sigma_pred, 4))

        result[f"predicted_{angle_str}"] = predicted

        # RMSE against measured
        r_val = math.sqrt(
            sum((p - m) ** 2 for p, m in zip(predicted, meas_stresses)) / len(meas_stresses)
        )
        result[f"rmse_{angle_str}"] = round(r_val, 4)

    with open(os.path.join(OUTPUT_DIR, "anisotropic_flow_curves.json"), "w") as f:
        json.dump(result, f, indent=2)


# ============================================================
# 8. Benchmark scoring
# ============================================================

def compute_rmse(predicted, actual):
    n = len(actual)
    return math.sqrt(sum((p - a) ** 2 for p, a in zip(predicted, actual)) / n)


def compute_benchmark_scores():
    """Implement normalized RMSE benchmark methodology."""
    gt = load_json(os.path.join(DATA_DIR, "ground_truth.json"))
    subs = load_json(os.path.join(DATA_DIR, "submissions.json"))

    configs = ["70", "110", "230"]
    teams = sorted(subs.keys())
    metrics = ["force", "major_strain", "minor_strain"]

    # Step 1: Compute raw RMSE per team per config per metric
    raw_rmse = {}
    for team in teams:
        raw_rmse[team] = {}
        for config in configs:
            gt_c = gt[config]
            sub_c = subs[team][config]

            force_rmse = compute_rmse(sub_c["force"], gt_c["force"])

            major_xz = compute_rmse(sub_c["major_strain_xz"], gt_c["major_strain_xz"])
            major_yz = compute_rmse(sub_c["major_strain_yz"], gt_c["major_strain_yz"])
            major_rmse = (major_xz + major_yz) / 2.0

            minor_xz = compute_rmse(sub_c["minor_strain_xz"], gt_c["minor_strain_xz"])
            minor_yz = compute_rmse(sub_c["minor_strain_yz"], gt_c["minor_strain_yz"])
            minor_rmse = (minor_xz + minor_yz) / 2.0

            raw_rmse[team][config] = {
                "force": force_rmse,
                "major_strain": major_rmse,
                "minor_strain": minor_rmse
            }

    # Step 2: Normalization factors (mean RMSE across teams per config+metric)
    norm_factors = {}
    for config in configs:
        norm_factors[config] = {}
        for metric in metrics:
            mean_val = sum(raw_rmse[t][config][metric] for t in teams) / len(teams)
            norm_factors[config][metric] = mean_val

    # Step 3: Total normalized RMSE per metric (average over configs)
    total_per_metric = {}
    for team in teams:
        total_per_metric[team] = {}
        for metric in metrics:
            avg = sum(
                raw_rmse[team][config][metric] / norm_factors[config][metric]
                for config in configs
            ) / 3.0
            total_per_metric[team][metric] = avg

    # Step 4: Overall total score
    team_scores = {}
    for team in teams:
        team_scores[team] = sum(total_per_metric[team][m] for m in metrics)

    # Step 5: Rank by total score (ascending)
    ranking = sorted(teams, key=lambda t: team_scores[t])

    result = {
        "normalization_factors": norm_factors,
        "team_scores": {t: round(v, 6) for t, v in team_scores.items()},
        "ranking": ranking
    }

    with open(os.path.join(OUTPUT_DIR, "benchmark_scores.json"), "w") as f:
        json.dump(result, f, indent=2)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("Fitting hardening laws...")
    params = fit_hardening_laws()

    print("Evaluating flow curves...")
    evaluate_flow_curves(params)

    print("Computing blended model...")
    compute_blended_model(params)

    print("Calibrating Hill48...")
    hill48 = calibrate_hill48()

    print("Computing yield locus...")
    compute_yield_locus(hill48)

    print("Computing directional properties...")
    compute_directional_properties(hill48)

    print("Computing anisotropic flow curves (cross-validation)...")
    compute_anisotropic_flow_curves(params, hill48)

    print("Computing benchmark scores...")
    compute_benchmark_scores()

    print("Done. All outputs written to /app/output/")
