#!/bin/bash

# Install the solution driver and build
cp /solution/driver_solution.ml /app/src/driver.ml
cd /app && dune build
