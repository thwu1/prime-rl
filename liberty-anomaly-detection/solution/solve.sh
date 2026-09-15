#!/usr/bin/env bash

set -e
cd /app

echo "=== Step 1: STA on original netlist ==="
python3 /solution/sta_engine.py /app/netlist.v /app/cells.lib 0.250 > /tmp/original_sta.json
cat /tmp/original_sta.json

echo ""
echo "=== Step 2: Re-synthesize with Yosys ==="
yosys -s /solution/synth.tcl 2>&1 | tail -20

echo ""
echo "=== Step 3: STA on optimized netlist ==="
python3 /solution/sta_engine.py /app/optimized_netlist.v /app/cells.lib 0.250 > /tmp/optimized_sta.json
cat /tmp/optimized_sta.json

echo ""
echo "=== Step 4: Simulate original netlist with iverilog ==="
iverilog -o /tmp/sim_orig -g2005 /app/cells_sim.v /app/netlist.v /solution/verify_tb.v
SIM_ORIG=$(vvp /tmp/sim_orig 2>&1)
echo "$SIM_ORIG"
ORIG_PASS=$(echo "$SIM_ORIG" | grep -c "PASS" || true)

echo ""
echo "=== Step 5: Simulate optimized netlist with iverilog ==="
iverilog -o /tmp/sim_opt -g2005 /app/cells_sim.v /app/optimized_netlist.v /solution/verify_tb.v
SIM_OPT=$(vvp /tmp/sim_opt 2>&1)
echo "$SIM_OPT"
OPT_PASS=$(echo "$SIM_OPT" | grep -c "PASS" || true)

SIM_OK=false
if [ "$ORIG_PASS" -ge 1 ] && [ "$OPT_PASS" -ge 1 ]; then
    SIM_OK=true
fi

echo ""
echo "=== Step 6: Generate final report ==="
python3 /solution/gen_report.py /tmp/original_sta.json /tmp/optimized_sta.json "$SIM_OK"
echo "Done. Report at /app/timing_report.json"
