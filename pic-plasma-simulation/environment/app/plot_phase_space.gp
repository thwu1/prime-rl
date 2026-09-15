# Phase-space plot for two-stream instability
set terminal png size 800,600
set output '/app/output/phase_plot.png'

set title "Two-Stream Instability: Phase Space (x, v)"
set xlabel "Position x"
set ylabel "Velocity v"
set grid

plot '/app/output/phase_space.dat' using 1:2 with dots lc rgb "blue" notitle
