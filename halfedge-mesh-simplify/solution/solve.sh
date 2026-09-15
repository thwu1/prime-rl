#!/usr/bin/env bash

pip3 install numpy==2.1.3 -q

# Deploy the decimation implementation
cp /solution/simplify_impl.py /app/simplify.py

# Deploy the Makefile
cp /solution/Makefile.solution /app/Makefile

# Deploy the validation script
cp /solution/validate_solution.sh /app/validate.sh
chmod +x /app/validate.sh

# Run the pipeline
make -C /app all
