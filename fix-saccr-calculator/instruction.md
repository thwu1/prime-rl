The R calculator spread across `/app/saccr.R`, `/app/core.R`, and `/app/addons.R` implements Basel III SA-CCR (BCBS 279) counterparty credit risk computation. Trade data CSVs reside in `/app/data/`. Running `Rscript /app/saccr.R` processes five BCBS 279 Annex 4a validation portfolios and writes `/app/results.json`.

The calculator produces incorrect results across multiple examples. Computations contain numerical, structural, and classification errors spanning multiple source files, and functionality required by certain portfolio types may be absent. Diagnose and fix all defects so outputs match the published golden values.

**Output** (`/app/results.json`): JSON object keyed `example1` through `example5`. Each example object must contain:

- `EAD`, `RC` (non-negative), `V_C`, `addon_aggregate`, `multiplier` (range [0.05, 1.0]), `PFE`
- Per-asset-class add-on fields (`addon_ir`, `addon_credit`, `addon_commodity`): include only when that asset class has trades in the example
- Per-asset-class detail breakdowns:
  - `ir_detail`: object mapping each currency to its hedging-set-level add-on
  - `credit_detail`: object mapping each reference entity to its **signed** entity-level add-on
  - `commodity_detail`: object mapping each hedging set name to its add-on

**Consistency** (tolerance +/-5): `PFE = multiplier * addon_aggregate` and `EAD = 1.4 * (RC + PFE)`.

**Golden values** (EAD/RC tolerance +/-5; add-on tolerance +/-10):

| Ex | Portfolio | EAD | RC | addon_agg |
|----|-----------|-----|----|-----------|
| 1 | IRD, unmargined | 569 | 60 | 347 |
| 2 | Credit, unmargined | 381 | 0 | 282 |
| 3 | Commodity, unmargined | 5406 | 20 | 3841 |
| 4 | IRD + Credit, unmargined | 936 | 40 | 629 |
| 5 | IRD + Commodity, margined | 1879 | 0 | 1401 |

**Per-asset-class add-ons** (tolerance +/-10):

| Ex | addon_ir | addon_credit | addon_commodity |
|----|----------|--------------|-----------------|
| 1 | 347 | — | — |
| 2 | — | 282 | — |
| 3 | — | — | 3841 |
| 4 | 347 | 282 | — |
| 5 | 123 | — | 1278 |

**Detail breakdowns** (tolerance +/-15):
- Ex 1 ir_detail: USD ~ 296, EUR ~ 50
- Ex 2 credit_detail: FirmA ~ 106, FirmB ~ -280, CDX.IG ~ 168
- Ex 3 commodity_detail: Energy ~ 2041, Metals ~ 1800
- Ex 4 ir_detail: USD ~ 296, EUR ~ 50; credit_detail: FirmA ~ 106, FirmB ~ -280, CDX.IG ~ 168
- Ex 5 ir_detail: USD ~ 105, EUR ~ 18; commodity_detail: Energy ~ 639, Metals ~ 639

**Multiplier**: Examples 1, 3, 4 require `multiplier = 1.0`. Examples 2 and 5 require `multiplier` strictly between 0.90 and 1.0. Example 5 must have `RC = 0`.

**Example 5** is a margined netting set; margin terms are in `/app/data/margin_ex5.csv`.
