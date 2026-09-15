A cross-language code translation benchmark evaluation pipeline lives at `/app/`. It ingests test execution data from 10 translated software projects spanning 5 test frameworks (JUnit/Maven, cargo test, pytest, go test, Google Test) across 6 language pairs, and produces an aggregated quality report at `/app/results.json`.

The pipeline reads raw benchmark data from `/data/benchmark/` (authoritative, do not modify), framework routing configuration from `/app/pipeline_config.json`, and is orchestrated via `make evaluate` in `/app/`.

## What is wrong

The pipeline has multiple interacting defects across its parsers, configuration layer, and statistical aggregation. These produce incorrect per-project test counts, corrupt language-pair aggregates, wrong overall statistics, and broken directional analysis (dynamic-to-static vs static-to-dynamic translation pairs). The defects span Python source files and the JSON configuration — diagnosing them requires understanding each test framework's output semantics and how the config routes framework identifiers to parser implementations.

Additionally, the `framework_analysis` section required by the output schema has not been implemented — only a stub exists at `/app/pipeline/framework_analyzer.py`. You must design and implement the aggregation logic for this component, computing per-test-framework metrics that correctly account for compile failures and framework-specific test counting conventions.

## Output specification

The output at `/app/results.json` must conform to the JSON Schema at `/app/output_schema.json`. The schema defines five required top-level sections:

- **`projects`**: Per-project results keyed by project ID. Each entry has: `source_lang` (string), `target_lang` (string), `compile_success` (boolean), `tests_passed` (integer >= 0), `tests_total` (integer >= 0), `pass_rate` (number in [0,1]), `all_tests_pass` (boolean).

- **`language_pairs`**: Aggregate statistics per `SourceLang_to_TargetLang` pair. Each entry has: `num_projects` (integer >= 1), `compile_rate` (number in [0,1]), `success_rate` (number in [0,1] — fraction where all tests pass), `avg_pass_rate` (number in [0,1] — mean of per-project pass rates, with compile-failed projects contributing 0.0).

- **`overall`**: Global statistics across all projects: `total_projects` (integer), `compile_rate`, `success_rate`, `avg_pass_rate` (all number in [0,1], same methodology as language_pairs — all projects in the denominator).

- **`directional_analysis`**: Contains `dynamic_to_static` and `static_to_dynamic` objects, each with: `pairs` (sorted array of language pair keys), `num_projects`, `compile_rate`, `success_rate`, `avg_pass_rate` (same methodology — all projects in the denominator including compile-failed ones contributing 0.0).

- **`framework_analysis`**: Per-test-framework aggregate metrics keyed by framework identifier (e.g., `junit`, `pytest`, `cargo_test`, `go_test`, `gtest`). Each entry has: `projects_using` (integer — count of projects using this framework regardless of compile status), `projects_compiled` (integer — count that compiled successfully), `total_tests_executed` (integer — sum of tests_total), `total_tests_passed` (integer — sum of tests_passed), `aggregate_pass_rate` (number in [0,1] — total_tests_passed / total_tests_executed, or 0.0 if none executed).

All floating-point values are rounded to 4 decimal places.

## Data exploration

Benchmark data at `/data/benchmark/` contains `manifest.json` and per-project directories with `meta.json`, `build.log`, and `test.log`. Use `jq`, `python3`, and standard tools to explore the raw data and verify your understanding of each test framework's output format.