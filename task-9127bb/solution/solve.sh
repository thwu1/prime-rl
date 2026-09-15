#!/bin/bash


# Copy the reference optimizer to /app
cp /solution/optimizer.py /app/optimizer.py

# Verify the optimizer works on all programs
cd /app
declare -A INPUT_MAP
INPUT_MAP[prog1]=p1.txt
INPUT_MAP[prog2]=p2.txt
INPUT_MAP[prog3]=p3.txt
INPUT_MAP[prog4]=p4.txt
INPUT_MAP[prog5]=p5.txt

for p in prog1 prog2 prog3 prog4 prog5; do
    python3 /app/optimizer.py /app/programs/${p}.asm /tmp/${p}_opt.asm
    if [ $? -ne 0 ]; then
        echo "ERROR: Optimizer failed on ${p}"
        exit 1
    fi
    # Verify output matches using the Go VM binary
    ORIG_OUT=$(/app/vm /app/programs/${p}.asm < /app/inputs/${INPUT_MAP[$p]} 2>/dev/null)
    OPT_OUT=$(/app/vm /tmp/${p}_opt.asm < /app/inputs/${INPUT_MAP[$p]} 2>/dev/null)
    if [ "$ORIG_OUT" != "$OPT_OUT" ]; then
        echo "ERROR: Output mismatch on ${p}"
        echo "  Original: $ORIG_OUT"
        echo "  Optimized: $OPT_OUT"
        exit 1
    fi
done

echo "Optimizer deployed successfully to /app/optimizer.py"
