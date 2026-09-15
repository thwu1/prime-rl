#!/bin/bash

# Copy implementation files to /app/
cp /solution/muni_calc_impl.py /app/muni_calc.py
cp /solution/reconcile_impl.sh /app/reconcile.sh
cp /solution/reconcile_helper.py /app/reconcile_helper.py
chmod +x /app/muni_calc.py /app/reconcile.sh

# Run the reconciliation pipeline
bash /app/reconcile.sh
