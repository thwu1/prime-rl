#!/bin/bash

# Replace the multi-stage pipeline with a standalone implementation that
# correctly handles all requirements:
# 1. NULL Parquet entries treated as resolved=false (not silently dropped)
# 2. SEM with Bessel's correction (sample variance, n-1 denominator)
# 3. Unbiased pass@k estimator: 1 - C(n-c,k)/C(n,k) from Chen et al.
# 4. Contamination with strict < date boundary and one-hop similarity
#    propagation from temporal sources only (no transitive)
# 5. Contamination uses full task set for temporal determination even
#    when evaluation is filtered by date window
# 6. Time-window filtering via --start-date/--end-date CLI arguments
# 7. Rankings sorted descending by resolved_rate
# 8. Task difficulty sorted ascending by mean_solve_rate
cp /solution/standalone_pipeline.py /app/src/pipeline.py

# Run the pipeline to generate the leaderboard
python3 /app/src/pipeline.py --data-dir /app/data --output /app/output/leaderboard.json
