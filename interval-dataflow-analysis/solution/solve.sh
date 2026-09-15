#!/bin/bash

set -e

# Copy solution files to the Maven source directory
cp /solution/Interval.java /app/src/main/java/dataflow/Interval.java
cp /solution/IntervalStore.java /app/src/main/java/dataflow/IntervalStore.java
cp /solution/IntervalAnalyzer.java /app/src/main/java/dataflow/IntervalAnalyzer.java
cp /solution/Main.java /app/src/main/java/dataflow/Main.java

# Build with Maven
cd /app
mvn -q compile dependency:copy-dependencies -DoutputDirectory=target/lib

echo "Solution deployed and compiled successfully."
