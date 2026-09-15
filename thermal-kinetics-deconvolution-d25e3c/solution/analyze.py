#!/usr/bin/env python3
"""
Multi-step thermal kinetics deconvolution and parameter recovery.


Pipeline:
1. Load multi-heating-rate TGA data
2. Deconvolve overlapping reactions via derivative peak fitting
3. Recover kinetic parameters (E_a, A) using Kissinger + Friedman methods
4. Predict conversion at unseen heating rate via ODE integration
"""

import json
import glob
import os
import re

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize, curve_fit
from scipy.signal import savgol_filter
from scipy.stats import linregress

R = 8.314  # Gas constant J/(mol*K)


def load_data(data_dir="/app/data"):
    """Load all TGA CSV files and return sorted by heating rate."""
    files = sorted(glob.glob(os.path.join(data_dir, "tga_beta_*.csv")))
    datasets = []
    for fpath in files:
        # Extract heating rate from filename
        match = re.search(r"beta_(\d+)", os.path.basename(fpath))
        beta = int(match.group(1))  # K/min
        data = np.loadtxt(fpath, delimiter=",", skiprows=1)
        T = data[:, 0]
        alpha = data[:, 1]
        datasets.append((beta, T, alpha))
    datasets.sort(key=lambda x: x[0])
    return datasets


def smooth_derivative(T, alpha, window=51, polyorder=3):
    """Compute smoothed dα/dT."""
    if len(alpha) < window:
        window = len(alpha) // 2 * 2 + 1
    alpha_smooth = savgol_filter(alpha, window, polyorder)
    dalpha_dT = np.gradient(alpha_smooth, T)
    dalpha_dT_smooth = savgol_filter(dalpha_dT, window, polyorder)
    return dalpha_dT_smooth


def asymmetric_double_peak(T, A1, mu1, sigma1, asym1, A2, mu2, sigma2, asym2):
    """Sum of two Fraser-Suzuki (asymmetric Gaussian) peaks."""
    def fraser_suzuki(T, A, mu, sigma, asym):
        z = (T - mu) / sigma
        # Asymmetric Gaussian approximation
        sigma_eff = sigma * np.where(T < mu, 1.0 / (1 + asym), 1.0 * (1 + asym))
        return A * np.exp(-0.5 * ((T - mu) / sigma_eff) ** 2)

    return fraser_suzuki(T, A1, mu1, sigma1, asym1) + fraser_suzuki(T, A2, mu2, sigma2, asym2)


def find_peaks_in_derivative(T, dalpha_dT):
    """Find approximate peak positions and heights in derivative curve."""
    # Find local maxima
    peaks = []
    for i in range(5, len(dalpha_dT) - 5):
        if dalpha_dT[i] == max(dalpha_dT[i-5:i+6]) and dalpha_dT[i] > 0.001:
            peaks.append((T[i], dalpha_dT[i]))

    if len(peaks) < 2:
        # Try finding a shoulder - use second derivative
        d2 = np.gradient(dalpha_dT, T)
        d2_smooth = savgol_filter(d2, 51, 3)
        # Find zero crossings of second derivative (inflection points)
        zero_crossings = []
        for i in range(1, len(d2_smooth)):
            if d2_smooth[i-1] * d2_smooth[i] < 0:
                zero_crossings.append(T[i])

        if peaks:
            main_peak_T = peaks[0][0]
            # The shoulder is near an inflection point
            for zc in zero_crossings:
                if abs(zc - main_peak_T) > 15:
                    idx = np.argmin(np.abs(T - zc))
                    peaks.append((T[idx], dalpha_dT[idx]))
                    break

    peaks.sort(key=lambda x: x[0])
    return peaks[:2] if len(peaks) >= 2 else peaks


