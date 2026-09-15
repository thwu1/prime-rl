`/app/group_financials.xlsx` contains multi-subsidiary financial data for Nexus Global Holdings (four subsidiaries in USD, EUR, JPY, BRL). Examine all sheets — subsidiary financials, exchange rates, ownership stakes, intercompany transactions, and loan portfolio — to understand the dataset.

Produce `/app/consolidated.xlsx` with five sheets:

**ConsolidatedPL** — Group P&L in USD with multi-currency translation, intercompany elimination, and non-controlling interest allocation. Columns: Gross, IC Elimination, Net. Rows: Product Sales, Service Revenue, Licensing, Consulting, COGS, Salaries, Marketing, R&D, Depreciation, Total Revenue, Total Expenses, Net Income, Non-Controlling Interest, Net Income Attributable to Parent.

**Amortization** — Per-loan analysis keyed by Loan_ID: monthly payment, remaining principal, cumulative interest paid, cumulative principal paid, remaining interest.

**Ratios** — Post-elimination financial ratios: Gross Margin, Operating Margin, IC Revenue Pct, Expense Ratio, COGS Ratio.

**BreakEven** — CVP analysis: variable cost ratio, contribution margin ratio, break-even revenue. Classify Salaries/R&D/Depreciation as fixed; COGS/Marketing as variable.

**Sensitivity** — Consolidated net income (pre-NCI) when all non-USD exchange rates shift simultaneously by −20%, −10%, +10%, +20%.