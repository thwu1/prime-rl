A broken workbook generator at `/app/build_workbook.py` reads CSV data from `/data/` (transactions, products, employees, budgets) and produces `/app/output/consolidated_report.xlsx`. The script crashes on the production CSVs and contains formula errors, missing features, and structural bugs. Fix the pipeline end-to-end so it produces a correct six-sheet workbook.

## Data issues in the CSVs

The CSVs contain mixed date formats (YYYY-MM-DD and M/D/YYYY), currency symbols and commas in numeric fields, inconsistent region casing, and whitespace in employee names. The script does not handle any of these.

## Required sheets and formulas

**Transactions** — Revenue via `Quantity*UnitPrice` (not addition). Cost via `XLOOKUP` into the Products sheet (not VLOOKUP). Profit, profit margin (`Profit/Revenue`), and fiscal quarter derived from `INT((MONTH-1)/3)+1`. Conditional formatting: flag margins below 10% and above 30%.

**Products** — Aggregated metrics using `SUMIFS`/`COUNTIFS` (not SUMIF/COUNTIF): total units sold, total revenue, transaction count, average order size. Profitability tier via `IFS` based on catalog margin bands (>40% High, >20% Medium, else Low).

**Employees** — Tenure in years from hire date via `TODAY()`. Salary band via `IFS` (Executive ≥100k / Senior ≥75k / Mid ≥50k / Junior). Annual bonus using nested `IF`/`AND` logic rewarding longer-tenured mid-level employees more generously.

**RegionalSummary** — Quarterly revenue matrix for all five regions (North, South, East, West, Central) using `SUMIFS`. Per-quarter stats rows: `AVERAGEIFS`, `COUNTIFS`, `MAXIFS`, `MINIFS`. Total column via `SUM`.

**FinancialModel** — Parameters: initial investment, discount rate, loan amount, annual rate, loan term. Cash flow schedule with year-0 referencing the investment cell. Metrics: `NPV` (using a `DiscountRate` named range), `IRR`, monthly `PMT`, total loan cost, total interest, 5-year `FV`. Data validation on the rate and investment cells.

**Dashboard** — Cross-sheet executive summary with live formulas (not hardcoded values): top/bottom products by revenue via `INDEX`/`MATCH`/`MAX`/`MIN` into Products, total revenue via `SUM` into Transactions, transaction count via `COUNTA`, average transaction value, and best Q1 region via cross-sheet reference to RegionalSummary. Conditional formatting on revenue total.

## Named ranges required

`DiscountRate`, `InitialInvestment`, `CashFlows`, `TransactionRevenue`, `ProductCatalog`.

## Constraints

All computed cells must contain live Excel formulas, not precomputed Python values. The final workbook must be at `/app/output/consolidated_report.xlsx`.