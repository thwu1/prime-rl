#!/usr/bin/env bash

pip3 install numpy==2.1.3 -q

# Build the C shared library
make -C /app

# Deploy Python package
cp /solution/kt_bettor.py /app/pfol/kt_bettor.py
cp /solution/olo1d.py /app/pfol/olo1d.py
cp /solution/coord_oco.py /app/pfol/coord_oco.py
cp /solution/cbce.py /app/pfol/cbce.py
cp /solution/bounds_checker.py /app/pfol/bounds_checker.py
cp /solution/__init__.py /app/pfol/__init__.py

cd /app
python3 -c "from pfol import KTBettor, OneDimOLO, CoordOCO, CBCE, BoundsChecker; print('All imports OK')"
