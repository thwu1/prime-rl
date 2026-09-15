#!/usr/bin/env bash

set -euo pipefail

cd /app

# 1. Fix CMakeLists.txt — add missing source files
cat > CMakeLists.txt << 'CEOF'
cmake_minimum_required(VERSION 3.10)
project(geqsolve CXX)
set(CMAKE_CXX_STANDARD 17)
add_executable(geqsolve main.cpp activity.cpp solver.cpp)
CEOF

# 2. Fix thermo.hpp — correct van't Hoff formula (add LN10 divisor)
cp /solution/thermo_fixed.hpp /app/thermo.hpp

# 3. Fix activity.cpp — correct interpolation + implement B-dot model
cp /solution/activity_fixed.cpp /app/activity.cpp

# 4. Fix solver.cpp — correct mass balances, Jacobian, tolerance, add mineral logic
cp /solution/solver_fixed.cpp /app/solver.cpp

# 5. Build
rm -rf build
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make
cd /app

# 6. Run all five test cases
for N in 1 2 3 4 5; do
    ./build/geqsolve "/app/problem_${N}.txt" "/app/results_${N}.txt"
    echo "Case ${N} done."
done

echo "All cases solved successfully."
