#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 networkx==3.4.2 -q

cp /solution/solver_impl.py /app/solver.py
python3 /app/solver.py
