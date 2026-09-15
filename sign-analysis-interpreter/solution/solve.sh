#!/bin/bash

pip3 install lark==1.1.9 -q

cp /solution/grammar.lark /app/grammar.lark
cp /solution/analyzer_impl.py /app/analyzer.py

make -C /app check-grammar
echo ""
for prog in /app/programs/*.lang; do
    echo "=== $(basename "$prog") ==="
    python3 /app/analyzer.py "$prog"
    echo ""
done
