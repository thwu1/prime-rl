#!/bin/bash
# Solution for methanol solvation free energy task
#
#
# Fixes four bugs:
#   1. fep.mdp: couple-moltype = SOL  ->  MOL   (couple methanol, not water)
#   2. fep.mdp: sc-alpha = 0.0        ->  0.5   (enable soft-core for vdW)
#   3. fep.mdp: nstdhdl = 0           ->  50    (enable dH/dl output for BAR)
#   4. run_fep.sh: sed "s/LAMBDA_STATE/..."  ->  sed "s/LAMBDA_INDEX/..."
#      (match the actual placeholder in the MDP)

cd /app

# --- Step 1: Fix bugs in fep.mdp ---
sed -i 's/^couple-moltype.*=.*SOL/couple-moltype           = MOL/' /app/fep.mdp
sed -i 's/^sc-alpha.*=.*0\.0/sc-alpha                 = 0.5/' /app/fep.mdp
sed -i 's/^nstdhdl[[:space:]]*=[[:space:]]*0[[:space:]]*$/nstdhdl                  = 50/' /app/fep.mdp

# --- Step 2: Fix bug in run_fep.sh ---
sed -i 's/LAMBDA_STATE/LAMBDA_INDEX/g' /app/run_fep.sh

# --- Step 3: Run FEP pipeline ---
NUM_LAMBDAS=11

for i in $(seq 0 $((NUM_LAMBDAS - 1))); do
    echo "=== Lambda window $i ==="
    mkdir -p /app/lambda_${i}

    # Substitute lambda index into MDP template
    sed "s/LAMBDA_INDEX/$i/g" /app/fep.mdp > /app/lambda_${i}/grompp.mdp

    gmx grompp -f /app/lambda_${i}/grompp.mdp \
               -c /app/system.gro \
               -p /app/topol.top \
               -o /app/lambda_${i}/fep.tpr \
               -maxwarn 5 2>&1

    if [ $? -ne 0 ]; then
        echo "ERROR: grompp failed for lambda $i"
        continue
    fi

    cd /app/lambda_${i}
    gmx mdrun -s fep.tpr -dhdl dhdl.xvg -e fep.edr -g fep.log \
              -o fep.trr -c fep.gro -ntmpi 1 -ntomp 1 2>&1

    if [ $? -ne 0 ]; then
        echo "ERROR: mdrun failed for lambda $i"
    fi

    cd /app
done

# --- Step 4: BAR analysis ---
echo "=== BAR Analysis ==="
DHDL_FILES=""
for i in $(seq 0 $((NUM_LAMBDAS - 1))); do
    if [ -f /app/lambda_${i}/dhdl.xvg ]; then
        DHDL_FILES="$DHDL_FILES /app/lambda_${i}/dhdl.xvg"
    fi
done

if [ -z "$DHDL_FILES" ]; then
    echo "ERROR: No dhdl.xvg files found"
    exit 1
fi

# Capture gmx bar output to file directly (avoids pipe buffering issues with tee)
gmx bar -f $DHDL_FILES -o /app/bar.xvg > /app/bar.log 2>&1
BAR_EXIT=$?
echo "gmx bar exit code: $BAR_EXIT"
echo "--- bar.log contents ---"
cat /app/bar.log
echo "--- end bar.log ---"

# --- Step 5: Extract solvation free energy ---
python3 /solution/extract_result.py
EXTRACT_EXIT=$?

# Fallback: if Python extraction failed, try direct grep
if [ $EXTRACT_EXIT -ne 0 ] || [ ! -f /app/result.txt ]; then
    echo "Python extraction failed (exit=$EXTRACT_EXIT), trying grep fallback..."

    # Try to find the total line and extract the number
    TOTAL_LINE=$(grep -i "total" /app/bar.log 2>/dev/null | head -1)
    if [ -n "$TOTAL_LINE" ]; then
        # Extract value after = or : sign
        RAW_VALUE=$(echo "$TOTAL_LINE" | grep -oP '(?<==)\s*[-+]?\d+\.?\d*' | head -1 | tr -d ' ')
        if [ -z "$RAW_VALUE" ]; then
            # Try extracting first significant float
            RAW_VALUE=$(echo "$TOTAL_LINE" | grep -oP '[-+]?\d+\.\d+' | head -1)
        fi
        if [ -n "$RAW_VALUE" ]; then
            # Ensure negative sign (solvation convention)
            python3 -c "
v = float('$RAW_VALUE')
if v > 0: v = -v
print(f'{v:.4f}')
" > /app/result.txt
            echo "Grep fallback result: $(cat /app/result.txt) kJ/mol"
        fi
    fi
fi

# Final verification
if [ -f /app/result.txt ]; then
    echo "Final result: $(cat /app/result.txt) kJ/mol"
else
    echo "ERROR: Failed to extract result from any source"
    exit 1
fi
