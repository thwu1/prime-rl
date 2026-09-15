#!/bin/bash

pip3 install lark==1.2.2 -q

cd /app

# Part 1: Run interpreter on all 10 regular programs
python3 /solution/interpreter.py

# Part 2: Copy fixed buggy programs and run them
for name in dot_product find_max sum_loop; do
    cp /solution/${name}_fixed.imp /app/output/${name}_fixed.imp
done

python3 -c "
import json, sys, os
sys.path.insert(0, '/solution')
from interpreter import IMPTransformer, run_program
from lark import Lark

with open('/app/imp.lark') as f:
    grammar_text = f.read()
parser = Lark(grammar_text, start='start', parser='earley')
transformer = IMPTransformer()

for name in ['dot_product', 'find_max', 'sum_loop']:
    imp_path = os.path.join('/app/output', name + '_fixed.imp')
    out_path = os.path.join('/app/output', name + '_fixed.json')
    with open(imp_path) as f:
        source = f.read()
    tree = parser.parse(source)
    stmts = transformer.transform(tree)
    store = run_program(stmts)
    with open(out_path, 'w') as f:
        json.dump(dict(sorted(store.items())), f)
    print(f'  {name}_fixed -> {dict(sorted(store.items()))}')
"

# Part 3: Copy synthesized programs and run them
for name in gcd fibonacci sort3; do
    cp /solution/${name}_synth.imp /app/output/${name}_synth.imp
done

python3 -c "
import json, sys, os
sys.path.insert(0, '/solution')
from interpreter import IMPTransformer, run_program
from lark import Lark

with open('/app/imp.lark') as f:
    grammar_text = f.read()
parser = Lark(grammar_text, start='start', parser='earley')
transformer = IMPTransformer()

for name in ['gcd', 'fibonacci', 'sort3']:
    imp_path = os.path.join('/app/output', name + '_synth.imp')
    out_path = os.path.join('/app/output', name + '_synth.json')
    with open(imp_path) as f:
        source = f.read()
    tree = parser.parse(source)
    stmts = transformer.transform(tree)
    store = run_program(stmts)
    with open(out_path, 'w') as f:
        json.dump(dict(sorted(store.items())), f)
    print(f'  {name}_synth -> {dict(sorted(store.items()))}')
"

# Build summary.json by merging all individual regular program outputs using jq
cd /app/output
(for f in $(ls *.json | grep -v summary | grep -v _fixed | grep -v _synth | sort); do
    name="${f%.json}"
    jq -n --arg name "$name" --slurpfile data "$f" '{($name): $data[0]}'
done) | jq -s 'add' > summary.json
