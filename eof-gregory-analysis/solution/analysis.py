"""
Corrected climate analysis with audit report.

Reads source NetCDF directly, bypassing flawed CDO/NCO preprocessing.
Applies correct area weighting, NaN masking, broken-stick significance
test, correct time window, and correct Gregory formula.

"""
import numpy as np
from netCDF4 import Dataset
import json


def main():
    # Load dataset directly from source NetCDF (bypass flawed pipeline)
    with Dataset('/app/data/climate_output.nc') as nc:
        tas_raw = nc.variables['tas'][:]   # masked array (time, lat, lon)
        lat = np.array(nc.variables['lat'][:])
        toa = np.array(nc.variables['toa_imbalance'][:])
        gmst = np.array(nc.variables['gmst_anomaly'][:])

    # Convert masked array to regular array preserving NaN for missing values
    tas = np.array(tas_raw.filled(np.nan))  # (time, lat, lon)

    # Transpose to (lon, lat, time) for spatial analysis
    field = np.transpose(tas, (2, 1, 0))  # (nx, ny, nt)
    nx, ny, nt = field.shape

    # ---- Corrected EOF analysis ----

    # FIX 1: Properly exclude NaN-masked grid cells instead of CDO setmisstoc,0
    valid_mask = ~np.isnan(field[:, :, 0])
    n_valid = int(np.sum(valid_mask))
    data_2d = field[valid_mask, :]  # (n_valid, nt)

    # FIX 2: Apply cosine-latitude area weighting (not sin as in NCO ncap2)
    _, LAT = np.meshgrid(np.arange(nx), lat, indexing='ij')
    cos_w = np.cos(np.deg2rad(LAT))
    weights = np.sqrt(cos_w[valid_mask])
    data_weighted = data_2d * weights[:, None]

    # Spatial covariance matrix
    cov = np.cov(data_weighted)

    # Eigendecomposition
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(-eigvals)
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    total_var = eigvals[eigvals > 0].sum()
    var_pct = eigvals / total_var * 100.0

    # FIX 3: Broken-stick significance test (instead of naive mean threshold)
    n_check = 20
    bs = np.zeros(n_check)
    for j in range(n_check):
        bs[j] = sum(1.0 / (k + 1) for k in range(j, n_valid)) / n_valid * 100

    n_sig = 0
    for j in range(n_check):
        if var_pct[j] > bs[j]:
            n_sig = j + 1
        else:
            break

    # Principal components
    pcs = data_weighted.T @ eigvecs  # (nt, n_valid)

    # Dominant periods via FFT
    periods = []
    for i in range(n_sig):
        fft_vals = np.abs(np.fft.rfft(pcs[:, i]))
        freqs = np.fft.rfftfreq(nt)
        fft_vals[0] = 0
        peak = np.argmax(fft_vals)
        periods.append(round(1.0 / freqs[peak], 1))

    # ---- Corrected Gregory method ----

    # FIX 4: Use post-transient regression window [100:300]
    # (not ncks -d time,0,149 which selects the initial transient)
    T = gmst[100:300]
    N = toa[100:300]
    slope, intercept = np.polyfit(T, N, 1)

    # FIX 5: Correct ECS formula: ECS = -intercept / slope
    # (not slope / intercept as in the flawed gregory.py)
    ecs = -intercept / slope

    # Compile corrected results
    expl_var = [round(float(var_pct[i]), 2) for i in range(n_sig)]
    results = {
        "n_significant_modes": int(n_sig),
        "mode_periods": sorted(periods),
        "explained_variance_pct": expl_var,
        "ecs_estimate": round(float(ecs), 4),
        "feedback_parameter": round(float(slope), 4),
        "total_variance_explained_pct": round(float(sum(var_pct[:n_sig])), 2),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Audit report documenting all errors found across CDO, NCO, and Python
    audit = {
        "n_errors": 5,
        "errors_found": [
            {
                "category": "missing_value_handling",
                "description": (
                    "Pipeline uses CDO setmisstoc,0 to replace missing/NaN "
                    "grid cells with zero instead of properly masking them "
                    "from the covariance computation. This introduces "
                    "artificial zero-variance data points that bias the EOF "
                    "decomposition and inflate the number of spurious modes."
                )
            },
            {
                "category": "area_weighting",
                "description": (
                    "Pipeline computes area weights with NCO ncap2 using "
                    "sin(lat) instead of cos(lat). On a regular lat-lon grid "
                    "the correct area weight is proportional to cos(latitude). "
                    "Using sin(lat) over-represents mid-latitudes near 45 "
                    "degrees and under-represents equatorial and polar cells, "
                    "distorting the spatial covariance structure."
                )
            },
            {
                "category": "regression_window",
                "description": (
                    "Pipeline extracts the first 150 time steps via NCO ncks "
                    "-d time,0,149 for Gregory regression, which includes "
                    "the initial transient adjustment period. The regression "
                    "should use the post-adjustment regime (time indices "
                    "100-299) where the N-vs-T relationship is quasi-linear."
                )
            },
            {
                "category": "significance_test",
                "description": (
                    "Python eof_analysis.py uses a naive eigenvalue-above-mean "
                    "threshold to determine significant EOF modes, which "
                    "retains far too many spurious modes. The correct approach "
                    "is the broken-stick model, which compares each eigenvalue "
                    "against the expected proportion from randomly partitioning "
                    "total variance among all dimensions."
                )
            },
            {
                "category": "ecs_formula",
                "description": (
                    "Python gregory.py computes ECS as slope/intercept instead "
                    "of -intercept/slope. The Gregory method fits N = slope*T "
                    "+ intercept; equilibrium (N=0) gives T_eq = -intercept/"
                    "slope. The inverted formula produces a physically "
                    "implausible ECS value."
                )
            }
        ]
    }

    with open('/app/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
