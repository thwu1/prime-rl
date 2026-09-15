#!/bin/bash

cp /solution/simulate.jl /app/simulate.jl
julia /app/simulate.jl /app/circuit.json /app/output.json
