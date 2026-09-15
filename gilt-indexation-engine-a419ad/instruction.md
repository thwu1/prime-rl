A C++ UK index-linked gilt pricing and risk analytics engine at `/app/` is built from multiple source files (`main.cpp`, `rpi.cpp`, `pricing.cpp`, `analytics.cpp`, `schedule.cpp`) with associated headers. The engine currently fails to build. Fix all compilation, linking, and runtime issues so it produces correct output:

```
cd /app && make clean && make && ./gilt_engine rpi_data.csv gilts.json output.json
```

The engine reads monthly UK RPI (Retail Price Index) data from `/app/rpi_data.csv` and gilt specifications from `/app/gilts.json`, computing pricing and risk analytics for each gilt. Each gilt specifies an `index_lag` field (3 or 8 months), and the engine must correctly implement both the 3-month lag (daily linear interpolation between adjacent months' RPI values) and 8-month lag (flat monthly RPI, no interpolation) reference RPI conventions per the UK DMO's published index-linked gilt cash flow formulae.

Pricing follows the UK_GB BondCalcMode: semi-annual coupons, compounding discount factors for initial and final periods, and a 7-business-day (Mon–Fri) ex-dividend window before each coupon date. The general-case pricing formula (more than 2 remaining coupons) must correctly discount each intermediate coupon. The yield solver must converge for all test cases.

The risk analytics module (`/app/analytics.cpp`) is unimplemented. It must compute:

- **Modified duration**: `-1/P * dP/dy` where `P` is dirty price
- **Convexity**: `1/P * d²P/dy²`
- **BPV** (basis point value): `modified_duration * dirty_price / 10000`, per 100 nominal
- **Breakeven inflation**: `pow(index_ratio, 1/T) - 1` where `T` is elapsed years (Actual/365.25) from effective date to settlement

**Output** — `/app/output.json` must be a JSON object with a `results` array. Each element contains: `id`, `base_rpi`, `settlement_ref_rpi`, `settlement_index_ratio`, `cashflows` (array of `{date, type, unindexed, index_ratio, indexed}`), `accrual_fraction`, `ex_dividend`, `accrued_interest`, `n_remaining_coupons`, `real_yield`, `real_dirty_price`, `real_clean_price`, `indexed_dirty_price`, `indexed_clean_price`, `modified_duration`, `convexity`, `bpv`, `breakeven_inflation`.

Verification compares output against independently computed reference values with specified tolerances.