def deconvolve_reactions(datasets):
    """
    Deconvolve two overlapping reactions from the composite TGA data.
    Returns weight fractions and per-reaction conversion curves.
    """
    # Strategy: fit the dα/dT curve to sum of two asymmetric peaks
    # across all heating rates simultaneously to get robust weight fractions

    weight_fracs = []
    all_peak_temps = {1: [], 2: []}

    for beta, T, alpha in datasets:
        dalpha_dT = smooth_derivative(T, alpha, window=71, polyorder=3)

        peaks = find_peaks_in_derivative(T, dalpha_dT)

        if len(peaks) < 2:
            # Use global optimization to find two peaks
            peak_idx = np.argmax(dalpha_dT)
            mu_guess = T[peak_idx]
            A_guess = dalpha_dT[peak_idx]
            # Assume second peak is about 40-60K higher
            mu2_guess = mu_guess + 50
            idx2 = np.argmin(np.abs(T - mu2_guess))
            A2_guess = dalpha_dT[idx2] if idx2 < len(dalpha_dT) else A_guess * 0.5
            peaks = [(mu_guess, A_guess), (mu2_guess, A2_guess)]

        mu1_init, A1_init = peaks[0]
        mu2_init, A2_init = peaks[1]

        # Fit double asymmetric peak to the derivative
        mask = dalpha_dT > 0.0005
        T_fit = T[mask]
        y_fit = dalpha_dT[mask]

        try:
            p0 = [A1_init, mu1_init, 15, 0.3, A2_init, mu2_init, 15, 0.3]
            bounds_lo = [0, mu1_init - 30, 3, -2, 0, mu2_init - 30, 3, -2]
            bounds_hi = [0.1, mu1_init + 30, 60, 2, 0.1, mu2_init + 30, 60, 2]

            popt, _ = curve_fit(asymmetric_double_peak, T_fit, y_fit, p0=p0,
                                bounds=(bounds_lo, bounds_hi), maxfev=20000)

            A1_fit, mu1_fit, sig1, asym1, A2_fit, mu2_fit, sig2, asym2 = popt

            # Integrate each peak to get weight fractions
            peak1_curve = asymmetric_double_peak(T, A1_fit, mu1_fit, sig1, asym1, 0, 0, 1, 0)
            peak2_curve = asymmetric_double_peak(T, 0, 0, 1, 0, A2_fit, mu2_fit, sig2, asym2)

            w1_est = np.trapz(peak1_curve, T)
            w2_est = np.trapz(peak2_curve, T)
            total_w = w1_est + w2_est

            if total_w > 0:
                weight_fracs.append(w1_est / total_w)

            all_peak_temps[1].append(mu1_fit)
            all_peak_temps[2].append(mu2_fit)

        except (RuntimeError, ValueError):
            # Fallback: use the peak positions directly
            all_peak_temps[1].append(mu1_init)
            all_peak_temps[2].append(mu2_init)

    # Average weight fraction across heating rates
    if weight_fracs:
        w1 = np.median(weight_fracs)
    else:
        w1 = 0.55  # fallback

    w1 = np.clip(w1, 0.1, 0.9)
    w2 = 1.0 - w1

    return w1, w2, all_peak_temps


def kissinger_analysis(peak_temps, heating_rates):
    """
    Apply Kissinger method: plot ln(β/T_p²) vs 1/T_p.
    Returns E_a (J/mol) and A (1/s).
    """
    T_p = np.array(peak_temps)
    beta = np.array(heating_rates) / 60.0  # K/s

    x = 1.0 / T_p
    y = np.log(beta / T_p ** 2)

    slope, intercept, r_value, _, _ = linregress(x, y)

    E_a = -R * slope
    A = np.exp(intercept + np.log(E_a / R))

    return E_a, A, r_value ** 2


