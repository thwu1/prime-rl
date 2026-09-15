#!/bin/bash

set -e
cd /app

# Fix infrastructure bugs
python3 /solution/fix_bugs.py

# Install rule implementations
cp /solution/ConstantFolding.java src/ConstantFolding.java
cp /solution/BooleanSimplification.java src/BooleanSimplification.java
cp /solution/PredicatePushdown.java src/PredicatePushdown.java
cp /solution/NullPropagation.java src/NullPropagation.java

# Build and test
mkdir -p build
javac -d build src/*.java /tests/TestRunner.java
java -cp build TestRunner
