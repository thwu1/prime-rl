#!/bin/bash
set -e
mkdir -p /app/data /app/output

SERIES="CPIAUCSL GDP FEDFUNDS UNRATE M2SL DGS10 T10Y2Y PAYEMS"

for s in $SERIES; do
    echo "Downloading ${s}..."
    curl -sfL --retry 3 --retry-delay 5 \
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=${s}&cosd=1930-01-01&coed=2099-12-31" \
        -o "/app/data/${s}.csv"
    lines=$(wc -l < "/app/data/${s}.csv")
    echo "  ${s}: ${lines} rows"
    if [ "$lines" -lt 10 ]; then
        echo "ERROR: ${s} download appears incomplete (${lines} rows)"
        exit 1
    fi
done

echo "All FRED series downloaded successfully."
