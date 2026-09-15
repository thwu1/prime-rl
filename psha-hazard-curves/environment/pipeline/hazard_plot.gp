# Seismic hazard curve plot
# Reads hazard_curves.csv and produces a log-log hazard curve PNG

set output "/app/output/hazard_curve.png"

set title "Probabilistic Seismic Hazard Curve - PGA"
set xlabel "PGA (g)"
set ylabel "Annual Rate of Exceedance"

set logscale x
set logscale y
set grid
set key top right

set datafile separator " "

plot "/app/output/hazard_curves.csv" every ::1 using 1:2 with linespoints \
     title "Total Hazard" lw 2 pt 7 ps 1.2
