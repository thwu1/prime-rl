Build a high-precision Black-Scholes implied volatility solver as a C shared library with Python ctypes bindings.

**Required files:**

- `/app/src/ivol.c` and `/app/src/ivol.h` -- C source implementing the solver
- `/app/Makefile` -- `make -C /app` must produce `/app/libivol.so` from the C source. The library must link only against `-lm` (standard C math library)
- `/app/iv_solver.py` -- Python module that loads `libivol.so` via ctypes

**C library interface** (symbols exported from `libivol.so`):

```
double bs_price(int is_call, double strike, double forward, double total_var, double df);
double implied_vol(int is_call, double price, double forward, double strike, double tte, double df);
```

`bs_price` computes the Black-Scholes option price given total variance `sigma^2 * tte`. `implied_vol` returns `sigma` such that `bs_price(is_call, strike, forward, sigma*sigma*tte, df)` reproduces the input price to near machine precision.

**Python module interface** (`/app/iv_solver.py`):

- `black_scholes_price(is_call: bool, strike, forward, total_variance, discount_df) -> float`
- `implied_volatility(is_call: bool, price, forward, strike, tte, discount_df) -> float`

**CLI**: `python3 /app/iv_solver.py --forward F --strike K --tte T --df DF --price P --type call|put` prints sigma to stdout.

**Accuracy requirements** -- parameters and thresholds are specified in `/app/data/test_config.json`:

- *Cui grid*: For each point on a multi-dimensional grid of strikes, maturities, and volatilities, compute the BS call price then invert it. Max |sigma_recovered - sigma_true| and mean error must satisfy thresholds in the config.
- *Wide vol range*: A single-strike test across a wide volatility sweep; max error threshold in the config.
- *Edge cases*: Price round-trip error must be below configured tolerance for each case.
- *Put-call parity*: IV derived from call and put prices for the same parameters must agree within configured tolerance.
- *Market quotes*: `/app/data/market_quotes.csv` defines option parameters with known volatilities. Vol recovery error must be below the per-row tolerance.

**Performance**: Full Cui grid computation must complete within the time limit in the config.

**Constraints**: No external implied-volatility or options-pricing packages. No pre-built shared libraries. The C code must be self-contained using only the standard C math library.
