Build a calibration pipeline for the Schoebel-Zhu-Hull-White (SZHW) stochastic volatility model against European call option prices in `/app/market_data.json`.

## Model

The SZHW model couples an Ornstein-Uhlenbeck volatility process with a Hull-White short rate:

    dS(t) = r(t) S(t) dt + σ(t) S(t) dW_x(t)
    dσ(t) = κ(σ̄ − σ(t)) dt + γ dW_σ(t)
    dr(t) = λ(θ(t) − r(t)) dt + η dW_r(t)

with correlations dW_x·dW_σ = ρ_xσ dt, dW_x·dW_r = ρ_xr dt, dW_σ·dW_r = ρ_rσ dt.

## Input

`/app/market_data.json` contains: `S0` (spot), `r` (risk-free rate), `T` (maturity), `strikes`, `call_prices` (reference European call prices), and `szhw_fixed_params` with keys `kappa`, `Rxr`, `lambd`, `eta`.

Calibrate the 5 free parameters: `gamma` (vol-of-vol), `sigmabar` (long-run volatility), `Rrsigma` (rate-vol correlation), `Rxsigma` (stock-vol correlation), `sigma0` (initial volatility).

## Deliverables

### Pricer — `/app/szhw_pricer.py`

Python module exporting:
```python
def compute_call_prices(S0, K, T, P0T, kappa, Rxr, lambd, eta,
                        gamma, sigmabar, Rrsigma, Rxsigma, sigma0) -> list[float]
```
`P0T` is the zero-coupon bond price P(0,T) as a scalar. `K` is a list of strikes. Returns one European call price per strike.

### Makefile — `/app/Makefile`

Must define three targets:
- `calibrate` — runs calibration, stores optimization results in `/app/calibration.db`
- `report` — reads the best result from the database, writes `/app/results.json` and `/app/smile.csv`
- `clean` — removes generated artifacts

### Database — `/app/calibration.db`

SQLite database with table `runs`:
```sql
CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    gamma REAL, sigmabar REAL, Rrsigma REAL,
    Rxsigma REAL, sigma0 REAL, l2_error REAL
);
```
At least one calibration run must be recorded.

### Results — `/app/results.json`

JSON with keys:
- `calibrated_params`: dict with keys `gamma`, `sigmabar`, `Rrsigma`, `Rxsigma`, `sigma0` (all numeric)
- `model_call_prices`: list of floats, one per strike in `market_data.json`
- `model_implied_vols`: list of Black-Scholes implied volatilities in decimal form (e.g. 0.25 = 25%), one per strike

### Volatility Smile — `/app/smile.csv`

CSV file with header `strike,model_price,market_price,implied_vol` and one data row per strike.

## Acceptance Criteria

- `gamma > 0`, `sigmabar > 0`, `sigma0 > 0`, `Rrsigma ∈ (−1, 1)`, `Rxsigma ∈ (−1, 1)`
- L2 norm of (model_call_prices − market call_prices) < 2.0
- All implied volatilities in (0.05, 2.0)
- No-arbitrage: each call price ≤ S0 (tolerance 0.1) and ≥ max(S0 − K·P(0,T), 0) (tolerance 0.1)
- `compute_call_prices` called with calibrated parameters reproduces `model_call_prices` within relative tolerance 1e-3
- For out-of-sample strikes [65.0, 75.0, 85.0, 110.0, 145.0], the pricer returns positive, non-increasing call prices (tolerance 0.01 between adjacent pairs)