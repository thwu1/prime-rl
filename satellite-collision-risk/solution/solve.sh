#!/bin/bash

set -e

# Copy fixed POM
cp /solution/pom_fix.xml /app/pom.xml

# Copy fixed CdmParser
cp /solution/CdmParser.java /app/src/main/java/conjanalysis/CdmParser.java

# Copy complete CollisionAnalyzer implementation
cp /solution/CollisionAnalyzer.java /app/src/main/java/conjanalysis/CollisionAnalyzer.java

# Build with Maven
cd /app
mvn package -q

echo "Solution deployed and compiled successfully."
