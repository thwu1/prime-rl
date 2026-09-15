A fuzzing benchmark experiment measured edge coverage for four fuzzers across four C/C++ targets with five independent trials each. Coverage data is stored in two different formats: binary FCOV files at `/app/data/{fuzzer}/{benchmark}/trial_*/coverage.cov` for some benchmarks, and rows in a SQLite database at `/app/data/experiment.db` for others. `/app/data/meta.json` indicates which benchmarks use which storage format. Tversky-index scoring coefficients are stored exclusively in the database's `config` table — they are absent from `meta.json`.

Data format details including the binary FCOV specification and database schema are at `/app/docs/data_format.md`. The FCOV binary format stores cumulative edge sets at each snapshot; the SQLite coverage table uses different storage semantics that must be determined by inspecting the actual data.

Design and implement a complete evaluation framework that reads both data formats, extracts scoring parameters from the database, computes Tversky-index novelty coverage scores according to `/app/docs/methodology.md`, produces cross-benchmark aggregate rankings with fractional ranking and proper tie-breaking, performs pairwise Mann-Whitney U statistical tests with Benjamini-Hochberg FDR correction across all benchmarks combined, and measures coverage velocity between measurement snapshots.

Produce output at `/app/output/` conforming to `/app/docs/output_schema.md`:
- `novelty_scores.json`
- `aggregate_ranking.json`
- `statistical_tests.json`
- `coverage_velocity.json`

A validated reference for one benchmark is at `/app/validation/expected_bloaty.json`. All output must be numerically correct for every benchmark in the experiment.