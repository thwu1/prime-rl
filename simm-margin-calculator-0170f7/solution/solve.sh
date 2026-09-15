#!/bin/bash


# Restore data and portfolio files from backup in case agent deleted them
cp -r /app/.data.bak/* /app/data/ 2>/dev/null
cp -r /app/.portfolios.bak/* /app/portfolios/ 2>/dev/null

# Copy all corrected Java source files (including Main.java and Sensitivity.java
# to ensure agent modifications to those files don't break the solution)
cp /solution/Main.java /app/src/Main.java
cp /solution/Sensitivity.java /app/src/Sensitivity.java
cp /solution/DeltaCalculator.java /app/src/DeltaCalculator.java
cp /solution/CurvatureCalculator.java /app/src/CurvatureCalculator.java
cp /solution/RiskAggregator.java /app/src/RiskAggregator.java

# Remove any stray Java files the agent may have added
find /app/src -name '*.java' ! -name 'Main.java' ! -name 'Sensitivity.java' \
    ! -name 'DeltaCalculator.java' ! -name 'CurvatureCalculator.java' \
    ! -name 'RiskAggregator.java' -delete 2>/dev/null

# Compile
cd /app
rm -rf /app/out
mkdir -p /app/out
javac -d /app/out /app/src/*.java

# Run all portfolios
for i in 1 2 3 4 5; do
    echo "Portfolio $i:"
    java -cp /app/out Main /app/portfolios/portfolio_$i.csv
    echo ""
done
