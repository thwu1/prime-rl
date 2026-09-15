#!/usr/bin/env bash

set -e

pip3 install pyyaml==6.0.2 -q

# Part 1: Install the Python spelling algebra engine
cp /solution/engine.py /app/engine.py

# Part 2: Set up native RIME deployment
mkdir -p /app/rime_deploy
cp /app/rime_data/challenge.schema.yaml /app/rime_deploy/
cp /app/rime_data/challenge.dict.yaml /app/rime_deploy/

# Create default.yaml configuration listing the challenge schema
python3 -c "
import yaml
config = {
    'schema_list': [{'schema': 'challenge'}],
    'menu': {'page_size': 5}
}
with open('/app/rime_deploy/default.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
"

# Build and deploy all schemas listed in default.yaml
# --build reads default.yaml from user_data_dir to discover schemas,
# compiles dictionaries (.table.bin) and prisms (.prism.bin) into build/
rime_deployer --build /app/rime_deploy /app/rime_deploy

echo "Solution deployed successfully"
