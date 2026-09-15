A corrupted multi-sheet financial analysis workbook has been partially recovered. The raw data is in `/app/data/` (CSV files: `transactions.csv`, `products.csv`, `employees.csv`, `regions.csv`). The original workbook's formula specification is at `/app/workbook_spec.json`.

The formula specification contains errors — formulas that were incorrectly modified during prior maintenance. The authoritative business requirements at `/app/business_rules.json` describe what each calculation should produce. Some discrepancies are explicit; others require domain expertise in financial reporting conventions, statistical methodology, and Excel function semantics to identify.

## Deliverables

**`/app/financial_analysis.db`** — SQLite database containing:
- Base tables loaded from CSVs with proper types, primary keys, and foreign key constraints
- SQL views implementing the CORRECT business logic per `business_rules.json` (not the buggy spec):
  - `enriched_transactions` — per-transaction lookups and computed financial metrics (500 rows)
  - `region_category_summary` — aggregations grouped by (region_name, category), including revenue-weighted discount computation
  - `employee_performance` — per-employee metrics with NETWORKDAYS tenure calculation (10 rows, all employees)
  - `inventory_status` — per-product stock analysis with status classification (20 rows, all products)
  - `quarterly_revenue` — quarterly aggregation with top-category identification and sequential growth tracking
- All views must use standard SQLite SQL only — no custom functions or extensions

**`/app/audit_report.json`** — structured report documenting every root-cause formula error found in the workbook spec:

    {
      "formula_errors": [
        {
          "view_name": "<view containing the error>",
          "column_name": "<column with the incorrect formula>",
          "error_description": "<what the spec gets wrong and what the correct behavior should be>"
        }
      ]
    }

Report only root-cause errors. If a downstream column produces wrong values solely because an upstream formula is incorrect, report the upstream formula — not the downstream symptom.