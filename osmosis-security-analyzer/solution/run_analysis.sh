#!/bin/bash

set -e

for xml in /app/systems/*.xml; do
    xmllint --schema /app/spec/microkit.xsd --noout "$xml"
done

python3 /app/analyzer.py

for dot in /app/output/*_flow.dot; do
    svg="${dot%.dot}.svg"
    dot -Tsvg "$dot" -o "$svg"
done
