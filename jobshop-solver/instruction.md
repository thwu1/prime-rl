A MIP-based solver for the Job Shop Scheduling Problem was developed at `/app/pipeline/` using GLPK's `glpsol` and a GMPL (GNU MathProg) model. It reads OR-Library benchmark instances from `/app/instances/` and is invoked via `/app/pipeline/run.sh`.

The pipeline currently fails to produce correct schedules. Diagnose all issues, fix the pipeline, and produce valid schedules meeting the quality targets below. Write final output to `/app/output/<instance>.csv`.

## Output Format

Each CSV: header `job,operation,machine,start,end` followed by one row per operation. All fields are 0-indexed integers. `end = start + processing_time`.

## Quality Targets

| Instance | Size  | Max Makespan |
|----------|-------|--------------|
| ft06     | 6×6   | 55           |
| la01     | 10×5  | 720          |
| la02     | 10×5  | 710          |
| la03     | 10×5  | 650          |

Schedules must be feasible: correct machine assignments matching the instance, correct processing durations, job operation precedence respected, and no overlapping operations on any machine.