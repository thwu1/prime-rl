# Mesh convergence plot for 1D Euler solver
set terminal png size 800,600
set output '/app/results/convergence.png'
set xlabel 'Mesh spacing (dx)'
set ylabel 'L1 density error'
set logscale xy
set title 'Mesh Convergence Study'
set key left top
set datafile separator ','
plot '/app/results/convergence_data.csv' every ::1 using 2:3 with linespoints pointtype 7 title 'L1 error', \
     '' every ::1 using 2:(column(2)) with lines dashtype 2 title 'O(1) reference'
