The directory `/app/` contains a Java project for a Hull-White one-factor short-rate model pricing engine. Build and run it with `bash /app/run.sh`.

**Current state:** The engine compiles and runs but produces incorrect results. The source at `/app/src/HullWhiteEngine.java` contains numerical errors in several pricing routines and is missing implementations for implied volatility inversion and early-exercise option pricing. The supporting files (`SimpleJson.java`, `config.json`, `build.xml`) are correct and should not need modification.

**Goal:** Diagnose and fix all issues so that `bash /app/run.sh` exits successfully and writes `/app/results.json` containing correct values for these keys:

- `discount_factors` — analytic discount factors at each bond maturity
- `B_values` — model B-function at T = 1, 5, 10, 20
- `conditional_variance` — short-rate conditional variance at t = 1, 5, 10
- `forward_bond_volatility` — forward bond vol per caplet maturity
- `mc_bond_prices` — Monte Carlo zero-coupon bond prices
- `caplet_forward_rates` — forward LIBOR rates for caplet underlyings
- `caplet_strikes` — caplet strike rates
- `mc_caplet_prices` — Monte Carlo caplet prices
- `mc_caplet_implied_normal_vols` — implied normal vols from MC caplet prices
- `analytic_caplet_implied_normal_vols` — implied normal vols from analytic caplet prices
- `european_swaption_value` — European payer swaption price
- `bermudan_swaption_value` — Bermudan payer swaption price with early exercise

**Success criteria:**
- `bash /app/run.sh` exits with code 0 and writes `/app/results.json`
- Analytic quantities match reference values to high precision
- MC bond prices converge to analytic discount factors within statistical tolerance
- MC and analytic caplet implied volatilities agree closely
- Bermudan swaption value is at least as large as European swaption value
- All verification tests pass
