#!/bin/bash

cp /solution/solver_correct.py /app/solver.py
cd /app
python3 -c "from solver import solve_brusselator; solve_brusselator()"
