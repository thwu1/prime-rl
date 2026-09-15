#!/bin/bash

cd /app

# Apply fixed source files
cp /solution/Curve.java src/calibrator/Curve.java
cp /solution/Pricer.java src/calibrator/Pricer.java
cp /solution/MulticurveCalibrator.java src/calibrator/MulticurveCalibrator.java
cp /solution/SensitivityEngine.java src/calibrator/SensitivityEngine.java

# Fix build script
cp /solution/build.sh /app/build.sh
chmod +x /app/build.sh

# Build and run
/app/build.sh
