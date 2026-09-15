Implement a pipeline that computes Section 385 intercompany debt recharacterization and Section 163(j) business interest expense limitation for a multi-entity portfolio across multiple taxable years.

Running `make -C /app all` must produce `/app/results.db` (a SQLite database). Running `make -C /app clean` must remove all generated files. Running `make -C /app report` must produce `/app/report.json` by querying `/app/results.db` using the `sqlite3` CLI and assembling the result with `jq`.

**Input** (`/app/data/`):

- `entities.csv` -- `id,type` (types: `c_corp`, `individual`, `partnership`)
- `financials.csv` -- `entity_id,year,tentative_taxable_income,business_interest_expense,business_interest_income,floor_plan_financing_interest,depreciation,amortization,depletion,nol_deduction,section_199a_deduction,capital_loss_carryover`
- `partnerships.csv` -- `partnership_id,partner_id,share`
- `ownership.csv` -- `parent_id,subsidiary_id,ownership_pct`
- `intercompany_loans.csv` -- `loan_id,issuer_id,holder_id,issue_date,principal,annual_interest,active_years` (semicolon-separated years)
- `distributions.csv` -- `from_entity,to_entity,date,amount`

Intercompany loan interest is already reflected in entity BIE (for the issuer) and BII (for the holder) in `financials.csv` for each active year. Interest attributable to debt that Section 385 recharacterizes as equity must be backed out of those figures before the Section 163(j) computation.

All regulatory rules governing both computations are in `/app/regulations/`. Those provisions are authoritative.

**Output** (`/app/results.db`):

Table `entity_results` -- `entity_id TEXT, year INTEGER, ati REAL, limitation REAL, deductible_bie REAL, disallowed_bie REAL, carryforward_bie REAL, excess_bie REAL, excess_taxable_income REAL, excess_bii REAL, ebie_converted REAL` -- PK `(entity_id, year)`.

Table `partner_allocations` -- `partnership_id TEXT, partner_id TEXT, year INTEGER, deductible_bie REAL, excess_bie REAL, excess_taxable_income REAL, excess_bii REAL` -- PK `(partnership_id, partner_id, year)`.

Table `ebie_balances` -- `entity_id TEXT, partnership_id TEXT, year INTEGER, balance REAL` -- PK `(entity_id, partnership_id, year)`.

Table `loan_recharacterizations` -- `loan_id TEXT, recharacterized INTEGER, recharacterized_amount REAL, annual_interest_removed REAL` -- PK `(loan_id)`.

**Report** (`/app/report.json`): The `report` target must use `sqlite3` (not Python) to query the database and `jq` to assemble the final JSON. Required keys: `total_entities` (int, distinct entity count), `total_entity_years` (int), `aggregate_deductible` (float), `aggregate_disallowed` (float), `recharacterized_loans` (int, count where recharacterized=1), `total_interest_removed` (float), `max_carryforward_entity` (string, entity_id with highest carryforward_bie), `max_carryforward_amount` (float), `ebie_fully_resolved` (int, ebie_balances rows where balance rounds to 0).
