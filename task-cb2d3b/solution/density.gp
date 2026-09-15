set terminal png size 800,800
set output '/app/output/density_contour.png'
set title 'Orszag-Tang Density (t=0.5)'
set xlabel 'x'
set ylabel 'y'
set size ratio 1
set pm3d map
set palette defined (0 "dark-blue", 0.5 "yellow", 1 "dark-red")
splot '/app/output/density.dat' matrix with pm3d notitle
