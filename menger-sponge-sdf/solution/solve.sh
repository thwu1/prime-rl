#!/bin/bash

pip3 install manifold3d==3.0.1 -q

cp /solution/lattice_generator.py /app/lattice_generator.py

cd /app
python3 /app/lattice_generator.py
