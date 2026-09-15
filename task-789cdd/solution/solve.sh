#!/bin/bash

# Deploy solution implementations
cp -f /solution/order_matcher_impl.py /app/order_matcher.py
cp -f /solution/simulation_impl.py /app/simulation.py
cp -f /solution/scorer_impl.py /app/scorer.py

# Remove any stale bytecode cache
rm -rf /app/__pycache__
