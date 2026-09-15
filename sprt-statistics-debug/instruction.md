The `/app/` directory contains a broken SPRT (Sequential Probability Ratio Test) statistical analysis service used for chess engine regression testing. It has four components:

- **Statistical Engine** (`/app/stats/`): Core numerical computations for SPRT hypothesis testing and Elo estimation. Supports three Elo models (logistic, normalized, BayesElo). Contains bugs producing incorrect results.
- **Fastchess Output Parser** (`/app/parser.py`): Extracts game results from raw fastchess console output. Sample output files are in `/app/data/`. Currently incomplete and produces wrong results for several input formats.
- **REST API Server** (`/app/server.py`): Flask server with stubbed-out endpoints for submitting game results, computing SPRT analytics, and querying stored test runs. Backed by SQLite. Needs full implementation.
- **Mathematical Specification** (`/app/SPEC.md`): Reference document describing the correct formulas for the statistical computations.

Fix all bugs and complete all missing implementations so the full pipeline works end-to-end: raw fastchess output can be submitted, parsed, stored, analyzed, and retrieved through the REST API with correct statistical results across all three supported Elo models.