def reconstruct_individual_conversions(datasets, w1, w2, E_a1_init, A1_init, E_a2_init, A2_init):
    """
    Given initial parameter estimates and weight fractions, reconstruct
    individual conversion curves by fitting the forward model to data.
    Returns refined parameters.
    """
    def forward_model(params, beta_Kmin, T_eval):
        E_a1, ln_A1, E_a2, ln_A2 = params
        A1 = np.exp(ln_A1)
        A2 = np.exp(ln_A2)
        beta = beta_Kmin / 60.0

        def ode(T, y):
            a1, a2 = y
            k1 = A1 * np.exp(-E_a1 / (R * T))
            k2 = A2 * np.exp(-E_a2 / (R * T))
            da1 = (k1 / beta) * max(0, 1 - a1)
            da2 = (k2 / beta) * max(0, 1 - a2)
            return [da1, da2]

        sol = solve_ivp(ode, [T_eval[0], T_eval[-1]], [0.0, 0.0],
                        t_eval=T_eval, method='RK45', rtol=1e-10, atol=1e-12,
                        max_step=1.0)
        alpha1 = np.clip(sol.y[0], 0, 1)
        alpha2 = np.clip(sol.y[1], 0, 1)
        return w1 * alpha1 + w2 * alpha2

    def objective(params):
        total_err = 0.0
        for beta, T, alpha in datasets:
            try:
                pred = forward_model(params, beta, T)
                residuals = alpha - pred
                total_err += np.sum(residuals ** 2)
            except Exception:
                total_err += 1e10
        return total_err

    # Initial parameters
    p0 = [E_a1_init, np.log(A1_init), E_a2_init, np.log(A2_init)]

    # Optimize
    result = minimize(objective, p0, method='Nelder-Mead',
                      options={'maxiter': 5000, 'xatol': 100, 'fatol': 1e-8})

    E_a1_opt, ln_A1_opt, E_a2_opt, ln_A2_opt = result.x
    A1_opt = np.exp(ln_A1_opt)
    A2_opt = np.exp(ln_A2_opt)

    return E_a1_opt, A1_opt, E_a2_opt, A2_opt


