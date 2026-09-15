# Gnuplot script: robust vs baseline trajectory comparison

set terminal png size 800,600 enhanced font "sans,12"
set output '/app/output/trajectory_plot.png'
set datafile separator ','
set xlabel 'X (m)'
set ylabel 'Y (m)'
set title 'Robust vs Baseline EKF Trajectory'
set key left top
set grid
plot '/app/output/trajectory.csv' every ::1 using 2:3 with lines linewidth 2 title 'Robust EKF', \
     '/app/output/baseline_trajectory.csv' every ::1 using 2:3 with lines linewidth 1 dashtype 2 title 'Baseline EKF'
