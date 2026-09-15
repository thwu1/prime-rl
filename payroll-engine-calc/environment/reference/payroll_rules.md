# Payroll Computation Rules Reference

## Federal Income Tax (FIT) — Percentage Method

For **regular wages** (scenario type `regular` and `regular_with_garnishment`):

1. Compute FIT taxable wages: `gross_pay + imputed_income - traditional_401k - section_125_health`
2. Compute adjusted wage: `FIT_taxable_wages - standard_deduction_per_period` (from `tax_config.fit_percentage_method`, keyed by pay frequency and filing status)
3. If adjusted wage ≤ 0, FIT = 0
4. Find the bracket where `min ≤ adjusted_wage < max` (treat `null` max as infinity)
5. FIT = `base_tax + rate × (adjusted_wage - over)`
6. Round to nearest cent

For **supplemental wages** using the **flat method** (used by `gross_up` and `retro_pay` types):
FIT = `gross_supplemental × federal_supplemental_flat_rate`

For **supplemental wages** using the **aggregate method** (type `bonus_aggregate`):

1. Compute FIT on the combined amount `(regular_gross + bonus)` as if it were a single regular wage payment — apply the percentage method using the same filing status and pay frequency brackets. The combined FIT taxable base is `regular_gross + bonus` (subtract pre-tax deductions on regular wages only, if any; bonuses have no pre-tax deductions).
2. Compute FIT on `regular_gross` alone using the same method.
3. FIT on the bonus = step 1 result − step 2 result.

Note: The aggregate method may push the combined amount into a higher tax bracket than the regular wages alone.

## FICA Taxes

FICA taxable wages = `gross_pay + imputed_income - section_125_health`

**Important:** Traditional 401(k) contributions do NOT reduce FICA wages. Only Section 125 (cafeteria plan) deductions reduce FICA wages.

### Social Security

- Rate: `fica.ss_rate` (employee share)
- Wage base: `fica.ss_wage_base` — SS tax stops once cumulative FICA wages reach this amount
- SS remaining this period: `max(0, ss_wage_base - ytd_fica_wages)`
- SS taxable this period: `min(fica_wages_this_period, ss_remaining)`
- SS tax: `ss_taxable × ss_rate`

If `ytd_fica_wages` already exceeds the wage base, SS tax for the period is $0.

### Medicare

- Rate: `fica.medicare_rate` — applies to ALL FICA wages (no cap)
- Medicare tax: `fica_wages_this_period × medicare_rate`

### Additional Medicare Tax

- Rate: `fica.additional_medicare_rate`
- Threshold: `fica.additional_medicare_threshold` — applies for withholding regardless of filing status
- If `ytd_fica_wages + fica_wages_this_period > threshold`:
  - Amount above threshold: `(ytd_fica_wages + fica_wages_this_period) - threshold`
  - Taxable this period: `min(fica_wages_this_period, amount_above_threshold)`
  - Additional Medicare tax: `taxable × additional_medicare_rate`
- If cumulative does not exceed threshold: $0

## State Tax

State withholding uses a flat rate:
- State taxable wages = `gross_pay + imputed_income - traditional_401k - section_125_health` (same base as FIT taxable wages, but without federal standard deduction subtraction)
- State tax = `state_taxable × state_rate`

For supplemental wages (bonuses, retro pay, gross-up): state tax = `supplemental_gross × state_rate`

## Group-Term Life Insurance Imputed Income

Employer-provided group-term life insurance over $50,000 creates taxable imputed income:

1. Coverage over exclusion: `max(0, coverage_amount - 50000)`
2. Round coverage over exclusion to nearest $100, then divide by 1000 to get units
3. Look up `cost_per_1000` from `group_term_life_table` using employee's age
4. Monthly cost: `units × cost_per_1000`
5. Annual imputed income: `(monthly_cost × 12) - (employee_monthly_contribution × 12)`
6. Per-period imputed income: `annual_imputed / pay_periods_per_year`
7. Round to nearest cent

