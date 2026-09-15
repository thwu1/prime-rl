#!/bin/bash

set -e

# Install the model checker implementation
cp /solution/ModelChecker.java /app/src/modelchecker/ModelChecker.java

# Fix ConcurrentProgram.java: lock scanning only processes first thread.
# Must scan all threads to discover all lock names used in the program.
python3 /solution/fix_framework.py

# Fix Makefile: per-file compilation breaks cross-package references;
# wrong main class name (Main is in default package, not modelchecker).
cp /solution/Makefile /app/Makefile

# Build
cd /app && make compile

echo "Solution installed and compiled successfully."
