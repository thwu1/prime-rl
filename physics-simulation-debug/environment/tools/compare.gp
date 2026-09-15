#!/usr/bin/gnuplot -persist
# compare.gp — Diagnostic comparison between simulation output and reference.
#
# Usage:
#   gnuplot -e "sim='ballistic'; col=0" /app/tools/compare.gp
#
# Generates /app/output/<sim>_cmp_<col>.png comparing state column <col>
# of the simulation output against reference data.
#
# Requires: python3, jq, gnuplot-nox

set terminal png size 900,500 enhanced
set output sprintf("/app/output/%s_cmp_%d.png", sim, col)
set title sprintf("%s — state[%d]: output vs reference", sim, col)
set xlabel "time"
set ylabel sprintf("state[%d]", col)
set grid

# Extract columns via python3 one-liners (works with any JSON structure)
ref_cmd = sprintf("python3 -c \"import json,sys; d=json.load(open('/app/reference/%s.json')); [print(t,d['data'][i][%d]) for i,t in enumerate(d['times'])]\"", sim, col)
out_cmd = sprintf("python3 -c \"import json,sys; d=json.load(open('/app/output/%s.json')); [print(t,d['data'][i][%d]) for i,t in enumerate(d['times'])]\"", sim, col)

plot sprintf("< %s", ref_cmd) using 1:2 with lines lw 2 title "reference", \
     sprintf("< %s", out_cmd) using 1:2 with lines lw 1 title "simulation"
