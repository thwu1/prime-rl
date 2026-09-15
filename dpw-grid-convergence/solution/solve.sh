#!/bin/bash

cd /app

# Run the analysis pipeline (parses data, computes convergence, writes JSON + SQLite + gnuplot files)
python3 /solution/analyze.py

# Generate convergence plots with gnuplot
cd /app/results/plots
for gp in plot_cl.gp plot_cd.gp plot_cm.gp; do
    gnuplot "$gp"
done
