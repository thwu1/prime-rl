#!/bin/bash
# Build and run the CDS pricing pipeline
cd /app
rm -rf out
mkdir -p out
javac -d out src/cds/CdsPricer.java 2>&1
if [ $? -ne 0 ]; then
    echo "Compilation failed"
    exit 1
fi
java -cp out cds.CdsPricer /app/data
