#!/bin/bash
set -e
cd /app
mkdir -p bin
javac -d bin $(find src -name '*.java')
echo "Build successful."
