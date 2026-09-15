# Gnuplot script for SDF cross-section visualization

set terminal pngcairo size 800,400
set output '/app/cross_section.png'
set xlabel 'x'
set ylabel 'SDF value'
set title 'Cross-section at y=0, z=0'
set grid
set key off
plot '/app/cross_section.dat' using 1:2 with lines lw 2 lc rgb '#0060ad'
