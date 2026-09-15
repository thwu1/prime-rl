#!/bin/bash

# Initialize the configuration pipeline
cd /app && make setup

# Install the solution
cp /solution/solution_impl.py /app/mla_dsa.py
