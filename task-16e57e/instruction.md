`/app/newton_schulz.py` contains an incomplete library for computing the polar factor of matrices via iterative methods. A reference SVD-based implementation (`polar_decomposition_svd`) is provided. All other functions raise `NotImplementedError`.

Algorithm parameters are stored in a SQLite database at `/app/coefficients.db`. A supplementary coefficient set is stored in a MATLAB-format data file at `/app/extra_coefficients.mat`. Use appropriate command-line tools to explore these data sources and understand their structure — the database schema is not documented elsewhere.

Complete the following:

1. Implement all unimplemented functions in `/app/newton_schulz.py` so that `/tests/test_state.py` passes. Examine the function signatures, docstrings, and test expectations to determine the correct behavior.

2. Extract the coefficient data from `/app/extra_coefficients.mat` and insert it into `/app/coefficients.db` as a new coefficient set named `tuned_v2`, following the existing database schema.

3. Generate `/app/verification_report.csv` by querying the database with the `sqlite3` command-line tool. The report must contain one row per coefficient set with columns: `name`, `num_iterations`, `mean_a`, `mean_b`, `mean_c` — computed from the stored coefficients.