Market data for a flat-forward yield curve and a co-terminal European swaption volatility matrix (lognormal/Black76) is provided in `/app/market_data.json`.

Calibrate a Hull-White one-factor short-rate model (two global parameters: mean reversion `a` and volatility `sigma`) to the five co-terminal swaption volatilities in the market data. Then, using the calibrated model, price:

- A **European payer swaption** (1Y expiry into 5Y swap, co-terminal with the calibration instruments).
- A **co-terminal Bermudan payer swaption** as defined in the `bermudan_spec` field of the market data (exercisable annually at years 1-5, all into swaps maturing at year 6).

Also compute:

- **Early-exercise premium**: `(bermudan_price / european_price - 1) * 100`.
- **DV01**: the change in the Bermudan swaption price when the flat forward rate increases by 1 basis point (0.0001), with the model parameters `a` and `sigma` held fixed at their calibrated values (only the yield curve shifts).

Write `/app/results.json` containing:

```json
{
  "calibrated_a": <float>,
  "calibrated_sigma": <float>,
  "european_swaption_price": <float>,
  "bermudan_swaption_price": <float>,
  "bermudan_premium_pct": <float>,
  "dv01": <float>
}
```

All prices are in currency units consistent with the notional in the market data.