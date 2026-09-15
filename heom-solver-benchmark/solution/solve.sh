#!/bin/bash

# Install dependencies
pip3 install numpy==1.26.4 scipy==1.13.1 cython==3.0.10 setuptools==69.5.1 -q
pip3 install qutip==5.0.4 -q

# Run the solver
python3 /solution/solve_helper.py
