#!/bin/bash

cd /app/stlc_sub

# Copy solved files over the task files
cp /solution/Subtyping_solved.v /app/stlc_sub/Subtyping.v
cp /solution/Typing_solved.v /app/stlc_sub/Typing.v
cp /solution/Algorithmic_solved.v /app/stlc_sub/Algorithmic.v

# Build
make clean
make
