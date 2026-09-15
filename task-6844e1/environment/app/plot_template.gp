# Dirty Page Write Throttle — Convergence Plot
#
# Generates a convergence plot from simulation CSV data.
# Reads: /app/results/simulation.csv
# Writes: /app/results/convergence.png
#
# CSV format (with header): tick,nr_dirty,setpoint,limit,ssd_dirty,hdd_dirty
#
# Usage:
#   gnuplot /app/plot_template.gp

set terminal png size 1200,600
set output '/app/results/convergence.png'

set title "Dirty Page Write Throttle — Convergence"
set xlabel "Tick"
set ylabel "Dirty Pages"
set grid
set key top right

set datafile separator ","

plot '/app/results/simulation.csv' every ::1 using 1:2 with lines title "Total Dirty" lw 2, \
     '' every ::1 using 1:3 with lines title "Setpoint" lw 2 dt 2, \
     '' every ::1 using 1:4 with lines title "Limit" lw 1 dt 3, \
     '' every ::1 using 1:5 with lines title "SSD Dirty" lw 1, \
     '' every ::1 using 1:6 with lines title "HDD Dirty" lw 1
