#!/bin/bash

# Install fixed resolver
cp /solution/resolver.py /app/resolver
chmod +x /app/resolver

# Generate dep_analysis.json using jq
jq -f /solution/extract_deps.jq /app/metadata.json > /app/dep_analysis.json

# Generate feature graph DOT file
python3 /solution/gen_graph.py

# Render SVG with graphviz
dot -Tsvg /app/feature_graph.dot -o /app/feature_graph.svg
