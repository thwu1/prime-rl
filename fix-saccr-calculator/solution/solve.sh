#!/bin/bash

# Deploy corrected SA-CCR calculator files and produce results
cp /solution/core_fixed.R /app/core.R
cp /solution/addons_fixed.R /app/addons.R
cp /solution/saccr_fixed.R /app/saccr.R
Rscript /app/saccr.R
