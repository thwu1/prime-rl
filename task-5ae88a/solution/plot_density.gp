# Gnuplot script for density contour visualization
set terminal pngcairo size 800,800 enhanced
set output '/app/density_contour.png'
set title 'Final Density Field' font ',14'
set xlabel 'x'
set ylabel 'y'
set pm3d map
set size ratio 1
set palette rgbformulae 33,13,10
splot '/app/density_final.dat' matrix with pm3d notitle
