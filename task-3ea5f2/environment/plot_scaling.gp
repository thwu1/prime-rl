# ATS-5 SPARTA Scaling Plot Template
# Modify and extend as needed for your analysis
#
# Expected data format in scaling_data.dat:
#   Column 1: node count
#   Column 2: FOM value (M-particle-steps/sec/node)
#
# Usage: gnuplot plot_scaling.gp
#   (after creating /app/scaling_data.dat with your data)

set terminal png size 800,600
set output "/app/scaling_plot.png"

set title "SPARTA Scaling"
set xlabel "Nodes"
set ylabel "FOM"

# TODO: Configure log scales for x-axis and/or y-axis
# TODO: Add grid lines
# TODO: Style data points and lines
# TODO: Add model fit curves from separate data files
# TODO: Add legend with model names and R-squared values

plot "/app/scaling_data.dat" using 1:2 with points title "Measured"
