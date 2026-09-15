Build `/app/analyze.py`, a command-line tool that queries the USAspending.gov REST API (`https://api.usaspending.gov/api/v2/`) to produce a federal procurement market concentration analysis report.

**CLI interface:**
```
python3 /app/analyze.py --naics CODE [CODE ...] --fy YEAR --output PATH
```

`--naics`: one or more 6-digit NAICS codes. `--fy`: federal fiscal year (integer). `--output`: path for the JSON report.

For each NAICS code, query the API to retrieve:
- Top contract-award recipients (minimum 50 per NAICS, handling pagination)
- State-level geographic distribution of contract spending (place of performance)
- Awarding agency breakdown

Only contract awards should be included (exclude grants, loans, and other assistance). Federal fiscal years begin October 1 of the prior calendar year (FY 2023 = 2022-10-01 through 2023-09-30).

**Required computations per NAICS code:**
- Herfindahl-Hirschman Index (HHI) for recipient concentration, computed as the sum of squared percentage-point market shares (range 0--10000, where 10000 = single-firm monopoly)
- CR4 and CR8: four-firm and eight-firm concentration ratios (percentage of total spending held by top 4 and 8 recipients respectively)
- Geographic HHI across states using the same formula

**Cross-NAICS analysis:** Identify recipients appearing in two or more of the specified NAICS codes. Report each with their per-NAICS amounts and total cross-NAICS spending. Match recipients by their API-provided identifier, not by name.

**Top recipient deep dive:** For the single highest-spending recipient across all queried NAICS codes, report their profile including name, identifier, location, business categories, and total transaction amount. If the recipient API profile endpoint is available and returns data, incorporate it; otherwise populate from the spending data.

**Output JSON at `--output`:**

- `metadata`: `naics_codes` (list of strings), `fiscal_year` (int), `generated_at` (ISO 8601)
- `per_naics`: object keyed by NAICS code string, each containing:
  - `total_spending` (float), `recipient_count` (int)
  - `concentration`: object with `hhi`, `cr4`, `cr8` (all floats)
  - `top_recipients`: list sorted descending by amount; each entry has `name` (str), `amount` (float), `share_pct` (float), `recipient_id` (str)
  - `geographic`: object with `hhi` (float) and `top_states` (list of up to 5 entries, each with `state_code`, `state_name`, `amount`, `share_pct`)
  - `top_agency`: object with `name` (str), `amount` (float)
- `cross_naics_overlap`: list of objects with `name`, `recipient_id`, `naics_codes` (list), `total_amount`
- `top_recipient_profile`: non-empty object with `name`, `recipient_id`, `location` (object), `business_categories` (list), `total_transaction_amount` (float)

Exit code 0 on success with valid JSON written to the output path.
