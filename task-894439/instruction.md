SPX implied volatility market data is available at `/app/data/spx_implied_vol.csv`. Inspect the file to understand its structure (columns, strike coverage, expiry count) and any data quality issues such as missing values.

Calibrate a rough Heston stochastic volatility model to this data. The calibration target is the normalized leverage term structure: fit the model's theoretical normalized leverage curve to an empirical one derived from the options surface. The variance and gamma swap term structures needed to compute empirical leverage must be estimated robustly from the implied volatility data — naive approaches that ignore the tails of the smile will produce biased swap estimates.

Write `/app/calibrate.py` that produces the following two output files. Run it with `python3 /app/calibrate.py`.

## Output 1: `/app/output/swap_curves.json`

JSON object with keys:

- `"expiries"`: sorted float list of maturities in years — one per distinct expiry in the data (the data contains exactly 48 distinct expiries).
- `"var_swaps"`: variance swap rates (one per expiry). All values must be positive and in the range (0.005, 0.2).
- `"gamma_swaps"`: gamma swap rates (one per expiry). All values must be positive. Due to the leverage effect in equity indices, gamma swaps should be less than the corresponding variance swaps for at least 90% of expiries.
- `"norm_leverage"`: normalized leverage values, defined as (gamma_swap − var_swap) / var_swap. For equity indices, at least 95% of values must be negative. The absolute magnitude of normalized leverage should increase substantially with maturity (long-term average of |norm_leverage| over the last 10 expiries should exceed 3× the average over the first 10).

All four lists must have the same length (48).

## Output 2: `/app/output/calibration.json`

JSON object with keys:

- `"H"`: Hurst exponent, must satisfy 0 < H ≤ 1.
- `"nu"`: vol-of-vol, must be positive.
- `"rho"`: spot-vol correlation, must satisfy −1 < ρ < 0 (negative leverage effect).
- `"lbd"`: mean reversion speed, must be non-negative.
- `"rmse"`: root mean squared error of the normalized leverage fit, must be below 0.02.
- `"model_norm_leverage"`: model-predicted normalized leverage at each of the 48 expiries under the calibrated parameters. All values must be negative.

## Calibration quality requirements

- The model admissibility condition λ' = λ − ρν > 0 must hold.
- The correlation between model and empirical normalized leverage must exceed 0.98.
- The model's absolute normalized leverage |L(T)| should be monotonically increasing with maturity (up to 2 violations allowed for numerical noise).
- At the shortest maturity, |model_norm_leverage[0]| must be below 0.10.
- At the longest maturity, |model_norm_leverage[-1]| must be below 1.5× the theoretical long-term limit |ρν/λ'|.

## Theoretical context

The rough Heston model's normalized leverage contract (flat forward variance case) is given by:

L(T) = (ρν/λ') · (1 − E_{α,2}(−λ' · T^α))

where α = H + 1/2, λ' = λ − ρν, and E_{α,β} is the two-parameter Mittag-Leffler function.