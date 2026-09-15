#!/bin/bash
# Build and run EUR Multicurve Calibrator
set -e
mkdir -p /app/bin
javac -d /app/bin /app/src/*.java
java -cp /app/bin MulticurveCalibrator
