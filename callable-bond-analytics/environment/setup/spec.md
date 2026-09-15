# Callable Bond Analytics — Methodology Specification

## Overview

Build a Python script (`/app/analyze.py`) that reads market data from `/app/market_data.json`, constructs a callable fixed-rate bond, and computes spread, risk, and scenario analytics. Write all results to `/app/results.json`.

## Market Data Format

The JSON input contains:
- `evaluation_date`: `[day, month, year]` triple
- `ois_rates`: `{tenor_string: rate_percent, ...}` — quoted par SOFR OIS swap rates
- `bond`: bond terms including issue date, maturity, coupon rate (percent), face amount, settlement days, quoted clean price, and first call date
- `hull_white`: `{a, sigma, tree_steps}` — Hull-White one-factor model parameters
- `krd_tenors`: list of tenor strings for key-rate duration computation
- `krd_bump_bps`: bump size in basis points for KRD
- `parallel_shift_bps`: parallel shift size in basis points for effective duration/convexity
- `stress_ois_rates`: `{tenor_string: rate_percent, ...}` — stressed OIS curve rates

All dates are `[day, month, year]` triples.

## Conventions

### Curve Construction
- Instruments: SOFR OIS swaps with 2 business days settlement
- Interpolation: log-cubic on discount factors
- Curve day counter: Actual/360

### Bond
- Payment calendar: US Government Bond
- Bond day counter: 30/360 Bond Basis
- Coupon frequency: Annual
- Schedule generation: backward from maturity
- Business day convention: Following

### Yield and Spread Computation
- Compounding convention: SimpleThenCompounded
- Compounding frequency: Annual
- Day counter for all yield/spread calculations: bond day counter (30/360 Bond Basis)

## Analytics

### 1. Bond Yield (`bond_yield`)
Solve for the yield-to-maturity that reprices the bond to its quoted clean price, using the bond day counter with SimpleThenCompounded annual compounding. Report as a decimal (e.g., 0.0365).

### 2. I-Spread (`i_spread_bps`)
The I-spread is the bond yield minus the linearly interpolated benchmark rate at the bond's maturity. The benchmark rates are the **quoted par OIS rates** from the market data (not bootstrapped zero rates). Construct an interpolation grid where the x-axis is year fractions from the evaluation date to each OIS tenor date, computed using the **bond day counter**. Interpolate at the year fraction to the bond's maturity. Report in basis points.

### 3. Z-Spread (`z_spread_bps`)
The zero-volatility spread over the SOFR discount curve such that the present value of the bond's cash flows equals the quoted clean price. Must use the **bond day counter**, SimpleThenCompounded compounding, and annual frequency. Report in basis points.

### 4. OAS (`oas_bps`)
Construct a call schedule: the bond is callable at par (clean price 100) on every coupon date from `first_call_date` (**inclusive**) up to maturity (**exclusive**). Build a callable fixed-rate bond with this call schedule. Set up a Hull-White one-factor short-rate model calibrated to the SOFR term structure using the provided mean-reversion speed (`a`) and volatility (`sigma`). Price using a tree-based engine with the specified number of time steps. Compute the OAS as the spread that equates the model's callable-bond price to the quoted clean price. Report in basis points.

### 5. Option Cost (`option_cost_bps`)
`option_cost = z_spread − oas`. Report in basis points.

### 6. Effective Duration (`effective_duration`)
Measure the callable bond's price sensitivity to a parallel shift in rates:
1. Shift the SOFR zero-rate curve up and down by `parallel_shift_bps` using a constant zero spread overlay
2. For each shifted curve, construct a **new** Hull-White model (same `a` and `sigma` parameters) and a **new** tree engine, then price the callable bond
3. Obtain the base callable bond model price from the tree engine on the unshifted curve

Formula: `effective_duration = (P_down − P_up) / (2 × P_base × shift)` where shift is in decimal.

### 7. Effective Convexity (`effective_convexity`)
Using the same shifted prices as effective duration:

`effective_convexity = (P_down + P_up − 2 × P_base) / (P_base × shift²)`

### 8. Key-Rate Durations (`key_rate_durations`)
Compute key-rate durations for the **bullet** (non-callable) bond using the SOFR discount curve:

- Bump profile: tent function. For KRD tenor k, apply the full bump at that tenor's calendar-adjusted date, linearly interpolating to zero at adjacent KRD tenor dates.
- Edge handling: at the first tenor, extend the bump flat from the evaluation date; at the last tenor, extend the bump flat to a distant horizon (60Y).
- For each bumped curve, reprice the bullet bond using a discounting engine on the spread-adjusted term structure.

`KRD_k = −(P_bumped − P_base) / (P_base × bump)` where bump is `krd_bump_bps` in decimal.

Report as an object mapping tenor strings to values.

### 9. Stress P&L (`stress_pnl`)
Assess the portfolio impact of a curve shift scenario:
1. Build a stressed SOFR curve from `stress_ois_rates`
2. Hold the Z-spread constant: apply the computed Z-spread as a constant zero spread over both the base and stressed SOFR curves
3. Price the bullet bond on each Z-spread-adjusted curve using a discounting engine

`stress_pnl = (P_stressed − P_base) × face / 100`

## Output Format

Write `/app/results.json` as a JSON object with keys:
- `bond_yield` — decimal
- `i_spread_bps` — basis points
- `z_spread_bps` — basis points
- `oas_bps` — basis points
- `option_cost_bps` — basis points
- `effective_duration` — decimal
- `effective_convexity` — decimal
- `key_rate_durations` — object `{tenor_string: value, ...}`
- `stress_pnl` — dollar amount
