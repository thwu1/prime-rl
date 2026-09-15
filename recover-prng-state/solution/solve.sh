#!/bin/bash

cd /app

echo "=== Step 1: Disassemble all generators ==="
for gen in gen_alpha gen_beta gen_gamma; do
    echo "Disassembling /app/$gen..."
    objdump -d /app/$gen > /tmp/disasm_$gen.txt
    echo "  $(wc -l < /tmp/disasm_$gen.txt) lines"
done

echo ""
echo "=== Step 2: Compile LCG brute-force helper ==="
gcc -O2 -o /tmp/lcg_crack /solution/lcg_crack.c
echo "Compiled /tmp/lcg_crack"

echo ""
echo "=== Step 3: Run forensic analysis and security evaluation ==="
python3 /solution/solve_forensic.py

echo ""
echo "=== Step 4: Deploy PRNG classifier ==="
cp /solution/classifier_src.py /app/classifier.py
chmod +x /app/classifier.py
echo "Classifier deployed to /app/classifier.py"

echo ""
echo "=== All outputs written ==="
ls -la /app/matching.txt /app/predictions_*.txt /app/weakest.txt /app/classifier.py /app/assessment.json
