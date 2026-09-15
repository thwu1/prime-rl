#!/bin/bash

# Install dependencies
pip3 install lark==1.2.2 -q

# Copy solution files
cp /solution/ml_unify_solution.py /app/ml_unify.py
cp /solution/ml_infer_solution.py /app/ml_infer.py
cp /solution/ml_parser_solution.py /app/ml_parser.py
cp /solution/ml_cli_solution.py /app/ml_cli.py
cp /solution/grammar_solution.lark /app/grammar.lark

# Verify the solution works
cd /app
python3 -c "
from ml_parser import parse
from ml_infer import infer_program
from ml_types import TInt

# Smoke test: parse and infer '42'
t = infer_program(parse('42'))
assert isinstance(t, TInt), f'Expected TInt, got {t}'

# Smoke test: parse and infer 'fun x -> x + 1'
t = infer_program(parse('fun x -> x + 1'))
print(f'fun x -> x + 1 : {t}')

# Smoke test: let-polymorphism
t = infer_program(parse('let id = fun x -> x in (id 1, id true)'))
print(f'let-poly result: {t}')

print('All smoke tests passed.')
"
