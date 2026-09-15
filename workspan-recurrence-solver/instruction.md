A SQLite database at `/app/parallel_costs.db` contains parallel algorithm definitions stored across a normalized relational schema (tables: `algorithms`, `work_recurrences`, `span_recurrences`, `base_cases`) and 19 analysis queries (table: `queries` with parameters encoded as JSON in `params_json`). An incomplete Makefile is at `/app/Makefile`.

Build a working `make results` pipeline that extracts algorithm definitions and query specifications from the database using `sqlite3`, computes exact integer answers for all 19 queries under the work-span parallel cost model, and assembles `/app/results.json` using `jq`. The results file must be a JSON object keyed by query ID (strings `"1"` through `"19"`), each containing the fields specified in that query's `output_fields`.

## Cost Model

- Work: `W(n) = branching_factor * W(n/divisor) + combine(n)`
- Span: `S(n) = critical_path_branches * S(n/divisor) + combine(n)`
- Brent's theorem: `T_P = ceil(W/P) + S`
- Parallel efficiency: `E = W / (P * T_P)`

Combine cost expressions reference variable `n` and function `log2()`. For granularity queries, `m` denotes the threshold size in the sequential base formula. All answers must be exact integers.

## Query Types

Discover the full specification of each query by examining its `params_json` field in the database. Types include recurrence evaluation, Brent's theorem application, algorithm composition pipelines, crossover analysis between algorithm variants, processor count optimization, minimum parallelism thresholds, granularity control for hybrid parallel/sequential execution, pipeline-level granularity optimization (optimizing one stage within a multi-algorithm pipeline), parallel efficiency thresholds, and granularity with alternative sequential base-case cost models.