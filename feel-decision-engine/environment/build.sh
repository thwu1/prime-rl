#!/bin/bash
set -e
mkdir -p /app/build
javac -d /app/build /app/src/feel/*.java
