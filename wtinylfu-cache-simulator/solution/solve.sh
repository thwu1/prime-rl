#!/bin/bash

set -e

# Fix build configuration
cp /solution/build.xml /app/build.xml
cp /solution/Makefile /app/Makefile

# Fix source files
cp /solution/FrequencySketch.java /app/src/wtinylfu/FrequencySketch.java
cp /solution/WTinyLfuCache.java /app/src/wtinylfu/WTinyLfuCache.java
cp /solution/CacheSimulator.java /app/src/wtinylfu/CacheSimulator.java

# Recompile
cd /app && make
