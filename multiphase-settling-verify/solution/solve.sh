#!/bin/bash


# Step 1: Compute correct results, query normalized DB, write report.json and convergence.tsv
python3 /solution/solver.py

# Step 2: Install correct gnuplot script and generate convergence plot
cp /solution/plot_convergence_fixed.gp /app/plot_convergence.gp
cd /app && gnuplot plot_convergence.gp 2>/dev/null

echo "Pipeline complete: report.json, convergence.tsv, convergence.png"
