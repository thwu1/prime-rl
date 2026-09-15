"""
Rough Heston calibration and pricing pipeline.

Entry point: run this script to calibrate rough Heston parameters
from SPX implied volatility data and compute model implied volatilities.
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from scipy import optimize

# Ensure sibling modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from swap_estimation import var_swap_robust, gamma_swap_robust
from special_functions import norm_lev_contract_rheston
from characteristic_fn import impvol_rheston
from fwd_curve import xi_curve_piecewise


def main():
    # Load SPX implied vol data
    df_spx = pd.read_csv("/app/spx_implied_vol_20230215.csv", index_col=0)

    # Compute variance and gamma swap rates from the implied vol surface
    vs_result = var_swap_robust(df_spx)
    gs_result = gamma_swap_robust(df_spx)
    var_swaps = vs_result["vs_mid"]
    gamma_swaps = gs_result["gs_mid"]
    spx_expiries = vs_result["expiries"]

    # Normalized leverage contract: L(T) = (gamma_swap - var_swap) / var_swap
    norm_leverage = (gamma_swaps - var_swaps) / var_swaps

    # Calibrate rough Heston parameters by fitting the leverage term structure
    def obj(x):
        H, nu, rho, lbd = x
        norm_lev_model = norm_lev_contract_rheston(H, nu, rho, lbd, spx_expiries)
        return np.sum((norm_lev_model - norm_leverage) ** 2 / (spx_expiries ** 0.9)) * 1e6

    x0 = np.array([0.05, 0.25, -0.64, 0.3])
    bounds = ((1e-4, 1), (0.01, 10), (-0.999, 0), (0, 10))
    res_optim = optimize.minimize(obj, x0, method="L-BFGS-B", bounds=bounds)
    x_opt = res_optim.x
    H_opt, nu_opt, rho_opt, lbd_opt = x_opt

    print(f"Calibrated: H={H_opt:.6f}, nu={nu_opt:.6f}, rho={rho_opt:.6f}, lbd={lbd_opt:.6f}")

    # Model leverage at calibrated parameters
    model_leverage = norm_lev_contract_rheston(H_opt, nu_opt, rho_opt, lbd_opt, spx_expiries)

    # Build forward variance curve: total variance w(T) = vs_rate * T
    w_in = var_swaps * np.sqrt(spx_expiries)
    xi = xi_curve_piecewise(spx_expiries, w_in)

    # Compute model implied vols using fixed parameters for pricing
    params = {"H": 0.05, "nu": 0.3, "rho": -0.65, "lbd": 0.3}
    maturities = [0.25, 0.5, 1.0]
    log_strikes = [-0.1, -0.05, 0.0, 0.05, 0.1]
    impvols = []
    for tau in maturities:
        row = []
        for k in log_strikes:
            try:
                iv = impvol_rheston(k, tau, params, xi, n_quad=40)
                iv_val = float(iv) if np.isscalar(iv) else float(iv[0])
            except Exception:
                iv_val = float("nan")
            row.append(round(iv_val, 8))
        impvols.append(row)
        print(f"  tau={tau}: {row}")

    # Write calibrated parameters
    with open("/app/calibrated_params.json", "w") as f:
        json.dump({
            "H": round(float(H_opt), 8),
            "nu": round(float(nu_opt), 8),
            "rho": round(float(rho_opt), 8),
            "lbd": round(float(lbd_opt), 8),
        }, f, indent=2)

    # Write leverage term structure
    with open("/app/normalized_leverage.json", "w") as f:
        json.dump({
            "expiries": [round(float(e), 8) for e in spx_expiries],
            "empirical": [round(float(v), 8) for v in norm_leverage],
            "model": [round(float(v), 8) for v in model_leverage],
        }, f, indent=2)

    # Write model implied volatilities
    with open("/app/model_impvols.json", "w") as f:
        json.dump({
            "maturities": maturities,
            "log_strikes": log_strikes,
            "impvols": impvols,
        }, f, indent=2)

    print("Done. Outputs written to /app/")


if __name__ == "__main__":
    main()
