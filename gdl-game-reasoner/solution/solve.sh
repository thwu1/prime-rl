#!/bin/bash

# Set up the GDL reasoner package
mkdir -p /app/gdl_reasoner
cp /solution/reasoner.py /app/gdl_reasoner/reasoner.py

python3 -c "
with open('/app/gdl_reasoner/__init__.py', 'w') as f:
    f.write('from .reasoner import GDLReasoner\n')
"

# Set up the GDL-to-Prolog compiler
cp /solution/gdl2prolog.py /app/gdl2prolog.py

# Run the maze solver to produce maze_solution.json
python3 /solution/maze_solver.py
