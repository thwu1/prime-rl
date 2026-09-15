A multi-stage COCO benchmarking pipeline at `/app/` processes raw optimization experiment data (TSV files in `/app/raw_data/`) through a C data converter, SQLite database, and Python analysis modules to produce performance metrics following Hansen et al.'s methodology (*Optimization Methods and Software*, 2021).

The pipeline is orchestrated by `/app/run_pipeline.sh`:
1. Compiles a C data converter (`/app/converter/`) via `make` that imports TSV run data into a SQLite database
2. Runs Python analysis modules (`/app/pipeline/`) that read from the database and compute ERT, ECDF, algorithm rankings, and dimension-scaling exponents
3. Writes final results to `/app/output/report.json`

The pipeline currently fails to build and, once build issues are resolved, produces incorrect results due to flawed methodology choices across multiple stages. Properties that correct results must satisfy are documented in `/app/properties.json`. The expected output schema is in `/app/schema.json`.

Additionally, the pipeline is missing a comparative analysis component specified in `/app/schema.json` that must be designed and implemented from scratch:

- **Virtual Best Solver (VBS)**: For each (function, dimension, target) scenario, compute the oracle lower bound — the minimum achievable ERT across all algorithms — and identify which algorithm achieves it (ties broken alphabetically).
- **Performance Profile**: Following Dolan & Moré's methodology, compute for each algorithm at thresholds τ ∈ {1.0, 1.5, 2.0, 5.0, 10.0} the fraction of solvable scenarios where the algorithm's ERT ≤ τ × VBS ERT. Only scenarios where at least one algorithm has finite ERT count toward the denominator.

Evaluate all methodology choices against the mathematical properties in `/app/properties.json`, correct the pipeline, design and implement the comparative analysis, and write the complete validated output to `/app/results.json`.