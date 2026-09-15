# Convergence plot for 1D Euler solver grid study
#
# Input:  /app/convergence_data.dat (columns: N, L2_error)
# Output: /app/convergence.png
#
# This script requires gnuplot with pngcairo terminal support.
# Usage: gnuplot plot_convergence.gp

# TODO: Set appropriate output terminal for PNG rendering
# TODO: Set output file path to /app/convergence.png

set xlabel 'N'
set ylabel 'Error'

# TODO: Both axes should use logarithmic scale for convergence analysis
# TODO: Add grid lines

# TODO: Plot convergence data with connected points
plot '/app/convergence_data.dat'
