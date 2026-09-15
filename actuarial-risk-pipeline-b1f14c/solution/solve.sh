#!/bin/bash

# Replace the buggy risk_pipeline.R with the corrected version
cp /solution/risk_pipeline_fixed.R /app/risk_pipeline.R

# Run the pipeline to produce results.json
Rscript /app/run_pipeline.R
