set terminal png size 800,800
set output '/app/output/divB_map.png'
set title '|div B|'
set xlabel 'x'
set ylabel 'y'
set size ratio 1
set pm3d map
splot '/app/output/divB_abs.dat' matrix with pm3d notitle
