A warehouse management SQLite database at `/data/warehouse.db` was assembled from heterogeneous sources during a systems migration. Its pre-built reporting views produce incorrect financial results. An external supplier rate card at `/data/supplier_rates.csv` has not been integrated. The database contains self-documentation (`schema_docs` and `business_rules` tables).

Produce all output files in `/app/output/`:

**`view_evaluation.json`** — JSON array. For each pre-built view in the database, evaluate its correctness and provide: `view_name`, `diagnosis` (observed defect), `root_cause` (the specific SQLite type system behavior responsible), `severity` (`"critical"` if monetary values are affected, `"warning"` otherwise), and `corrected_sql` (a complete CREATE VIEW statement that fixes the defect when executed against the original database).

**`warehouse_hardened.db`** — A corrected copy of the database using SQLite STRICT tables with declared column types, foreign key REFERENCES declarations, and CHECK constraints enforcing documented business rules. All valid data must be migrated with type mismatches resolved to proper storage classes. Cycle-forming BOM edges must be excluded. Indeterminate costs must be resolved from the supplier rate card per business rules. Include corrected reporting views that produce accurate results with the clean data.

**`bom_costs.csv`** — Recursive BOM cost for every part where `category = 'assembly'`. Total cost = part's resolved unit cost + SUM(quantity × child total cost) for all BOM children, with cycle back-edges excluded. CSV: header `sku,total_cost`, costs to 2 decimal places.

**`valuation.csv`** — Total inventory value per warehouse, including inventory records with type-mismatched foreign keys. CSV: header `warehouse,total_value`, values to 2 decimal places.

**`audit.json`** — JSON object:
- `type_violations`: values whose SQLite storage class doesn't match `schema_docs`
- `cycles`: cycles in the BOM graph (each as a list of part IDs)
- `malformed_json`: parts with invalid JSON in `specs`
- `date_anomalies`: inventory rows with non-ISO-8601 `last_audit` dates, with normalized values