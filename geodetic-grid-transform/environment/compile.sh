#!/bin/bash
cd /app
mkdir -p build
javac -d build src/gov/noaa/ngs/transform/*.java
