#!/bin/bash
cd /app
mkdir -p build
javac -d build src/dataflow/*.java
