# Corrected MMS Grid Convergence Plot
set terminal pngcairo enhanced size 800,600
set output "convergence.png"

set xlabel "Grid cells (N)"
set ylabel "L_2 error norm"

set logscale xy

set title "MMS Grid Convergence Study"
set key top right

f(x) = a * x**(-p)
a = 1.0
p = 2.0
fit f(x) "convergence.tsv" using 1:2 via a, p

plot "convergence.tsv" using 1:2 with linespoints pt 7 ps 1.5 title "L_2 norm", \
     f(x) with lines lw 2 title sprintf("Fitted order = %.2f", p)
