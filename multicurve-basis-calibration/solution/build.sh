#!/bin/bash
set -e
mkdir -p /app/bin
javac -d /app/bin /app/src/calibrator/*.java
java -cp /app/bin calibrator.MulticurveCalibrator
