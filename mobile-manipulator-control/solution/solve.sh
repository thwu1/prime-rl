#!/bin/bash

pip3 install numpy==2.1.3 pyyaml==6.0.2 -q

# Deploy controller
cp /solution/youbot_controller.py /app/youbot_controller.py

# Run closed-loop simulation to produce error CSV
cd /app
python3 /solution/run_simulation.py

# Generate convergence plot with gnuplot
gnuplot /solution/plot_error.gp
echo "Wrote /app/error_plot.png"