Imputed income is added to wages for FIT, FICA (SS and Medicare), and state tax purposes. It is NOT cash paid to the employee — it only affects tax calculations, not net pay.

If `group_term_life` is null or absent, imputed income is $0.

## Pre-Tax Deduction Rules

| Deduction Type | Reduces FIT wages? | Reduces FICA wages? | Reduces State wages? |
|---|---|---|---|
| Traditional 401(k) | Yes | **No** | Yes |
| Section 125 Health | Yes | Yes | Yes |

## Gross-Up Calculation

Given a `desired_net` amount, compute the gross bonus such that after all individually rounded tax withholdings, the net equals or exceeds the desired amount.

Applicable taxes (all at flat rates):
- FIT at `federal_supplemental_flat_rate`
- SS at `fica.ss_rate` (only on the portion within SS wage base room)
- Medicare at `fica.medicare_rate`
- Additional Medicare at `fica.additional_medicare_rate` (if applicable)
- State at the applicable state flat rate

**SS wage base boundary:** If the gross amount would partially or fully exceed the remaining SS room (`ss_wage_base - ytd_fica_wages`), Social Security tax applies only to the portion within the remaining room. This creates a piecewise calculation where the effective total tax rate changes at the SS boundary.

The computed gross should be the **minimum value in whole cents** where `gross - sum(individually_rounded_taxes) >= desired_net`.

## Retroactive Pay with Overtime Recalculation

When an hourly employee receives a pay raise retroactive to prior weeks:

For each week:
1. `regular_hours = min(hours_worked, weekly_threshold_hours)`
2. `ot_hours = max(0, hours_worked - weekly_threshold_hours)`
3. `rate_diff = new_hourly_rate - old_hourly_rate`
4. `ot_rate_diff = (new_hourly_rate × ot_multiplier) - (old_hourly_rate × ot_multiplier)`
5. `regular_diff = regular_hours × rate_diff`
6. `ot_diff = ot_hours × ot_rate_diff`
7. `total_diff = regular_diff + ot_diff`

Total retro gross = sum of all weeks' `total_diff`.

Retro pay is treated as supplemental wages: apply flat FIT rate, flat FICA rates, and flat state rate.

## Garnishment — Child Support with CCPA Limits

For type `regular_with_garnishment`, compute all regular paycheck fields first, then apply the garnishment.

### Disposable Earnings (CCPA)

Disposable earnings = `gross_pay` minus all legally required withholdings.

Legally required withholdings:
- Federal income tax (FIT)
- Social Security tax
- Medicare tax (including Additional Medicare Tax)
- State income tax

Voluntary deductions (traditional 401(k), Section 125 health insurance) are NOT subtracted when computing disposable earnings.

### CCPA Garnishment Limits — Child Support

The Consumer Credit Protection Act (CCPA) limits the maximum amount that can be garnished for child support based on the employee's circumstances:

| Supporting another spouse/child? | In arrears > 12 weeks? | Maximum % of disposable earnings |
|---|---|---|
| Yes | No | 50% |
| Yes | Yes | 55% |
| No | No | 60% |
| No | Yes | 65% |

### Garnishment Calculation

1. Compute `disposable_earnings` as defined above
2. Determine `ccpa_limit_pct` from the table above using the garnishment parameters
3. `max_garnishment` = `disposable_earnings × ccpa_limit_pct` (rounded to nearest cent)
4. `actual_garnishment` = `min(order_amount, max_garnishment)`
5. `net_pay_after_garnishment` = `net_pay - actual_garnishment`

Where `net_pay` is the regular net pay before garnishment (gross minus pre-tax deductions minus all taxes).

## Net Pay Calculation

For `regular` and `regular_with_garnishment` types:
`net_pay = gross_pay - pretax_401k - pretax_health - fit_withholding - ss_tax - medicare_tax - additional_medicare_tax - state_tax`

Note: imputed income affects tax calculations but is not cash — it does not add to gross pay and is not subtracted for net pay.

## Rounding

All monetary output values should be rounded to the nearest cent. Round 0.5 up (standard rounding).
