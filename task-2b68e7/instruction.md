A PostgreSQL 16 database `alien_signals` is pre-loaded with alien signal detection data across multiple tables with cryptic column names. A domain knowledge base at `/app/knowledge_base.jsonl` describes hierarchical calculation formulas and classification rules used by signal analysts. The formulas have interdependencies — some composite metrics require computing simpler ones first.

PostgreSQL is installed but not running. Start it with `service postgresql start`. Connect with `psql -U postgres -d alien_signals` (trust auth configured).

Build a complete signal analysis and prioritization pipeline:

1. Study the knowledge base and database schema. Create PostgreSQL functions implementing these formulas: `calculate_snqi`, `calculate_tols`, `calculate_rpi`, `calculate_bfr`, `calculate_lif`, `calculate_aoi`, and `calculate_oqf`. Each must accept the parameters its formula requires and return NUMERIC. Note that `calculate_oqf` depends on pre-computed AOI and LIF values plus telescope pointing accuracy.

2. Create a materialized view `mv_signal_analysis` that joins signals with all relevant tables and for each signal computes columns: `signalregistry`, `telescref`, `observstation`, `snqi`, `tols`, `rpi`, `bfr`, `oqf`, `tols_category` (TEXT: 'Low'/'Medium'/'High' per TOLS Category rules in KB), `is_analyzable` (BOOLEAN per Analyzable Signals definition in KB), and `is_target_of_opportunity` (BOOLEAN per Target of Opportunity definition in KB).

3. Add columns `auto_snqi` (NUMERIC) and `analyzable` (BOOLEAN) to the `signals` table. Create a trigger that automatically computes these using `calculate_snqi` on every INSERT or UPDATE. Backfill all existing rows.

4. Export the materialized view to `/app/signal_report.csv` with headers.