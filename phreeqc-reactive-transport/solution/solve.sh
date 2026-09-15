#!/bin/bash

set -e

# ---- Build PHREEQC from source ----
cd /app/phreeqc3_src
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release > /dev/null 2>&1
make -j"$(nproc)" > /dev/null 2>&1

# Locate the binary
PHREEQC_BIN=""
for candidate in \
    /app/phreeqc3_src/build/phreeqc \
    /app/phreeqc3_src/build/src/phreeqc \
    /app/phreeqc3_src/build/phreeqc3 \
    /app/phreeqc3_src/build/src/phreeqc3; do
    if [ -x "$candidate" ]; then
        PHREEQC_BIN="$candidate"
        break
    fi
done

if [ -z "$PHREEQC_BIN" ]; then
    PHREEQC_BIN=$(find /app/phreeqc3_src/build -name "phreeqc*" -type f -executable 2>/dev/null | head -1)
fi

if [ -z "$PHREEQC_BIN" ]; then
    echo "ERROR: Could not find PHREEQC binary after build"
    exit 1
fi

PHREEQC_DB=/app/phreeqc3_src/database/phreeqc.dat
echo "PHREEQC binary: $PHREEQC_BIN"
echo "Database: $PHREEQC_DB"

# ---- Write the corrected model ----
# The original drain_model.pqi has five errors that must be fixed:
#   1. Initial porewater (SOLUTION 1-10) is missing Alkalinity specification
#   2. Calcite equilibrium target SI is -2.0 instead of 0.0
#   3. Transport boundary conditions are 'constant constant' instead of 'flux flux'
#   4. Dispersivity is 1.0 m instead of 0.05 m
#   5. SELECTED_OUTPUT is missing -totals and -equilibrium_phases directives
python3 /solution/write_corrected_model.py

# ---- Run corrected simulation ----
"$PHREEQC_BIN" /app/corrected_model.pqi /app/simulation_output.txt "$PHREEQC_DB"
echo "Simulation complete."

# ---- Parse output and write results ----
python3 /solution/parse_output.py
