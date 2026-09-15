A SQLite database at `/app/options.db` contains European equity option market data across several tables. Explore its schema to understand the available data — the database includes option quotes from multiple sources with varying reliability, several yield curves, and underlying asset metadata.

Calibrate a Heston stochastic volatility model to a clean implied volatility surface extracted from this database. Write results to `/app/results.json`:

    {
      "calibrated_params": {"kappa": ..., "gamma": ..., "vbar": ..., "v0": ..., "rho": ...},
      "calibration_rmse_iv_pct": <float>,
      "feller_satisfied": <boolean>,
      "forward_variance": {"T_0.5": ..., "T_1.0": ..., "T_2.0": ..., "T_5.0": ...},
      "repriced_ivs": [[iv_T1_K1, iv_T1_K2, ...], ...],
      "greeks": {
        "delta": [[delta_T1_K1, ...], ...],
        "vega": [[vega_T1_K1, ...], ...]
      }
    }

- `kappa`, `gamma`, `vbar`, `v0`, `rho`: Heston parameters (variance mean-reversion speed, vol-of-vol, long-run variance, initial variance, spot-vol correlation)
- `calibration_rmse_iv_pct`: 100 × sqrt(mean((σ_model − σ_market)²)), must be below 1.0
- `feller_satisfied`: whether the Feller condition holds for the calibrated parameters
- `forward_variance`: expected value of the Heston variance process at horizons 0.5, 1.0, 2.0, 5.0 years
- `repriced_ivs`: model-implied Black-Scholes implied volatilities (decimals) at each (maturity, strike) grid point, indexed [maturity][strike] both ascending
- `greeks.delta`: option price sensitivity to the underlying spot at each grid point
- `greeks.vega`: option price sensitivity to initial variance v0 at each grid point