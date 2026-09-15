-- FuzzBench coverage data extraction
-- Extracts final coverage snapshot per fuzzer/benchmark/trial
.mode csv
.headers on
.output /app/pipeline/tmp/final_coverage.csv
SELECT
    c.fuzzer,
    c.benchmark,
    c.trial_id,
    c.edges_covered AS final_edges
FROM coverage c
INNER JOIN (
    SELECT fuzzer, benchmark, trial_id, MIN(time) AS final_time
    FROM coverage
    GROUP BY fuzzer, benchmark, trial_id
) latest ON c.fuzzer = latest.fuzzer
    AND c.benchmark = latest.benchmark
    AND c.trial_id = latest.trial_id
    AND c.time = latest.final_time
ORDER BY c.benchmark, c.fuzzer, c.trial_id;
.quit
