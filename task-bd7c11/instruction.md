A dataset of 64 U.S. Treasury notes and bonds with observed market prices is provided at `/app/data/treasury_bonds.csv`. The file contains columns: `cusip`, `coupon_rate` (annual, in percent), `maturity_date`, `settlement_date` (2024-06-15 for all), `price` (clean price per $100 face), and `duration_years` (Macaulay duration).

Implement a complete Nelson-Siegel-Svensson (NSS) yield curve fitting pipeline that:

1. Fits the 6-parameter NSS model to the bond cross-section by minimizing duration-weighted squared price errors: `sum((P_obs - P_model)^2 / D_i)`. The NSS continuously compounded zero-coupon spot rate is: `y(t) = β₁ + β₂·((1-e^(-t/τ₁))/(t/τ₁)) + β₃·((1-e^(-t/τ₁))/(t/τ₁) - e^(-t/τ₁)) + β₄·((1-e^(-t/τ₂))/(t/τ₂) - e^(-t/τ₂))`, with discount factor `d(t) = e^(-y(t)·t)`. Bond prices are computed as the sum of discounted semiannual cashflows (coupon/2 every 6 months, plus 100 at maturity).

2. Computes the instantaneous forward rate curve: `f(t) = β₁ + β₂·e^(-t/τ₁) + β₃·(t/τ₁)·e^(-t/τ₁) + β₄·(t/τ₂)·e^(-t/τ₂)`.

3. Computes the par yield curve (the coupon rate `c` at which a bond prices at par): `c = 2·(1-d(T)) / Σd(tᵢ)` where `tᵢ` are semiannual payment times up to maturity `T`.

4. Classifies each bond as "rich" (observed > model by more than 0.15%), "cheap" (observed < model by more than 0.15%), or "fair".

Write the following output files:

- `/app/output/fitted_params.json`: `{"tau1": ..., "tau2": ..., "beta1": ..., "beta2": ..., "beta3": ..., "beta4": ...}` (float values, rates as decimals)
- `/app/output/spot_rates.csv`: columns `maturity,rate` for maturities [0.5, 1, 2, 3, 5, 7, 10, 20, 30] (rates as decimals, e.g. 0.04 for 4%)
- `/app/output/forward_rates.csv`: columns `maturity,rate` for the same maturities
- `/app/output/par_yields.csv`: columns `maturity,rate` for the same maturities
- `/app/output/model_prices.csv`: columns `cusip,observed_price,model_price,error_pct` (error_pct = (observed-model)/model)
- `/app/output/rich_cheap.csv`: columns `cusip,classification,error_pct`