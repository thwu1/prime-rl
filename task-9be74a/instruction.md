A Python library at `/app/rough_heston_lib/` partially implements a rough Heston volatility calibration and pricing pipeline (entry point: `/app/rough_heston_lib/pipeline.py`). It loads SPX implied volatility data, estimates variance and gamma swap rates via robust replication, calibrates rough Heston parameters (H, nu, rho, lambda) by fitting the normalized leverage term structure, builds a piecewise-constant forward variance curve, and prices options via the rough Heston characteristic function.

The library has implementation bugs in several modules. Additionally, the characteristic function module (`/app/rough_heston_lib/characteristic_fn.py`) is entirely unimplemented — it contains only function signatures that raise `NotImplementedError`. You must implement this module from scratch using the Padé [3,3] rational approximant for the fractional Riccati equation, fix all bugs across the other modules, and run the corrected pipeline to produce the output files specified below.

SPX implied volatility data (Feb 15, 2023) is at `/app/spx_implied_vol_20230215.csv` with columns `Expiry`, `Texp`, `Strike`, `Bid`, `Ask`, `Fwd`, `CallMid` and 48 distinct expiry dates.

## `/app/calibrated_params.json`

```json
{"H": <float>, "nu": <float>, "rho": <float>, "lbd": <float>}
```
H in [0.0001, 1], nu in [0.01, 10], rho in (-1, 0), lbd in [0, 10].

## `/app/normalized_leverage.json`

```json
{"expiries": [<48 floats>], "empirical": [<48 floats>], "model": [<48 floats>]}
```
- 48 entries per array, expiries ascending
- Over 90% of empirical values negative, all magnitude below 1.0
- Longer-dated empirical leverage more negative than shorter-dated (first-quarter mean vs last-quarter mean)
- Model-to-empirical RMSE below 0.015

## `/app/model_impvols.json`

Computed with fixed parameters H=0.05, nu=0.3, rho=-0.65, lbd=0.3 and the forward variance curve from calibrated variance swap rates:

```json
{"maturities": [0.25, 0.5, 1.0], "log_strikes": [-0.1, -0.05, 0.0, 0.05, 0.1], "impvols": [[<5>], [<5>], [<5>]]}
```
- All values finite and in (0.05, 1.0)
- Negative skew: vol(k=-0.1) > vol(k=+0.1) at each maturity
- Convexity: vol(k=-0.1) + vol(k=+0.1) > 2*vol(k=0)
- Skew asymmetry: vol(k=-0.1) - vol(k=0) > vol(k=0) - vol(k=+0.1)
- Skew magnitude decreases with maturity
- ATM vols approximately 0.19, 0.20, 0.20 (tolerance ±0.02)