#!/bin/bash

cp /solution/lib_solution.rs /app/src/lib.rs
cd /app && cargo build --release
