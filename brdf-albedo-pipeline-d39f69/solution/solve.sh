#!/bin/bash

# Deploy fixed R source files
cp /solution/fixed_kernels.R /app/kernels.R
cp /solution/fixed_pipeline.R /app/brdf_pipeline.R

# Run the corrected pipeline
Rscript /app/brdf_pipeline.R
