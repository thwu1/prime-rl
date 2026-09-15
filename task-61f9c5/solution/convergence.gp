# Dirty page ratio convergence plot
# Plots dirty_ratio vs tick for all three scenarios
#

set terminal png size 1200,600
set output '/app/output/convergence.png'

set title 'Dirty Page Ratio Convergence Across Scenarios'
set xlabel 'Tick'
set ylabel 'Dirty Ratio'
set key outside right top
set grid
set datafile separator ","

set yrange [0:0.8]

# Setpoint reference line at 0.40
set arrow from graph 0, first 0.40 to graph 1, first 0.40 nohead lt 0 lw 2
set label "setpoint (0.40)" at graph 0.01, first 0.42 font ",9"

plot '/app/output/symmetric_timeseries.csv' every ::1 using 1:2 with lines title 'symmetric' lw 2, \
     '/app/output/bursty_timeseries.csv' every ::1 using 1:2 with lines title 'bursty' lw 2, \
     '/app/output/asymmetric_timeseries.csv' every ::1 using 1:2 with lines title 'asymmetric' lw 2
