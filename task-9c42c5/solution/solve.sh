#!/bin/bash

# Copy the solution implementation to /app
cp /solution/ipl_solution.v /app/IPL.v

# Compile the solution
cd /app && coqc -Q . IPL IPL.v
