#!/bin/bash

# Fix 1: SQL extraction - correct the asymptote column reference
cp /solution/extract_scenarios_fixed.sql /app/extract_scenarios.sql

# Fix 2-3: Python extrapolators - Lagrange formula + exponential asymptote subtraction
cp /solution/extrapolators_fixed.py /app/extrapolators.py

# Fix 4: Python allocator - abs(c) instead of c**2 for optimal weights
cp /solution/allocator_fixed.py /app/allocator.py

# Fix 5: Python benchmark - min error instead of max result for best_method
cp /solution/benchmark_fixed.py /app/benchmark.py

# Fix 6: jq post-processing - correct improvement ratio direction
cp /solution/postprocess_fixed.jq /app/postprocess.jq

# Fix 7: Add missing generate_measurements to noise_model.py
cp /solution/noise_model_fixed.py /app/noise_model.py

# Fix 8: Implement all zne_optimizer.py stubs
cp /solution/zne_optimizer_solution.py /app/zne_optimizer.py

# Clean and regenerate both tracks
make -C /app clean
make -C /app all
