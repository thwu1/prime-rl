#!/bin/bash

set -e

cd /app

# Copy fixed Java source files from solution
cp /solution/BlockParser.java src/main/java/swift/BlockParser.java
cp /solution/FieldValidator.java src/main/java/swift/FieldValidator.java
cp /solution/CrossFieldValidator.java src/main/java/swift/CrossFieldValidator.java
cp /solution/StpChecker.java src/main/java/swift/StpChecker.java
cp /solution/IbanValidator.java src/main/java/swift/IbanValidator.java
cp /solution/Pacs008Mapper.java src/main/java/swift/Pacs008Mapper.java
cp /solution/Makefile Makefile

# Run the pipeline
make all

echo "Solution applied and engine executed successfully."
