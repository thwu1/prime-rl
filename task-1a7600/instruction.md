You are given market European call option prices across multiple strikes and maturities in `/app/market_data.json`. These prices were generated from a Heston stochastic volatility model with unknown parameters.

Build a calibration engine that:

1. Implements the Heston model characteristic function for log-asset price under risk-neutral measure. The Heston SDE is: dS = r*S*dt + sqrt(v)*S*dW_x, dv = kappa*(vbar - v)*dt + gamma*sqrt(v)*dW_v, with corr(dW_x, dW_v) = rho. Handle the well-known numerical instability in the characteristic function (the so-called "Little Heston Trap").

2. Implements the COS (Fourier-cosine expansion) method for European option pricing given an arbitrary characteristic function. The method must price puts via cosine coefficients, then use put-call parity for calls.

3. Jointly calibrates the 5 Heston parameters (kappa, gamma, vbar, v0, rho) across all maturities simultaneously by minimizing the sum of squared relative pricing errors.

4. Computes option Greeks (Delta, Gamma, Vega) for the strikes and maturity specified in the `greeks_spec` section of the market data, using the calibrated model. Delta and Gamma are sensitivities to the spot price S0; Vega is sensitivity to the initial variance v0 (not sigma).

5. Extracts Black-Scholes implied volatilities from the calibrated model prices.

Write all results to `/app/results.json` following the output format in `/app/config.json`. The parameter bounds in `config.json` constrain the optimization search space.

Calibration quality target: the calibrated model must reproduce every market price within 0.1% relative error.