#!/bin/bash
# Run free energy perturbation pipeline for methanol solvation
# Uses BAR (Bennett Acceptance Ratio) to compute solvation free energy

NUM_LAMBDAS=11

echo "Starting FEP pipeline with $NUM_LAMBDAS lambda windows..."

for i in $(seq 0 $((NUM_LAMBDAS - 1))); do
    echo ""
    echo "============================================"
    echo " Lambda window $i / $((NUM_LAMBDAS - 1))"
    echo "============================================"

    mkdir -p /app/lambda_${i}

    # Create MDP for this lambda window by substituting the state index
    sed "s/LAMBDA_STATE/$i/g" /app/fep.mdp > /app/lambda_${i}/grompp.mdp

    # Preprocess
    gmx grompp -f /app/lambda_${i}/grompp.mdp \
               -c /app/system.gro \
               -p /app/topol.top \
               -o /app/lambda_${i}/fep.tpr \
               -maxwarn 5 2>&1

    if [ $? -ne 0 ]; then
        echo "ERROR: grompp failed for lambda $i"
        continue
    fi

    # Run simulation
    cd /app/lambda_${i}
    gmx mdrun -s fep.tpr -dhdl dhdl.xvg -e fep.edr -g fep.log \
              -o fep.trr -c fep.gro -ntmpi 1 -ntomp 1 2>&1

    if [ $? -ne 0 ]; then
        echo "ERROR: mdrun failed for lambda $i"
    fi

    cd /app
done

echo ""
echo "============================================"
echo " BAR Analysis"
echo "============================================"

# Collect dhdl files
DHDL_FILES=""
for i in $(seq 0 $((NUM_LAMBDAS - 1))); do
    if [ -f /app/lambda_${i}/dhdl.xvg ]; then
        DHDL_FILES="$DHDL_FILES /app/lambda_${i}/dhdl.xvg"
    fi
done

if [ -n "$DHDL_FILES" ]; then
    gmx bar -f $DHDL_FILES -o /app/bar.xvg 2>&1 | tee /app/bar.log
    # Extract result
    grep -i "total" /app/bar.log | head -1 | grep -oP '[-+]?\d+\.\d+' | head -1 > /app/result.txt
    echo ""
    echo "Solvation free energy: $(cat /app/result.txt) kJ/mol"
else
    echo "ERROR: No dhdl.xvg files found. Check simulation output."
fi