def refine_all_params(datasets, w1_init, E_a1_init, A1_init, E_a2_init, A2_init):
    """
    Joint optimization of all parameters including weight fractions.
    """
    def forward_model(params, beta_Kmin, T_eval):
        E_a1, ln_A1, E_a2, ln_A2, w1 = params
        A1 = np.exp(ln_A1)
        A2 = np.exp(ln_A2)
        w2 = 1.0 - w1
        beta = beta_Kmin / 60.0

        def ode(T, y):
            a1, a2 = y
            k1 = A1 * np.exp(-E_a1 / (R * T))
            k2 = A2 * np.exp(-E_a2 / (R * T))
            da1 = (k1 / beta) * max(0, 1 - a1)
            da2 = (k2 / beta) * max(0, 1 - a2)
            return [da1, da2]

        sol = solve_ivp(ode, [T_eval[0], T_eval[-1]], [0.0, 0.0],
                        t_eval=T_eval, method='RK45', rtol=1e-10, atol=1e-12,
                        max_step=1.0)
        alpha1 = np.clip(sol.y[0], 0, 1)
        alpha2 = np.clip(sol.y[1], 0, 1)
        return w1 * alpha1 + w2 * alpha2

    def objective(params):
        # Enforce constraints via penalty
        E_a1, ln_A1, E_a2, ln_A2, w1 = params
        if E_a1 <= 0 or E_a2 <= 0 or E_a1 >= E_a2:
            return 1e15
        if w1 <= 0.05 or w1 >= 0.95:
            return 1e15

        total_err = 0.0
        for beta, T, alpha in datasets:
            try:
                # Subsample for speed
                step = max(1, len(T) // 500)
                T_sub = T[::step]
                alpha_sub = alpha[::step]
                pred = forward_model(params, beta, T_sub)
                residuals = alpha_sub - pred
                total_err += np.sum(residuals ** 2)
            except Exception:
                total_err += 1e10
        return total_err

    p0 = [E_a1_init, np.log(A1_init), E_a2_init, np.log(A2_init), w1_init]

    result = minimize(objective, p0, method='Nelder-Mead',
                      options={'maxiter': 20000, 'xatol': 50, 'fatol': 1e-10,
                               'adaptive': True})

    E_a1, ln_A1, E_a2, ln_A2, w1 = result.x
    return E_a1, np.exp(ln_A1), E_a2, np.exp(ln_A2), w1


def predict_conversion(E_a1, A1, E_a2, A2, w1, beta_Kmin, T_predict):
    """Predict total conversion at given heating rate and temperatures."""
    w2 = 1.0 - w1
    beta = beta_Kmin / 60.0
    T_start = 350.0
    T_end = max(T_predict) + 50.0
    T_eval = np.linspace(T_start, T_end, 5000)

    def ode(T, y):
        a1, a2 = y
        k1 = A1 * np.exp(-E_a1 / (R * T))
        k2 = A2 * np.exp(-E_a2 / (R * T))
        da1 = (k1 / beta) * max(0, 1 - a1)
        da2 = (k2 / beta) * max(0, 1 - a2)
        return [da1, da2]

    sol = solve_ivp(ode, [T_start, T_end], [0.0, 0.0],
                    t_eval=T_eval, method='RK45', rtol=1e-12, atol=1e-14,
                    max_step=0.5)

    alpha1 = np.clip(sol.y[0], 0, 1)
    alpha2 = np.clip(sol.y[1], 0, 1)
    total = w1 * alpha1 + w2 * alpha2

    predictions = {}
    for T_p in T_predict:
        idx = np.argmin(np.abs(T_eval - T_p))
        predictions[f"{T_p:.1f}"] = float(np.clip(total[idx], 0, 1))

    return predictions


def main():
    print("Loading TGA data...")
    datasets = load_data()
    heating_rates = [d[0] for d in datasets]
    print(f"Loaded {len(datasets)} datasets at heating rates: {heating_rates} K/min")

    print("\nDeconvolving reactions via derivative peak analysis...")
    w1, w2, peak_temps = deconvolve_reactions(datasets)
    print(f"Initial weight fractions: w1={w1:.4f}, w2={w2:.4f}")

    # Kissinger analysis for each reaction
    print("\nKissinger analysis for initial E_a estimates...")
    if len(peak_temps[1]) == len(heating_rates) and len(peak_temps[2]) == len(heating_rates):
        E_a1_kiss, A1_kiss, r2_1 = kissinger_analysis(peak_temps[1], heating_rates)
        E_a2_kiss, A2_kiss, r2_2 = kissinger_analysis(peak_temps[2], heating_rates)
        print(f"Reaction 1: E_a={E_a1_kiss/1000:.1f} kJ/mol, A={A1_kiss:.2e} 1/s, R²={r2_1:.4f}")
        print(f"Reaction 2: E_a={E_a2_kiss/1000:.1f} kJ/mol, A={A2_kiss:.2e} 1/s, R²={r2_2:.4f}")
    else:
        print("Warning: Insufficient peak data, using fallback estimates")
        E_a1_kiss = 140000.0
        A1_kiss = 1e12
        E_a2_kiss = 180000.0
        A2_kiss = 1e14

    # Refine via ODE fitting
    print("\nRefining parameters via ODE fitting...")
    E_a1, A1, E_a2, A2, w1 = refine_all_params(
        datasets, w1, E_a1_kiss, A1_kiss, E_a2_kiss, A2_kiss)
    w2 = 1.0 - w1

    # Ensure ordering
    if E_a1 > E_a2:
        E_a1, E_a2 = E_a2, E_a1
        A1, A2 = A2, A1
        w1, w2 = w2, w1

    print(f"\nFinal parameters:")
    print(f"Reaction 1: E_a={E_a1/1000:.2f} kJ/mol, A={A1:.3e} 1/s, w={w1:.4f}")
    print(f"Reaction 2: E_a={E_a2/1000:.2f} kJ/mol, A={A2:.3e} 1/s, w={w2:.4f}")

    # Predict at beta=7.5 K/min
    print("\nPredicting conversion at beta=7.5 K/min...")
    T_predict = [480.0, 520.0, 540.0, 560.0, 580.0, 620.0, 700.0]
    predictions = predict_conversion(E_a1, A1, E_a2, A2, w1, 7.5, T_predict)
    for T_p, val in sorted(predictions.items(), key=lambda x: float(x[0])):
        print(f"  T={T_p} K: alpha={val:.6f}")

    # Write results
    results = {
        "reaction_1": {
            "activation_energy_J_mol": float(E_a1),
            "pre_exponential_factor_per_s": float(A1),
            "weight_fraction": float(w1)
        },
        "reaction_2": {
            "activation_energy_J_mol": float(E_a2),
            "pre_exponential_factor_per_s": float(A2),
            "weight_fraction": float(w2)
        },
        "predictions_beta_7_5": predictions
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
