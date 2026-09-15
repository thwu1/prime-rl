#!/bin/bash

cd /app && npm install --silent 2>/dev/null

# Fix the exp_2 bug in math64x64.ts (shift off-by-one)
sed -i 's/result >>= 62n - (x >> 64n)/result >>= 63n - (x >> 64n)/' /app/src/math64x64.ts

# Install solution implementations
cp /solution/exp64x64_solution.ts /app/src/exp64x64.ts
cp /solution/yieldmath_solution.ts /app/src/yieldmath.ts
