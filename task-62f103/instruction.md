Biomechanical gait data from a multi-subject walking study is at `/app/data/` — joint angle time series, gait event timings, and subject anthropometrics for 2 subjects × 2 conditions × 3 runs (12 recording sessions total). The data was acquired using automated instrumentation with known measurement reliability issues.

`/app/config/pi_specification.yaml` defines all required performance indicator computations, output file structures, and analysis requirements.

Produce all specified outputs to `/app/output/` and create an executable pipeline entry point at `/app/run_pipeline.sh`.