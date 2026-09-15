#!/bin/bash

# Deploy the fixed growth engine with all features
cp /solution/growth_engine_fixed.R /app/growth_engine.R

# Verify the engine loads and runs
Rscript -e 'source("/app/growth_engine.R"); cat("Engine loaded successfully\n")'
