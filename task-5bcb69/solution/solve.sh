#!/bin/bash

# Generate the correctly-rounded cbrtf implementation by deriving
# algorithm parameters from IEEE 754 principles, then verify it
# against MPFR reference values across normal and subnormal ranges.

python3 /solution/generate_cbrtf.py
