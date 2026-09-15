#!/usr/bin/env bash

set -euo pipefail

# Install corrected source files (fixes 9 bugs across 3 R files)
cp /solution/transforms_fixed.R /app/lib/transforms.R
cp /solution/statistics_fixed.R /app/lib/statistics.R
cp /solution/pipeline_fixed.R /app/pipeline.R

# Install the missing robust statistics module
cp /solution/robust.R /app/lib/robust.R

# Run the corrected pipeline
Rscript /app/pipeline.R
