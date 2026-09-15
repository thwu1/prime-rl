#!/bin/bash

set -e

# Copy corrected source files over the buggy ones
cp /solution/MergeEngine.java /app/src/compaction/MergeEngine.java
cp /solution/CompactionSelector.java /app/src/compaction/CompactionSelector.java

# Rebuild
cd /app && ./build.sh
