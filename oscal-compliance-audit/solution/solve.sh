#!/bin/bash

cd /app

# Resolve the chained profile hierarchy using oscal-cli
# org_profile -> baseline_profile -> catalog
oscal-cli profile resolve --to=JSON org_profile.json resolved_catalog.json

# If oscal-cli resolve subcommand name differs, try alternative
if [ ! -f resolved_catalog.json ]; then
    oscal-cli profile resolve-profile --to=JSON org_profile.json resolved_catalog.json
fi

# Run the compliance analysis pipeline
python3 /solution/analyzer.py
