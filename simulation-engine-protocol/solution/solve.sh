#!/bin/bash

# Copy the solution engine implementation into /app/
cp /solution/engine_impl.py /app/engine.py

# Verify the solution loads correctly
cd /app
python3 -c "
from engine import SimulationEngine
e = SimulationEngine()
r = e.get_simulator_features()
assert len(r.features.features) > 0, 'No features reported'
r2 = e.load_world(__import__('interfaces').Resource(uri='file:///test.sdf'))
assert r2.result.result == 1, 'Load world failed'
print('Solution verified: engine initialized and world loaded successfully')
"
