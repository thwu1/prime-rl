#!/bin/bash

pip3 install numpy==2.1.3 -q

cd /app

# Run the DCA pipeline (produces results.json, score matrices, gnuplot scripts, and TSV report)
python3 /solution/dca_pipeline.py

# Generate contact map heatmap PNGs using gnuplot
echo "Generating contact map heatmaps with gnuplot..."
gnuplot /app/plot_family_1.gp
gnuplot /app/plot_family_2.gp
gnuplot /app/plot_family_3.gp
echo "Heatmap generation complete."

# Verify outputs exist
ls -la /app/results.json /app/contact_map_family_*.png /app/pipeline_report.tsv
