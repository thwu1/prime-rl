#!/usr/bin/env bash

# Compile the C++ solver using g++ (discovered in the environment)
g++ -O2 -std=c++17 -o /app/solver /solution/solver.cpp
chmod +x /app/solver
