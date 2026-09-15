#!/bin/bash

# Install AI implementation
cp /solution/ai_impl.py /app/ai_player.py

# Run parameter optimization (creates optimal_params.json and analysis.db)
cd /app
python3 /solution/optimizer.py
