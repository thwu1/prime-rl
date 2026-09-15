# Gnuplot script: error convergence plot

set terminal pngcairo size 900,500 enhanced font 'Arial,11'
set output '/app/error_plot.png'
set datafile separator ','

set title 'End-Effector Error Convergence'
set xlabel 'Timestep'
set ylabel 'Error (rad / m)'
set key outside right top
set grid

plot '/app/error_data.csv' using 1:2 with lines lw 1.5 title 'wx', \
     '' using 1:3 with lines lw 1.5 title 'wy', \
     '' using 1:4 with lines lw 1.5 title 'wz', \
     '' using 1:5 with lines lw 1.5 title 'vx', \
     '' using 1:6 with lines lw 1.5 title 'vy', \
     '' using 1:7 with lines lw 1.5 title 'vz'
