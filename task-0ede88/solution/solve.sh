#!/bin/bash

cd /app
gcc -O2 -o solver /solution/solver.c
./solver
