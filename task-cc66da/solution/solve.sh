#!/bin/bash

set -e

pip3 install pyyaml==6.0.2

cp /solution/analyzer_solution.py /app/analyzer.py
chmod +x /app/analyzer.py

# Verify basic functionality
echo "=== Verifying query subcommand ==="
python3 /app/analyzer.py query alpha/web-frontend beta/api-server 8080
python3 /app/analyzer.py query alpha/web-frontend gamma/db-primary 5432

echo "=== Verifying query-ip subcommand ==="
python3 /app/analyzer.py query-ip 10.1.2.3 epsilon/ingress-ctrl 80
python3 /app/analyzer.py query-ip 10.255.1.1 epsilon/ingress-ctrl 80

echo "=== Verifying unprotected subcommand ==="
python3 /app/analyzer.py unprotected

echo "=== Verifying graph subcommand ==="
python3 /app/analyzer.py graph | dot -Tsvg > /dev/null
echo "Graph output validated by graphviz"
