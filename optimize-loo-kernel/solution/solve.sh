#!/bin/bash

# Install solution dependencies
pip3 install numpy==2.1.3 -q

# ── Step 1: Fix CMakeLists.txt ──────────────────────────────────────────────
cat > /app/CMakeLists.txt << 'CMAKEOF'
cmake_minimum_required(VERSION 3.16)
project(Analytics LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(analytics src/main.cpp)

target_compile_options(analytics PRIVATE -O2 -Wall)

set_target_properties(analytics PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "/app"
)
CMAKEOF

# ── Step 2: Generate small profiling dataset (N=1000) ───────────────────────
python3 /solution/gen_small_data.py

# ── Step 3: Build naive version and profile with cachegrind ─────────────────
mkdir -p /app/build /app/output
cd /app/build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --clean-first
cd /app

# Run naive version through cachegrind with full cache simulation
# (valgrind 3.22+ defaults --cache-sim to no; must enable to collect Dr/Dw/D1m*/DLm* events)
valgrind --tool=cachegrind --cache-sim=yes \
    --cachegrind-out-file=/app/output/cg_naive.out \
    /app/analytics 2>/dev/null

# Parse naive cachegrind output file (structured .out format, not stderr)
python3 /solution/parse_cachegrind.py /app/output/cg_naive.out > /app/output/naive_metrics.json

# ── Step 4: Replace with optimized implementation ───────────────────────────
cp /solution/optimized_main.cpp /app/src/main.cpp

# ── Step 5: Rebuild optimized version ───────────────────────────────────────
cd /app/build
cmake --build . --clean-first
cd /app

# ── Step 6: Profile optimized version with cachegrind ───────────────────────
# Regenerate small data (naive run overwrote results.json but data is still there)
python3 /solution/gen_small_data.py

valgrind --tool=cachegrind --cache-sim=yes \
    --cachegrind-out-file=/app/output/cg_opt.out \
    /app/analytics 2>/dev/null

# Parse optimized cachegrind output file
python3 /solution/parse_cachegrind.py /app/output/cg_opt.out > /app/output/opt_metrics.json

# ── Step 7: Generate profiling comparison report ────────────────────────────
python3 -c "
import json

with open('/app/output/naive_metrics.json') as f:
    naive = json.load(f)
with open('/app/output/opt_metrics.json') as f:
    opt = json.load(f)

report = {
    'naive': naive,
    'optimized': opt
}

with open('/app/output/profile_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print('Profile report written to /app/output/profile_report.json')
print(f'Naive I_refs:     {naive.get(\"I_refs\", 0):>15,}')
print(f'Optimized I_refs: {opt.get(\"I_refs\", 0):>15,}')
print(f'Naive D_refs:     {naive.get(\"D_refs\", 0):>15,}')
print(f'Optimized D_refs: {opt.get(\"D_refs\", 0):>15,}')
"
