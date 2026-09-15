A supply chain analytics warehouse at `/app/warehouse.duckdb` was populated from upstream source systems via an automated ETL pipeline. Archived exports from the upstream systems are under `/app/sources/` (see `/app/sources/manifest.txt`).

The warehouse may contain data quality issues from the ETL process. The source system exports may also have their own quality characteristics — no single data source is guaranteed to be the authoritative ground truth for all attributes. Cross-validate all available data sources against each other, identify and quantify any systematic discrepancies, determine which source is most trustworthy for each data element, and produce reconciled analytical results.

DuckDB CLI is available as `duckdb`. Write `/app/results.json` containing:

- **revenue_by_region**: Object mapping each region name (string) to total line item revenue (float, 2 decimal places). Revenue per line item = `l_extendedprice * (1 - l_discount)`, attributed to the customer's region via customer → nation → region.
- **top_supplier_by_availability**: The `s_name` (string) of the supplier with the highest total `ps_availqty` across all parts they supply. Break ties alphabetically.
- **returned_revenue_fraction**: Fraction of total revenue attributable to returned items (`l_returnflag = 'R'`), as float with 6 decimal places.
- **urgent_order_revenue_1995**: Sum of `o_totalprice` for orders with `o_orderpriority = '1-URGENT'` placed in 1995 (`o_orderdate` in [1995-01-01, 1996-01-01)), as float with 2 decimal places.
- **avg_supplycost_europe**: Average `ps_supplycost` for part-supplier relationships involving suppliers located in the EUROPE region, as float with 2 decimal places.
- **priority_fulfillment_rate**: Object mapping each `o_orderpriority` value (string) to the fraction of its line items fulfilled on time (`l_receiptdate <= l_commitdate`), as float with 4 decimal places. Only for orders placed in 1995 (`o_orderdate` in [1995-01-01, 1996-01-01)).