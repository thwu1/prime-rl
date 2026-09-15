#!/bin/bash

cd /app

# Install the complete C source with analytical Jacobian
cp /solution/robertson_complete.c /app/robertson_ext.c

# Compile
R CMD SHLIB robertson_ext.c

# Run the solver benchmark and generate output
Rscript /solution/solve_driver.R
