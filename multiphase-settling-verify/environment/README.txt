MFiX-lite Verification Pipeline
================================

This directory contains a multi-stage verification pipeline for a
simplified multiphase particle-settling simulation code.

Pipeline stages (coordinated by Makefile):
  1. Run verification analyses (mflow_verify.py -> results.json)
  2. Extract convergence data (extract_convergence.py -> convergence.tsv)
  3. Generate convergence plot (plot_convergence.gp -> convergence.png)
  4. Audit historical runs (requires querying history.db)
  5. Produce final report (report.json)

Files:
  mflow_verify.py        - Verification code (drag, settling, MMS)
  config.toml            - Physical and numerical parameters
  Makefile               - Pipeline orchestration (currently broken)
  extract_convergence.py - TSV extraction for gnuplot
  plot_convergence.gp    - gnuplot convergence visualization (currently broken)
  history.db             - SQLite database with historical run data
  expected_schema.json   - Required report format

Database schema (normalized across 5 tables):
  runs(run_id, code_version, run_date)
  drag_data(run_id, reynolds, cd_value)
  settling_params(run_id, terminal_velocity, reynolds_number)
  settling_fronts(run_id, eps_s0, settling_front, filling_front, hindered_velocity)
  mms_data(run_id, grid_level, l2_norm)

  A run_summary view joins across these tables for an overview.

  Reconstructing any single run's full results for comparison requires
  querying and joining across these tables.

Usage:
  make all    (should run the full pipeline -- currently broken)
