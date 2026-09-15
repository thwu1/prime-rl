#!/bin/bash

set -e

# Fix 1: Makefile — add -lsqlite3 to linker flags
sed -i 's/^LDLIBS = -lm$/LDLIBS = -lm -lsqlite3/' /app/converter/Makefile

# Fix 2: converter.c — swap dimension and instance bind order
# Lines bind instance to position 3 (dimension column) and dim to position 4 (instance column)
# Fix: bind dim to position 3 and instance to position 4
sed -i 's/sqlite3_bind_int(ins_run, 3, instance);/sqlite3_bind_int(ins_run, 3, dim);/' /app/converter/converter.c
sed -i 's/sqlite3_bind_int(ins_run, 4, dim);/sqlite3_bind_int(ins_run, 4, instance);/' /app/converter/converter.c
sed -i 's/sqlite3_bind_int(find_run, 3, instance);/sqlite3_bind_int(find_run, 3, dim);/' /app/converter/converter.c
sed -i 's/sqlite3_bind_int(find_run, 4, dim);/sqlite3_bind_int(find_run, 4, instance);/' /app/converter/converter.c

# Build the converter
cd /app/converter
make clean
make
cd /app

# Import data
rm -f /app/benchmark.db
./converter/converter /app/raw_data/metadata.json /app/raw_data /app/benchmark.db

# Now fix the Python pipeline and compute results directly
python3 /solution/solve_helper.py
