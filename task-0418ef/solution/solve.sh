#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 -q

cd /app

# Copy solver implementation into /app so it is discoverable by tests
cp /solution/solver_impl.py /app/solver_impl.py

python3 /app/solver_impl.py
