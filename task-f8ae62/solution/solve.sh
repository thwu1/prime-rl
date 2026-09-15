#!/bin/bash


set -e

python3 /solution/solver.py

echo "Solution applied. Restarting Apache..."
service apache2 stop 2>/dev/null || true
sleep 1
service apache2 start
echo "Apache restarted. Solution complete."
