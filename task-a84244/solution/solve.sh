#!/bin/bash

cd /app

# Replace the buggy triint64.ml with the fixed version
cp /solution/triint64_fixed.ml /app/triint64.ml

# Build and verify
dune build
dune exec ./main.exe
