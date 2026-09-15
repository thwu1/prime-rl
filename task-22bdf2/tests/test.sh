#!/bin/bash

# Install test dependencies
pip3 install pytest==8.3.4 numpy==2.1.3 -q

mkdir -p /app/output

# Run solver for each scenario (continue on failure so pytest can report)
echo "=== Running wind_tunnel scenario ==="
timeout 180 python3 /app/solver.py /app/scenarios/wind_tunnel.toml /app/output/wind_tunnel.npz || echo "wind_tunnel solver failed"

echo "=== Running hydrostatic scenario ==="
timeout 180 python3 /app/solver.py /app/scenarios/hydrostatic.toml /app/output/hydrostatic.npz || echo "hydrostatic solver failed"

echo "=== Running channel_flow scenario ==="
timeout 180 python3 /app/solver.py /app/scenarios/channel_flow.toml /app/output/channel_flow.npz || echo "channel_flow solver failed"

echo "=== Running complex_flow scenario ==="
timeout 180 python3 /app/solver.py /app/scenarios/complex_flow.toml /app/output/complex_flow.npz || echo "complex_flow solver failed"

echo "=== Running tests ==="
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
