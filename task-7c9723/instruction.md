Build a placement optimizer and routing analysis pipeline for the Tenstorrent Wormhole AI accelerator's Network-on-Chip that solves DRAM reader placement, analyzes link-level traffic, persists data in SQLite, and generates Graphviz routing diagrams.

Read `/app/arch_spec.md` for the NoC routing model, link utilization analysis, and bandwidth formulas. Read `/app/chip_config.json` for the grid topology and six test scenarios with varying harvesting patterns. See `/app/output_schema.json` for the JSON output format and `/app/db_schema.sql` for the required SQLite database schema.

Create `/app/placer.py` that processes all scenarios and produces:

- `/app/results.json` — minimum-total-hop congestion-free placements with link utilization metrics and bandwidth estimates for each scenario, following `/app/output_schema.json`.
- `/app/noc_analysis.db` — SQLite database with placement data, return-path link traversals, per-link utilization counts, and scenario summaries, following the schema in `/app/db_schema.sql`.
- `/app/viz/<scenario>.dot` and `/app/viz/<scenario>.svg` — Graphviz visualizations of the 10x12 grid showing DRAM banks, reader positions, harvested tiles, and color-coded return paths per NoC, rendered via the `neato` layout engine with pinned node positions.

The hardest scenario has five harvested rows. Multiple displaced banks are forced onto a single available row across different columns, and the optimal placement requires considering inter-bank displacement trade-offs that simple ordered-iteration approaches will miss.