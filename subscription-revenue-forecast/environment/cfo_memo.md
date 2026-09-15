# CFO Quarterly Update — Q4 2023

**Document ID:** CFO-Q4-2023
**Date:** December 20, 2023
**Distribution:** Finance, FP&A, Treasury
**Classification:** Internal — Forecast Model Parameters

---

## 1. FX Risk Management & Hedge Accounting

Treasury has established a rolling hedge program for our foreign currency revenue
streams (AUD and GBP). The program designates a portion of each currency's
anticipated revenue as the hedged item under IFRS 9 cash flow hedge accounting.

The details of each forward contract — including counterparty, contracted forward
rate, and the hedge ratio (proportion of revenue designated as hedged) — are
maintained in the hedge book at `/app/data/hedge_book.csv`. This file contains
both active contracts and historical records; **only contracts with status
"active" should be incorporated into the forecast model.**

### Hedge Effectiveness Assessment

Per IFRS 9, all designated hedge relationships must pass an effectiveness
assessment before hedge accounting treatment may be applied. The assessment
methodology, data source, and effectiveness bounds are documented in the IFRS
regulatory framework at `/app/config/ifrs_framework.json`. Quarterly
mark-to-market valuation data for each hedge contract is maintained at
`/app/data/hedge_valuations.parquet`.

**Hedges that fail the effectiveness test must be dedesignated.** For
dedesignated hedge positions, the entire country-year revenue is translated at
the prevailing spot rate only, and no hedge gain or loss is recognized.

### Effective Conversion Rate

For hedges that pass the effectiveness assessment, each foreign currency's
effective USD conversion rate reflects the weighted blend of hedged and unhedged
exposure:

- The **hedged portion** of local-currency revenue is translated at the contracted
  **forward rate** specified in the hedge book.
- The **unhedged portion** (remaining exposure) is translated at the prevailing
  annual **spot rate** from the rate curves data.

USD-denominated revenue (USA market) requires no FX conversion or hedge treatment.

---

## 2. Expected Credit Loss Provisions

The Credit Committee has completed the annual assessment of expected credit losses
(ECL) across all subscription tiers, applying the simplified approach under
IFRS 9 for trade receivables. The approved provision rates are documented in
`/app/data/credit_provisions.csv`.

**Important:** The credit provisions file contains both the current approved
assessments and previously superseded preliminary estimates from the initial risk
review. Only entries with `review_status = "approved"` reflect the committee's
final determination and should be used in the forecast. The ECL rates are uniform
across all countries — they are tier-level provisions reflecting the credit risk
profile of each subscription segment.

### Forward-Looking Scenario Overlay

Consistent with IFRS 9 requirements for forward-looking information, base ECL
rates must be adjusted using probability-weighted macroeconomic scenarios. The
scenario parameters (weights and multipliers) are specified in the IFRS
regulatory framework at `/app/config/ifrs_framework.json`. The resulting
probability-weighted ECL rate replaces the base rate in the revenue waterfall.

### Application of ECL Provisions

ECL provisions represent a reduction in recognized net revenue. They are applied
as follows:

- The provision is calculated on **local-currency net revenue** (i.e., after the
  tax adjustment step but before any foreign currency translation).
- The provision amount equals `net_revenue_local × weighted_ECL_rate` for the
  applicable tier.
- The post-provision amount (`net_revenue_local × (1 − weighted_ECL_rate)`) is
  then carried forward to the currency translation step.

---

## 3. Revenue Computation Waterfall

To ensure consistency with IFRS-compliant consolidated reporting, the revenue
waterfall for each country-tier combination in each forecast period follows this
sequence:

1. **Gross subscription revenue** — charged price x subscriber count, in local
   currency.
2. **Tax adjustment** — divide gross revenue by (1 + applicable tax rate) to
   derive net revenue in local currency. USA has a 0% rate (no adjustment).
3. **Credit loss provision** — multiply local-currency net revenue by
   (1 - weighted ECL rate) for the applicable tier. This reduces recognized
   revenue to reflect expected credit losses.
4. **Currency translation** — convert to USD using the effective conversion rate.
   For effective hedges, this is the blended rate per Section 1. For
   dedesignated hedges, use spot rate only. For USD revenue, no conversion.

Steps 1-4 are performed for every country-tier pair in every forecast period.
The total monthly net revenue is the sum across all combinations.

---

## 4. Revenue Analytics — Seasonality Study

The revenue analytics team has prepared monthly seasonality adjustment factors
based on three years of historical subscriber activity patterns. These factors
are available in `/app/data/seasonality_adjustments.csv` for reference.

**These adjustments remain under board review and have NOT been approved for
incorporation into the base revenue forecast.** They should be excluded from
all forecast computations until formal board approval is granted. The current
base forecast assumes uniform monthly recognition with no seasonal adjustments.

---

## 5. Present Value Discounting

For financial reporting and investment analysis, the forecast must include the
net present value (NPV) of cumulative revenue. The discount curve is derived
from benchmark par bond rates maintained in the operational database. The
bootstrapping methodology and discount factor application are documented in
the IFRS regulatory framework at `/app/config/ifrs_framework.json`.

**Note:** The database also contains a `flat_discount_rates` table with
superseded CFO estimates. These flat rates have been replaced by the
bootstrapped zero-coupon curve approach and must not be used.

---

## 6. Data Architecture

Following the Q3 data governance review, rate curve projections (CPI, subscriber
growth, FX spot rates) have been consolidated into a single external data file at
`/app/data/rate_curves.csv`. This file uses a pivoted format with fiscal years as
columns.

The operational database (`/app/model.db`) retains historical rate records in the
`historical_rates` table for audit purposes only. **Forecast projections must be
sourced exclusively from the rate curves CSV file.** The `data_sources` table in
the database provides a registry of all external data files and their governance
status.

Hedge valuation data for effectiveness testing is maintained in Parquet format at
`/app/data/hedge_valuations.parquet`.

Business rules and policy parameters are maintained in `/app/config/policy.toml`.
IFRS regulatory parameters are in `/app/config/ifrs_framework.json`.
