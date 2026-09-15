#!/bin/bash

# Reference solution: builds C++ solver with CMake, extracts data from
# SQLite database, runs solver, and inserts results back into the database.

# 1. Copy solver source and CMakeLists into the project
cp /solution/solver.cpp /app/project/src/solver.cpp
cp /solution/complete_cmake.txt /app/project/CMakeLists.txt

# 2. Build with CMake
cd /app/project/build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)"

# 3. Run the pipeline: extract from DB -> solve -> insert results
python3 /solution/pipeline_helper.py /app/project/build/solver /app/lattice.db

# 4. Create the pipeline script at /app/pipeline.sh
cat > /app/pipeline.sh << 'PIPEEOF'
#!/bin/bash
# Pipeline: build solver, extract from SQLite, solve, insert results
cd /app/project/build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)"
python3 /solution/pipeline_helper.py /app/project/build/solver /app/lattice.db
PIPEEOF
chmod +x /app/pipeline.sh

# 5. Verify by querying results from the database
echo "=== Results in database ==="
sqlite3 /app/lattice.db "SELECT r.test_id, t.n, r.closure_size FROM results r JOIN test_cases t ON r.test_id = t.id ORDER BY r.test_id;"
