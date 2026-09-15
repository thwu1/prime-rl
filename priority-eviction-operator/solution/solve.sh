#!/bin/bash

# Write the correct implementation
python3 /solution/write_solution.py

# Verify by running the tests
cd /app
mvn test -q
