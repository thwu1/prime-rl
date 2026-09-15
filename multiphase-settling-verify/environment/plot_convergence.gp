# MMS Grid Convergence Plot
# Reads convergence data and produces a log-log plot with fitted order

set terminal postscript eps enhanced color font "Helvetica,14"
set output "convergence.eps"

set xlabel "Grid cells (N)"
set ylabel "L_2 error norm"

set logscale x

set title "MMS Grid Convergence Study"
set key top right box

# Linear fit on the data
f(x) = a * x + b
fit f(x) "convergence.tsv" using 1:2 via a, b

plot "convergence.tsv" using 3:4 with linespoints pt 7 ps 1.5 title "L_2 norm", \
     f(x) with lines lw 2 title sprintf("Slope = %.2f", a)
