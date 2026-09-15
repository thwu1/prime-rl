#
# Gnuplot script: P-h diagram for transcritical CO2 cycle

set terminal pngcairo size 800,600 enhanced font 'Arial,12'
set output '/app/ph_diagram.png'

set title 'Transcritical CO2 Refrigeration Cycle - P-h Diagram'
set xlabel 'Specific Enthalpy (kJ/kg)'
set ylabel 'Pressure (MPa)'
set logscale y
set grid
set key off

# Read state points from results.json via inline system calls
M = 0.0440098  # kg/mol

h1 = system("python3 -c \"import json; d=json.load(open('/app/results.json')); print(d['state1']['h_J_mol'] / 0.0440098 / 1000)\"") + 0
p1 = system("python3 -c \"import json; d=json.load(open('/app/results.json')); print(d['state1']['P_Pa'] / 1e6)\"") + 0
h2 = system("python3 -c \"import json; d=json.load(open('/app/results.json')); print(d['state2']['h_J_mol'] / 0.0440098 / 1000)\"") + 0
p2 = system("python3 -c \"import json; d=json.load(open('/app/results.json')); print(d['state2']['P_Pa'] / 1e6)\"") + 0
h3 = system("python3 -c \"import json; d=json.load(open('/app/results.json')); print(d['state3']['h_J_mol'] / 0.0440098 / 1000)\"") + 0
p3 = system("python3 -c \"import json; d=json.load(open('/app/results.json')); print(d['state3']['P_Pa'] / 1e6)\"") + 0
# State 4: isenthalpic expansion from state 3 to evaporator pressure
h4 = h3
p4 = p1

set label 1 '1' at h1, p1 point pt 7 ps 1.5 offset 1,1
set label 2 '2' at h2, p2 point pt 7 ps 1.5 offset 1,1
set label 3 '3' at h3, p3 point pt 7 ps 1.5 offset -2,1
set label 4 '4' at h4, p4 point pt 7 ps 1.5 offset -2,-1

# Write cycle data to temporary file (inline data blocks cannot expand variables)
set print '/app/_cycle_data.tmp'
print sprintf("%g %g", h1, p1)
print sprintf("%g %g", h2, p2)
print sprintf("%g %g", h3, p3)
print sprintf("%g %g", h4, p4)
print sprintf("%g %g", h1, p1)
set print

# Plot cycle as connected lines: 1->2->3->4->1
set style line 1 lc rgb '#0060ad' lw 2 dt 1
plot '/app/_cycle_data.tmp' using 1:2 with linespoints ls 1 pt 7 ps 1.5
