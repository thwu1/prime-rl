The directory `/app/data/` contains six CSV files from the International Dataset of Flaky Tests (IDoFT), a community-curated dataset of flaky tests from real Java and Python projects:

- `pr-data.csv` — Java/Maven flaky tests (columns: Project URL, SHA Detected, Module Path, Fully-Qualified Test Name, Category, Status, PR Link, Notes)
- `gr-data.csv` — Java/Gradle flaky tests (same columns as pr-data.csv)
- `py-data.csv` — Python flaky tests (columns: Project URL, SHA Detected, Pytest Test Name, Category, Status, PR Link, Notes — no Module Path)
- `tso-iso-rates.csv` — Test-suite-order vs isolation failure rates with p-values and pass counts
- `tic-fic-data.csv` — Test-introducing commit (TIC) vs flakiness-introducing commit (FIC) data with timing info
- `odr-tests.csv` — Order-dependent test relationships mapping polluter/state-setter tests to their victims/brittle tests

Build a Python analysis pipeline at `/app/flaky_analyzer.py` that processes all six datasets and writes a JSON report to `/app/analysis_report.json`. The report must contain exactly these top-level keys with the specified nested structure:

**`dataset_summary`**: Row counts and unique project counts for each dataset file. Keys: `pr_data_rows`, `gr_data_rows`, `py_data_rows`, `pr_unique_projects`, `gr_unique_projects`, `py_unique_projects` (all integers).

**`category_fix_rates`**: For each flakiness category appearing in `pr-data.csv`, compute fix rates. Some rows have multiple categories separated by `;` — count each category occurrence independently. For each category, report: `total` (number of occurrences), `accepted` (occurrences where Status is "Accepted"), `with_status` (occurrences where Status is non-blank), `fix_rate` (accepted / with_status, or 0.0 if with_status is 0). Category keys should be the raw category strings (e.g., "ID", "OD", "OD-Vic").

**`order_dependency_graph`**: From `odr-tests.csv`, compute: `total_relationships` (row count), `unique_od_tests` (distinct values in OD-test column), `unique_projects` (distinct Project URL values), `victim_count` (rows where OD-test-type is "victim"), `brittle_count` (rows where OD-test-type is "brittle"). Then build an undirected graph where nodes are test names and edges connect tests that co-occur in the same row across any pair of the three test columns (OD-test, Relevant-test VP/BSS, Relevant-test VPC). Deduplicate edges. Report: `num_nodes`, `num_edges`, `connected_components` (number of connected components), `largest_component_size`.

**`tic_fic_analysis`**: From `tic-fic-data.csv`: `total_tests`, `tic_equals_fic_true` (count where "TIC = FIC" is "TRUE"), `tic_equals_fic_false` (count where "TIC = FIC" is "FALSE"). For FALSE-only rows, compute: `mean_days_between` (mean of "Days Between TIC-FIC"), `median_days_between`, `max_days_between`.

**`tso_iso_analysis`**: From `tso-iso-rates.csv`: `total_tests`, `significant_count` (P-Value < 0.05), `nonsignificant_count`. Compute pass rates as (Number of Times Test Passed) / (Total Runs). Report: `mean_suite_pass_rate`, `mean_isolation_pass_rate` (across all tests). `suite_worse_count`: among significant tests, how many have suite pass rate strictly less than isolation pass rate.

**`cross_dataset_analysis`**: `projects_in_all_java_datasets` — sorted list of Project URLs appearing in all three of pr-data.csv, tso-iso-rates.csv, and odr-tests.csv. `unique_odr_tests_in_pr_data` — count of distinct (Project URL, OD-test) pairs from odr-tests.csv that also appear in pr-data.csv (matching on Project URL and Fully-Qualified Test Name). `unique_odr_tests_accepted` — of those, how many have Status "Accepted" in pr-data.csv.

All float values should be JSON numbers (not strings). Run the analyzer via `python3 /app/flaky_analyzer.py`.