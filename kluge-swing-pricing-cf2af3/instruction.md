The program at `/app/kluge_swing.py` computes swing option prices under Black-Scholes-Merton, European call analytics under a Kluge stochastic energy spot model, and FDM grid convergence estimates via Richardson extrapolation. It produces incorrect numerical results across all three sections.

Fix the program so that `python3 /app/kluge_swing.py` generates a correct `/app/results.json`.

QuantLib C++ source files are available in `/app/reference/` including the pricing engine, stochastic process, instrument classes, the library's Richardson extrapolation header, and the complete test suite.

**Output schema** (`/app/results.json`):
```json
{
  "bs_swing": [
    {"n": <int 1-12>, "swing_price": ..., "bermudan_price": ...,
     "european_prices": [...], "upper_bound": ..., "lower_bound": ...,
     "upper_ok": true, "lower_ok": true}
  ],
  "kluge": {
    "std_dev": ..., "skewness": ..., "excess_kurtosis": ...,
    "bs_price": ..., "ccs3_price": ..., "ccs4_price": ...,
    "rubinstein_price": ..., "mc_price": ..., "mc_error": ...,
    "implied_vols": {"bs": ..., "ccs3": ..., "ccs4": ..., "rubinstein": ...}
  },
  "convergence": {
    "n1":  {"coarse": ..., "medium": ..., "fine": ..., "richardson": ..., "convergence_ratio": ...},
    "n6":  {"coarse": ..., "medium": ..., "fine": ..., "richardson": ..., "convergence_ratio": ...},
    "n12": {"coarse": ..., "medium": ..., "fine": ..., "richardson": ..., "convergence_ratio": ...}
  }
}
```

**Validation criteria:**

`bs_swing` — 12 entries for n=1..12. Each must satisfy: `swing_price <= n * bermudan_price + 0.01` and `swing_price >= lower_bound - 0.04`. Swing prices must be non-decreasing in n. `upper_bound` must equal `n * bermudan_price`. `lower_bound` must equal the sum of European put prices for the n exercise dates nearest maturity.

`kluge` — `std_dev` accurate to 1e-8; `skewness` accurate to 1e-8; `excess_kurtosis` accurate to 1e-6. All four moment-matching option prices accurate to 1e-6. Monte Carlo price (200,000 paths, numpy seed 421) must agree with `rubinstein_price` within 3 standard errors. Implied volatilities must be positive, within (0.1, 10.0), mutually distinct, and each must reproduce its corresponding option price via Black's call formula to within 1e-4.

`convergence` — For n in {1, 6, 12}: coarse grid (25x100), medium grid (50x200), fine grid (100x400) swing prices. Medium prices must equal corresponding `bs_swing` swing prices to 1e-10. Richardson extrapolation applies to the medium/fine pair with second-order convergence and refinement ratio k=2: `(k^p * fine - medium) / (k^p - 1)` where p=2. Convergence ratios `(coarse - medium) / (medium - fine)` must fall in (1.2, 15.0). Richardson prices must be positive.
